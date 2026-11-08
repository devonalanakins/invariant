#!/usr/bin/env python3
"""Indexed references and batched Zstandard for synthetic receiver-scoped sync.

This is a comparison instrument, NOT a deployable protocol or original codec.
There is no authentication or output-bounded decompression. Never feed it
untrusted input or use it for production archives or network synchronization.
"""

import argparse
import hashlib
import json
import platform
import subprocess
import random
import shutil
import struct

from benchmark import evolving_corpora
from sync_baselines import (BLOCK_BYTES, MAX_BYTES, MAX_REFS, Receiver, blocks,
                            call_zstd, experiment, parse_advertisement,
                            scope_digest, send_full, sha)

MAGIC = b"IVBT1"
HEADER = struct.Struct("<5s32s32s32sQIIII")
NEW_BLOCK = struct.Struct("<32sI")
INDEX = struct.Struct("<I")


def send_batched(snapshot, advertisement, scope, zstd, chunk_size=BLOCK_BYTES):
    """Build exactly one compressed frame for all newly transmitted chunks."""
    authorized_scope = scope_digest(scope)  # namespace only; NOT authorization
    known = sorted(parse_advertisement(advertisement, authorized_scope))
    known_indexes = {key: index for index, key in enumerate(known)}
    parts = blocks(snapshot, chunk_size)
    if len(parts) > MAX_REFS or len(snapshot) > MAX_BYTES:
        raise ValueError("snapshot exceeds experiment cap")

    missing = {}
    new_indexes = {}
    references = []
    for part in parts:
        key = sha(part)
        if key in known_indexes:
            references.append(known_indexes[key])
            continue
        if key not in missing:
            new_indexes[key] = len(missing)
            missing[key] = part
        elif missing[key] != part:
            raise ValueError("SHA-256 collision")
        references.append(len(known) + new_indexes[key])

    if len(missing) + len(known) > MAX_REFS:
        raise ValueError("combined dictionary too large")
    if missing:
        frame = call_zstd(b"".join(missing.values()), zstd)
    else:
        frame = b""
    if len(frame) > MAX_BYTES:
        raise ValueError("frame too large")

    header = HEADER.pack(MAGIC, authorized_scope, sha(advertisement),
                         sha(snapshot), len(snapshot), chunk_size,
                         len(references), len(missing), len(frame))
    ref_data = b"".join(INDEX.pack(index) for index in references)
    missing_headers = b"".join(NEW_BLOCK.pack(key, len(value))
                               for key, value in missing.items())
    packet = header + ref_data + missing_headers + frame
    if len(packet) > MAX_BYTES:
        raise ValueError("packet too large")
    metadata = len(header) + len(ref_data) + len(missing_headers)
    return packet, {
        "advertisement_bytes": len(advertisement),
        "payload_bytes": len(packet),
        "metadata_bytes": metadata,
        "compressed_frame_bytes": len(frame),
        "total_wire_bytes": len(advertisement) + len(packet),
        "reused_references": sum(1 for index in references if index < len(known)),
        "new_chunks": len(missing),
    }


def receive_batched(packet, advertisement, receiver, zstd):
    """Reconstruct atomically; only valid on trusted synthetic fixtures."""
    if len(packet) < HEADER.size or len(packet) > MAX_BYTES:
        raise ValueError("invalid packet size")
    (magic, scope, advertisement_hash, expected_hash, raw_len, block_size,
     nrefs, nnew, frame_size) = HEADER.unpack_from(packet)
    if (magic != MAGIC or scope != receiver.scope or raw_len > MAX_BYTES or
            not 1 <= block_size <= 65536 or nrefs > MAX_REFS or
            nrefs != (raw_len + block_size - 1) // block_size or
            nnew > nrefs or frame_size > MAX_BYTES):
        raise ValueError("invalid header, scope or size")
    if sha(advertisement) != advertisement_hash:
        raise ValueError("incorrect advertisement digest")
    known = sorted(parse_advertisement(advertisement, receiver.scope))
    if receiver.advertisement() != advertisement:
        raise ValueError("stale or corrupt receiver advertisement")
    if len(known) + nnew > MAX_REFS:
        raise ValueError("dictionary limit")
    expected_len = HEADER.size + nrefs * INDEX.size + nnew * NEW_BLOCK.size + frame_size
    if expected_len != len(packet):
        raise ValueError("truncated or trailing packet")

    pos = HEADER.size
    indexes = []
    for _ in range(nrefs):
        index, = INDEX.unpack_from(packet, pos)
        if index >= len(known) + nnew:
            raise ValueError("invalid chunk reference index")
        indexes.append(index)
        pos += INDEX.size

    descriptions = []
    seen_keys = set()
    known_set = set(known)
    for _ in range(nnew):
        key, length = NEW_BLOCK.unpack_from(packet, pos)
        pos += NEW_BLOCK.size
        if not 1 <= length <= block_size or key in known_set or key in seen_keys:
            raise ValueError("invalid or duplicate new chunk")
        descriptions.append((key, length))
        seen_keys.add(key)
    if set(index for index in indexes if index >= len(known)) != set(range(len(known), len(known) + nnew)):
        raise ValueError("orphan new chunks")

    frame = packet[pos:]
    if bool(frame) != bool(nnew):
        raise ValueError("invalid frame presence")
    raw = call_zstd(frame, zstd, decompress=True) if frame else b""
    if len(raw) != sum(length for _, length in descriptions):
        raise ValueError("batch data size mismatch")
    fresh = {}
    pos = 0
    for key, length in descriptions:
        block = raw[pos:pos + length]
        pos += length
        if sha(block) != key:
            raise ValueError("chunk digest mismatch")
        fresh[key] = block
    chunks = []
    for index in indexes:
        if index < len(known):
            key = known[index]
            block = receiver.chunks.get(key)
        else:
            key = descriptions[index - len(known)][0]
            block = fresh[key]
        if block is None or sha(block) != key:
            raise ValueError("missing or corrupt local context")
        chunks.append(block)
    restored = b"".join(chunks)
    if len(restored) != raw_len or sha(restored) != expected_hash:
        raise ValueError("incorrect reconstructed snapshot")
    receiver.chunks.update(fresh)
    return restored


def synthetic_mutating_binary():
    """A deliberately favorable counterexample: large stable high-entropy bytes."""
    rng = random.Random(20261108)
    current = bytearray(rng.randbytes(256 * 1024))
    revisions = []
    for revision in range(5):
        if revision:
            offset = revision * 7 * BLOCK_BYTES
            current[offset:offset + BLOCK_BYTES] = rng.randbytes(BLOCK_BYTES)
        revisions.append(bytes(current))
    return revisions


def synthetic_shifted_binary():
    """Fixed boundaries lose reuse when incompressible bytes shift by one."""
    rng = random.Random(20261109)
    current = rng.randbytes(128 * 1024)
    revisions = [current]
    for _ in range(4):
        current = b"X" + current
        revisions.append(current)
    return revisions


def compare(family, revisions, zstd):
    scope = "fictional/" + family
    receiver = Receiver(scope)
    full_wire = cold_wire = warm_wire = ad_bytes = metadata_bytes = 0
    peak_context = 0
    for snapshot in revisions:
        full_wire += len(send_full(snapshot, scope, zstd))
        empty = Receiver(scope)
        cold_packet, cold_stats = send_batched(snapshot, empty.advertisement(), scope, zstd)
        if receive_batched(cold_packet, empty.advertisement(), empty, zstd) != snapshot:
            raise AssertionError("cold reconstruction mismatch")
        cold_wire += cold_stats["total_wire_bytes"]

        advertisement = receiver.advertisement()
        packet, stats = send_batched(snapshot, advertisement, scope, zstd)
        if receive_batched(packet, advertisement, receiver, zstd) != snapshot:
            raise AssertionError("warm reconstruction mismatch")
        warm_wire += stats["total_wire_bytes"]
        ad_bytes += stats["advertisement_bytes"]
        metadata_bytes += stats["metadata_bytes"]
        peak_context = max(peak_context, receiver.stored_context_bytes())
    cached = receiver.stored_context_bytes()
    receiver.chunks.clear()
    request = receiver.advertisement()
    retry, retry_stats = send_batched(revisions[-1], request, scope, zstd)
    if receive_batched(retry, request, receiver, zstd) != revisions[-1]:
        raise AssertionError("context loss retry failed")
    return {
        "history": family,
        "revisions": len(revisions),
        "original_bytes": sum(map(len, revisions)),
        "stateless_full_wire_bytes": full_wire,
        "independent_cold_batched_wire_bytes": cold_wire,
        "chained_warm_batched_wire_bytes": warm_wire,
        "warm_advertisement_bytes": ad_bytes,
        "warm_sender_metadata_bytes": metadata_bytes,
        "receiver_context_storage_bytes_lower_bound": cached,
        "receiver_context_peak_bytes_lower_bound": peak_context,
        "context_loss_resend_bytes": retry_stats["total_wire_bytes"],
        "roundtrip_verified": True,
    }


def run(zstd):
    histories = evolving_corpora()
    histories["mutating-binary"] = synthetic_mutating_binary()
    histories["shifted-binary"] = synthetic_shifted_binary()
    results = [compare(name, revisions, zstd) for name, revisions in histories.items()]
    prior = {name: experiment(name, revisions, zstd)["warm_chained_delta_wire_bytes"]
             for name, revisions in histories.items()}
    for result in results:
        result["legacy_per_chunk_warm_wire_bytes"] = prior[result["history"]]
    return {
        "experiment": "001",
        "phase": "5",
        "benchmark_type": "fictional-batched-chunk-wire-simulation",
        "synthetic": True,
        "performance_claims_permitted": False,
        "environment": {
            "python": platform.python_version(),
            "zstd_version": subprocess.run([zstd, "--version"], capture_output=True,
                                           check=True, text=True).stdout.strip(),
            "block_bytes": BLOCK_BYTES,
        },
        "limitations": [
            "No network, authentication, encryption or bounded external decoder.",
            "Warm advertisement and all sender framing counted; context storage is a lower bound.",
            "The experimental indexed format and batching use known existing techniques, not CARE.",
            "Only fictional fixtures, including one deliberately favorable high-entropy history.",
            "No normalized CPU, memory, energy or real transfer failure measurements.",
        ],
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zstd", default=shutil.which("zstd"))
    args = parser.parse_args()
    if not args.zstd:
        parser.error("zstd CLI required")
    print(json.dumps(run(args.zstd), indent=2))


if __name__ == "__main__":
    main()
