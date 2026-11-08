#!/usr/bin/env python3
"""Synthetic two-round, need-specific chunk synchronization baseline.

This is RESEARCH INSTRUMENTATION, not an authenticated, safe, deployed codec.
Messages are in-memory and decoded using the unbounded external zstd CLI;
never pass adversarial content or real/private data to this experiment.
"""

import argparse
import json
import platform
import random
import shutil
import struct
import subprocess

from benchmark import evolving_corpora
from sync_baselines import (BLOCK_BYTES, MAX_BYTES, MAX_REFS, Receiver,
                            call_zstd, experiment as v1_experiment,
                            scope_digest, sha)

PROBE_MAGIC = b"IVP21"
REPLY_MAGIC = b"IVR21"
DATA_MAGIC = b"IVD21"
PROBE = struct.Struct("<5s32s32sQII")
REPLY = struct.Struct("<5s32s32sI")
DATA = struct.Struct("<5s32s32sII")
LENGTH = struct.Struct("<I")
HASH_LEN = 32


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def create_probe(source, scope, block_size=BLOCK_BYTES):
    _require(1 <= block_size <= 65536 and len(source) <= MAX_BYTES,
             "invalid probe input size or block size")
    refs = [sha(source[i:i + block_size])
            for i in range(0, len(source), block_size)]
    _require(len(refs) <= MAX_REFS, "too many references")
    message = (PROBE.pack(PROBE_MAGIC, scope_digest(scope), sha(source),
                          len(source), block_size, len(refs)) + b"".join(refs))
    _require(len(message) <= MAX_BYTES, "probe too large")
    return message


def read_probe(probe, expected_scope=None):
    _require(PROBE.size <= len(probe) <= MAX_BYTES, "invalid probe size")
    magic, scope, whole_hash, size, chunk_size, count = PROBE.unpack_from(probe)
    _require(magic == PROBE_MAGIC and (expected_scope is None or scope == expected_scope),
             "invalid probe magic or scope")
    _require(size <= MAX_BYTES and 1 <= chunk_size <= 65536 and count <= MAX_REFS,
             "invalid probe length or chunk size")
    _require(count == (size + chunk_size - 1) // chunk_size,
             "probe reference count mismatch")
    _require(len(probe) == PROBE.size + count * HASH_LEN,
             "invalid probe references or trailing bytes")
    refs = [probe[PROBE.size + i * HASH_LEN:PROBE.size + (i + 1) * HASH_LEN]
            for i in range(count)]
    return scope, whole_hash, size, chunk_size, refs


def _get_bit(bitmap, index):
    return bool(bitmap[index // 8] & (1 << (index % 8)))


def _set_bit(bitmap, index):
    bitmap[index // 8] |= 1 << (index % 8)


def reply_to_probe(probe, receiver):
    scope, _, _, chunk_size, refs = read_probe(probe, receiver.scope)
    bitmap = bytearray((len(refs) + 7) // 8)
    for i, key in enumerate(refs):
        cached = receiver.chunks.get(key)
        if cached is not None and 0 < len(cached) <= chunk_size and sha(cached) == key:
            _set_bit(bitmap, i)
    reply = REPLY.pack(REPLY_MAGIC, scope, sha(probe), len(refs)) + bitmap
    _require(len(reply) <= MAX_BYTES, "reply exceeds limit")
    return bytes(reply)


def read_reply(reply, probe):
    scope, _, _, _, refs = read_probe(probe)
    _require(REPLY.size <= len(reply) <= MAX_BYTES, "invalid reply size")
    magic, reply_scope, probe_hash, count = REPLY.unpack_from(reply)
    _require(magic == REPLY_MAGIC and reply_scope == scope and probe_hash == sha(probe)
             and count == len(refs), "reply scope, probe or count mismatch")
    bits = reply[REPLY.size:]
    _require(len(bits) == (count + 7) // 8, "reply bitmap length mismatch")
    if count % 8:
        _require(bits[-1] & ~((1 << (count % 8)) - 1) == 0, "noncanonical bitmap padding")
    availability = {}
    for i, key in enumerate(refs):
        present = _get_bit(bits, i)
        previous = availability.setdefault(key, present)
        _require(previous == present, "inconsistent duplicate availability")
    return availability


def _missing_refs(refs, availability):
    ordered = []
    seen = set()
    for key in refs:
        if not availability[key] and key not in seen:
            ordered.append(key)
            seen.add(key)
    return ordered


def send_data(source, probe, reply, zstd):
    scope, whole_hash, size, chunk_size, refs = read_probe(probe)
    _require(size == len(source) and whole_hash == sha(source), "sender input mismatch")
    availability = read_reply(reply, probe)
    blocks = [source[i:i + chunk_size] for i in range(0, size, chunk_size)]
    _require([sha(x) for x in blocks] == refs, "sender references disagree")
    block_lookup = {}
    for key, block in zip(refs, blocks):
        if key in block_lookup:
            _require(block_lookup[key] == block, "collision in sender chunks")
        block_lookup[key] = block
    missing = _missing_refs(refs, availability)
    raw = b"".join(block_lookup[key] for key in missing)
    _require(len(raw) <= MAX_BYTES, "missing chunk data too large")
    frame = call_zstd(raw, zstd) if missing else b""
    message = (DATA.pack(DATA_MAGIC, scope, sha(probe), len(missing), len(frame))
               + b"".join(LENGTH.pack(len(block_lookup[key])) for key in missing)
               + frame)
    _require(len(message) <= MAX_BYTES, "data packet too large")
    return message, {"probe_bytes": len(probe), "reply_bytes": len(reply),
                     "data_bytes": len(message), "wire_bytes": len(probe) + len(reply) + len(message),
                     "missing_unique_chunks": len(missing),
                     "available_unique_chunks": sum(availability.values()),
                     "compressed_new_chunk_bytes": len(frame),
                     "data_metadata_bytes": len(message) - len(frame)}


def receive_data(probe, reply, packet, receiver, zstd):
    scope, whole_hash, size, block_size, refs = read_probe(probe, receiver.scope)
    availability = read_reply(reply, probe)
    _require(DATA.size <= len(packet) <= MAX_BYTES, "invalid data packet")
    magic, received_scope, probe_hash, count, frame_len = DATA.unpack_from(packet)
    missing = _missing_refs(refs, availability)
    _require(magic == DATA_MAGIC and received_scope == scope and probe_hash == sha(probe)
             and count == len(missing), "data packet identity or count mismatch")
    offset = DATA.size
    _require(count <= MAX_REFS and frame_len <= MAX_BYTES and
             offset + count * LENGTH.size + frame_len == len(packet),
             "data packet length mismatch")
    sizes = []
    for _ in missing:
        (raw_size,) = LENGTH.unpack_from(packet, offset)
        offset += LENGTH.size
        _require(0 < raw_size <= block_size, "invalid reconstructed chunk length")
        sizes.append(raw_size)
    _require(sum(sizes) <= MAX_BYTES, "missing chunks exceed maximum")
    frame = packet[offset:]
    _require(bool(missing) == bool(frame), "missing compressed frame")
    # External zstd decoder output is NOT memory-bounded: synthetic trusted inputs only.
    raw = call_zstd(frame, zstd, decompress=True) if missing else b""
    _require(len(raw) == sum(sizes), "decompressed chunk lengths differ")
    fresh = {}
    cursor = 0
    for key, n in zip(missing, sizes):
        block = raw[cursor:cursor + n]
        cursor += n
        _require(sha(block) == key, "new chunk digest mismatch")
        fresh[key] = block
    # The receiver may have lost context after advertising its availability.
    assembled = []
    for key in refs:
        block = fresh.get(key) if key in fresh else receiver.chunks.get(key)
        _require(block is not None and sha(block) == key,
                 "missing or corrupt context; fresh probe required")
        assembled.append(block)
    result = b"".join(assembled)
    _require(len(result) == size and sha(result) == whole_hash,
             "snapshot digest mismatch")
    # Never mutate the receiver until whole-object exact reconstruction succeeded.
    receiver.chunks.update(fresh)
    return result


def transfer(source, receiver, scope, zstd, block_size=BLOCK_BYTES):
    probe = create_probe(source, scope, block_size)
    reply = reply_to_probe(probe, receiver)
    packet, metrics = send_data(source, probe, reply, zstd)
    if receive_data(probe, reply, packet, receiver, zstd) != source:
        raise AssertionError("two-round exact reconstruction failed")
    return metrics


def experiment(family, revisions, zstd, block_size=BLOCK_BYTES):
    scope = "fictional/" + family
    live = Receiver(scope)
    warm = {key: 0 for key in ["wire_bytes", "probe_bytes", "reply_bytes",
                                 "data_bytes", "compressed_new_chunk_bytes", "data_metadata_bytes"]}
    cold = 0
    peak = 0
    reused = 0
    for snapshot in revisions:
        cold += transfer(snapshot, Receiver(scope), scope, zstd, block_size)["wire_bytes"]
        metrics = transfer(snapshot, live, scope, zstd, block_size)
        for key in warm:
            warm[key] += metrics[key]
        reused += metrics["available_unique_chunks"]
        peak = max(peak, live.stored_context_bytes())
    final_context = live.stored_context_bytes()
    live.chunks.clear()
    recovery = transfer(revisions[-1], live, scope, zstd, block_size)["wire_bytes"]
    rotated_scope = scope + "/rotated"
    rotation = transfer(revisions[-1], Receiver(rotated_scope), rotated_scope,
                        zstd, block_size)["wire_bytes"]
    return {"history": family, "block_size": block_size, "revisions": len(revisions),
            "cold_wire_bytes": cold, "warm_wire_bytes": warm["wire_bytes"],
            "warm_probe_bytes": warm["probe_bytes"],
            "warm_reply_bytes": warm["reply_bytes"],
            "warm_data_bytes": warm["data_bytes"],
            "warm_new_chunk_frame_bytes": warm["compressed_new_chunk_bytes"],
            "warm_payload_metadata_bytes": warm["data_metadata_bytes"],
            "warm_available_unique_chunk_ids": reused,
            "receiver_context_bytes_peak_lower_bound": peak,
            "receiver_context_bytes_final_lower_bound": final_context,
            "context_loss_last_snapshot_recovery_bytes": recovery,
            "scope_rotation_last_snapshot_bytes": rotation,
            "protocol_messages_per_snapshot": 3,
            "v1_protocol_messages_per_snapshot": 2,
            "roundtrip_verified": True}


def stress_histories():
    """Synthetic anti-overfitting fixtures: shifted bytes and fresh noise."""
    rng = random.Random(20261108)
    base = rng.randbytes(24 * 1024)
    shifted = []
    for revision in range(5):
        # An insertion near the beginning shifts all later fixed block boundaries.
        shifted.append((b"prefix" + bytes([revision]) * (revision + 1) + base))
    noise = [random.Random(1000 + i).randbytes(12 * 1024) for i in range(5)]
    return {"stress-shifted-binary": shifted, "stress-independent-noise": noise}


def benchmark(zstd, chunk_sizes=(BLOCK_BYTES,)):
    results = []
    histories = {**evolving_corpora(), **stress_histories()}
    for name, revisions in histories.items():
        v1 = v1_experiment(name, revisions, zstd)
        for chunk_size in chunk_sizes:
            results.append({"history": name, "v1_full_zstd_wire_bytes": v1["stateless_full_zstd_wire_bytes"],
                            "v1_warm_wire_bytes": v1["warm_chained_delta_wire_bytes"],
                            "v1_block_size": BLOCK_BYTES,
                            "v1_cold_wire_bytes": v1["cold_independent_delta_wire_bytes"],
                            **experiment(name, revisions, zstd, chunk_size)})
    return {"experiment": "001", "phase": "6", "benchmark_type": "synthetic-two-round-exchange",
            "performance_claims_permitted": False,
            "environment": {"platform": platform.platform(), "zstd_version":
                            subprocess.run([zstd, "--version"],
                            capture_output=True, text=True, check=True).stdout.strip()},
            "limitations": [
                "Only fictional in-memory messages; no network or authorization.",
                "Probe, reply and payload bytes all counted; network round-trip latency is not measured.",
                "Chunk advertisements expose hashes; namespace digests are not authentication.",
                "Receiver context bytes are lower-bound raw content plus IDs only.",
                "Zstd CLI decode is not bounded against malicious frames; do not deploy.",
                "Protocol v2 batches missing chunks into a single Zstandard frame; no novel codec.",
            ], "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zstd", default=shutil.which("zstd"))
    parser.add_argument("--chunk-sizes", default="1024,4096,16384")
    args = parser.parse_args()
    if not args.zstd:
        parser.error("zstd CLI is required")
    sizes = tuple(int(x) for x in args.chunk_sizes.split(","))
    print(json.dumps(benchmark(args.zstd, sizes), indent=2))


if __name__ == "__main__":
    main()
