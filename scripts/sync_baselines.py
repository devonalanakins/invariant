#!/usr/bin/env python3
"""Synthetic cold/warm synchronization baseline with counted wire bytes.

Research-only simulation: no network, authentication, encrypted transport,
negotiation, streaming, or hardened untrusted-data decoder. All context is
synthetic and limited to one explicitly configured scope.
"""

import argparse
import hashlib
import json
import platform
import shutil
import struct
import subprocess
from pathlib import Path

from benchmark import evolving_corpora

BLOCK_BYTES = 4096
MAX_BYTES = 64 * 1024 * 1024
MAX_REFS = 16384
MAGIC_AD = b"IVAD1"
MAGIC_DELTA = b"IVDL1"
MAGIC_FULL = b"IVFL1"
ADVERTISEMENT = struct.Struct("<5s32sI")
DELTA = struct.Struct("<5s32s32sQIII")
FULL = struct.Struct("<5s32s32sQI")
CHUNK = struct.Struct("<32sII")
UINT = struct.Struct("<I")
DIGEST_BYTES = 32


def sha(data):
    return hashlib.sha256(data).digest()


def scope_digest(name):
    if not isinstance(name, str) or not name or len(name.encode("utf-8")) > 128:
        raise ValueError("scope name must be 1-128 UTF-8 bytes")
    return sha(b"INVARIANT/synthetic-scope/v1\0" + name.encode("utf-8"))


def call_zstd(data, zstd, decompress=False):
    args = [zstd, "-d", "-q", "-c"] if decompress else [zstd, "-3", "-q", "-c"]
    return subprocess.run(args, input=data, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=True, timeout=30).stdout


def blocks(snapshot, size=BLOCK_BYTES):
    if not 1 <= size <= 65536 or len(snapshot) > MAX_BYTES:
        raise ValueError("invalid snapshot length or chunk size")
    return [snapshot[i:i + size] for i in range(0, len(snapshot), size)]


class Receiver:
    def __init__(self, scope):
        self.scope = scope_digest(scope)
        self.chunks = {}  # digest -> verified bytes, scoped to this receiver

    def stored_context_bytes(self):
        """Lower bound: raw chunk contents and 32-byte digest keys only."""
        return sum(len(key) + len(chunk) for key, chunk in self.chunks.items())

    def advertisement(self):
        # Never claim possession of a damaged chunk: re-download it instead.
        known = sorted(key for key, chunk in self.chunks.items()
                       if len(key) == DIGEST_BYTES and sha(chunk) == key)
        if len(known) > MAX_REFS:
            raise ValueError("advertisement exceeds research limit")
        return ADVERTISEMENT.pack(MAGIC_AD, self.scope, len(known)) + b"".join(known)


def parse_advertisement(packet, scope):
    if len(packet) < ADVERTISEMENT.size or len(packet) > MAX_BYTES:
        raise ValueError("invalid receiver advertisement")
    magic, identifier, count = ADVERTISEMENT.unpack_from(packet)
    if magic != MAGIC_AD or identifier != scope or count > MAX_REFS:
        raise ValueError("wrong scope or invalid receiver advertisement")
    if len(packet) != ADVERTISEMENT.size + DIGEST_BYTES * count:
        raise ValueError("truncated or trailing receiver advertisement")
    ids = [packet[ADVERTISEMENT.size + i * DIGEST_BYTES:
                  ADVERTISEMENT.size + (i + 1) * DIGEST_BYTES] for i in range(count)]
    if ids != sorted(set(ids)):
        raise ValueError("receiver advertisement is not canonical")
    return set(ids)


def send_delta(snapshot, advertisement, scope, zstd, chunk_size=BLOCK_BYTES):
    if len(snapshot) > MAX_BYTES:
        raise ValueError("snapshot exceeds experimental limit")
    known = parse_advertisement(advertisement, scope_digest(scope))
    parts = blocks(snapshot, chunk_size)
    if len(parts) > MAX_REFS:
        raise ValueError("too many block references")
    hashes = [sha(part) for part in parts]
    missing = {}
    for key, part in zip(hashes, parts):
        if key not in known:
            previous = missing.setdefault(key, part)
            if previous != part:
                raise ValueError("content-addressed collision")
    frames = []
    for key, part in missing.items():
        frame = call_zstd(part, zstd)
        frames.append(CHUNK.pack(key, len(part), len(frame)) + frame)
    header = DELTA.pack(MAGIC_DELTA, scope_digest(scope), sha(snapshot),
                        len(snapshot), chunk_size, len(hashes), len(missing))
    packet = header + b"".join(hashes) + b"".join(frames)
    if len(packet) > MAX_BYTES:
        raise ValueError("packet exceeds experimental limit")
    metadata = DELTA.size + DIGEST_BYTES * len(hashes) + CHUNK.size * len(missing)
    return packet, {
        "advertisement_bytes": len(advertisement),
        "payload_bytes": len(packet),
        "metadata_bytes": metadata,
        "compressed_chunk_bytes": len(packet) - metadata,
        "new_chunks": len(missing),
        "reused_references": len(hashes) - sum(key in missing for key in hashes),
        "total_wire_bytes": len(packet) + len(advertisement),
    }


def receive_delta(packet, receiver, zstd):
    """Apply atomically; only for trusted synthetic inputs, never hostile data."""
    if len(packet) < DELTA.size or len(packet) > MAX_BYTES:
        raise ValueError("invalid delta size")
    magic, scope, expected, size, block_size, count, new_count = DELTA.unpack_from(packet)
    if (magic != MAGIC_DELTA or scope != receiver.scope or size > MAX_BYTES or
            not 1 <= block_size <= 65536 or count > MAX_REFS or
            count != (size + block_size - 1) // block_size or new_count > count):
        raise ValueError("invalid delta header or scope")
    offset = DELTA.size
    if len(packet) < offset + DIGEST_BYTES * count:
        raise ValueError("truncated delta references")
    refs = [packet[offset + DIGEST_BYTES * i:offset + DIGEST_BYTES * (i + 1)]
            for i in range(count)]
    offset += DIGEST_BYTES * count
    fresh = {}
    for _ in range(new_count):
        if len(packet) < offset + CHUNK.size:
            raise ValueError("truncated delta chunk header")
        key, raw_len, encoded_len = CHUNK.unpack_from(packet, offset)
        offset += CHUNK.size
        if (key in fresh or not 1 <= raw_len <= block_size or
                not 1 <= encoded_len <= MAX_BYTES or
                encoded_len > len(packet) - offset):
            raise ValueError("invalid chunk declaration")
        data = call_zstd(packet[offset:offset + encoded_len], zstd, decompress=True)
        offset += encoded_len
        if len(data) != raw_len or sha(data) != key:
            raise ValueError("chunk integrity failure")
        fresh[key] = data
    if offset != len(packet):
        raise ValueError("trailing delta bytes")
    assembled = []
    for key in refs:
        part = fresh.get(key)
        if part is None:
            part = receiver.chunks.get(key)
        if part is None or sha(part) != key:
            raise ValueError("missing or corrupt receiver context; resend required")
        assembled.append(part)
    result = b"".join(assembled)
    if len(result) != size or sha(result) != expected:
        raise ValueError("reconstructed snapshot mismatch")
    # Commit only after verifying every transmitted chunk and the full snapshot.
    receiver.chunks.update(fresh)
    return result


def send_full(snapshot, scope, zstd):
    if len(snapshot) > MAX_BYTES:
        raise ValueError("snapshot exceeds experimental limit")
    frame = call_zstd(snapshot, zstd)
    packet = FULL.pack(MAGIC_FULL, scope_digest(scope), sha(snapshot),
                       len(snapshot), len(frame)) + frame
    if len(packet) > MAX_BYTES:
        raise ValueError("full packet exceeds experimental limit")
    return packet


def receive_full(packet, scope, zstd):
    if len(packet) < FULL.size or len(packet) > MAX_BYTES:
        raise ValueError("invalid full packet length")
    magic, identifier, expected, size, frame_size = FULL.unpack_from(packet)
    if (magic != MAGIC_FULL or identifier != scope_digest(scope) or
            size > MAX_BYTES or len(packet) != FULL.size + frame_size):
        raise ValueError("invalid full packet or scope")
    result = call_zstd(packet[FULL.size:], zstd, decompress=True)
    if len(result) != size or sha(result) != expected:
        raise ValueError("full packet integrity failure")
    return result


def experiment(history, revisions, zstd):
    scope = "fictional/" + history
    receiver = Receiver(scope)
    full_total = 0
    cold_total = 0
    warm_total = 0
    warm_catalog = 0
    warm_payload = 0
    warm_metadata = 0
    reused = 0
    peak_context = 0
    for snapshot in revisions:
        full = send_full(snapshot, scope, zstd)
        if receive_full(full, scope, zstd) != snapshot:
            raise AssertionError("full baseline failed")
        full_total += len(full)
        empty = Receiver(scope)
        advertisement = empty.advertisement()
        cold, cold_metrics = send_delta(snapshot, advertisement, scope, zstd)
        if receive_delta(cold, empty, zstd) != snapshot:
            raise AssertionError("cold sync failed")
        cold_total += cold_metrics["total_wire_bytes"]
        advertisement = receiver.advertisement()
        delta, warm_metrics = send_delta(snapshot, advertisement, scope, zstd)
        if receive_delta(delta, receiver, zstd) != snapshot:
            raise AssertionError("warm sync failed")
        warm_total += warm_metrics["total_wire_bytes"]
        warm_catalog += warm_metrics["advertisement_bytes"]
        warm_payload += warm_metrics["payload_bytes"]
        warm_metadata += warm_metrics["metadata_bytes"]
        reused += warm_metrics["reused_references"]
        peak_context = max(peak_context, receiver.stored_context_bytes())
    final_context = receiver.stored_context_bytes()
    final_context_chunks = len(receiver.chunks)
    # Explicit context-loss recovery: no stale references are advertised.
    receiver.chunks.clear()
    retry_adv = receiver.advertisement()
    retry_packet, retry_metrics = send_delta(revisions[-1], retry_adv, scope, zstd)
    if receive_delta(retry_packet, receiver, zstd) != revisions[-1]:
        raise AssertionError("lost-context retry failed")
    # Scope rotation must not silently preserve access to old cached context.
    rotated = Receiver(scope + "/rotated")
    rotated_packet, rotated_metrics = send_delta(revisions[-1], rotated.advertisement(),
                                                 scope + "/rotated", zstd)
    if receive_delta(rotated_packet, rotated, zstd) != revisions[-1]:
        raise AssertionError("scope-rotation cold retry failed")
    return {
        "history": history,
        "revisions": len(revisions),
        "original_bytes": sum(len(x) for x in revisions),
        "stateless_full_zstd_wire_bytes": full_total,
        "cold_independent_delta_wire_bytes": cold_total,
        "warm_chained_delta_wire_bytes": warm_total,
        "warm_catalog_bytes": warm_catalog,
        "warm_payload_bytes": warm_payload,
        "warm_payload_metadata_bytes": warm_metadata,
        "warm_reused_references": reused,
        "warm_context_stored_bytes_peak_lower_bound": peak_context,
        "warm_context_stored_bytes_final_lower_bound": final_context,
        "warm_context_unique_chunks_final": final_context_chunks,
        "context_loss_last_snapshot_resend_bytes": retry_metrics["total_wire_bytes"],
        "scope_rotation_last_snapshot_resend_bytes": rotated_metrics["total_wire_bytes"],
        "roundtrip_verified": True,
    }


def benchmark(zstd):
    return {
        "experiment": "001",
        "phase": "4",
        "benchmark_type": "fictional-in-memory-wire-protocol-simulation",
        "performance_claims_permitted": False,
        "environment": {
            "python_platform": platform.platform(),
            "zstd_version": subprocess.run([zstd, "--version"], check=True,
                                           capture_output=True, text=True).stdout.strip(),
            "block_bytes": BLOCK_BYTES,
        },
        "limitations": [
            "Only synthetic data. No real network or authenticated receiver.",
            "Exact packet and advertisement byte lengths are counted; transport framing, TLS and retries are not.",
            "Fixed block boundaries; the cold/warm comparison is not a mature sync engine.",
            "Receiver catalog leaks chunk fingerprints; do not deploy or cross privacy scopes.",
            "Context storage counts chunk bytes plus 32-byte IDs only, excluding Python/disk/index overhead.",
            "Decoder uses external zstd without bounded output and accepts trusted synthetic inputs only.",
            "No CPU/memory/energy equivalence, statistical confidence or novelty claim.",
        ],
        "results": [experiment(history, revisions, zstd)
                    for history, revisions in evolving_corpora().items()],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zstd", default=shutil.which("zstd"))
    args = parser.parse_args()
    if not args.zstd:
        parser.error("zstd command is required")
    print(json.dumps(benchmark(args.zstd), indent=2))


if __name__ == "__main__":
    main()
