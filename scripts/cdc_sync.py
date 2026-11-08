#!/usr/bin/env python3
"""Deterministic content-defined chunking versus fixed blocks, synthetic only.

Experimental comparison instrument, not FastCDC, CARE, a new compressor,
secure transport, or production archive. Decoder calls unbounded zstd CLI.
"""

import argparse
import json
import platform
import random
import shutil
import struct
import subprocess

from batched_sync import (compare as fixed_compare, synthetic_mutating_binary,
                          synthetic_shifted_binary)
from benchmark import evolving_corpora
from sync_baselines import (MAX_BYTES, MAX_REFS, Receiver, call_zstd,
                            parse_advertisement, scope_digest, send_full, sha)

MASK64 = (1 << 64) - 1
GEAR = tuple(random.Random(20261108 + 131 * i).getrandbits(64)
             for i in range(256))
MAGIC = b"IVCD1"
HEADER = struct.Struct("<5s32s32s32sQIIIIII")
INDEX = struct.Struct("<I")
NEW_BLOCK = struct.Struct("<32sI")


def validate_params(min_size, target_size, max_size):
    if (not all(isinstance(v, int) for v in (min_size, target_size, max_size))
            or min_size < 256 or min_size > target_size
            or target_size > max_size or max_size > 65536
            or target_size & (target_size - 1)):
        raise ValueError("invalid content-defined chunking parameters")


def cdc_chunks(data, min_size=2048, target_size=4096, max_size=8192):
    """Simple gear-hash cutpoints, with hard min/max and deterministic seed.

    The next chunk starts after each cut. Byte insertions shift at most the
    first matching boundary in a steady unchanged region. No novelty claim.
    """
    validate_params(min_size, target_size, max_size)
    if len(data) > MAX_BYTES:
        raise ValueError("synthetic snapshot too large")
    result = []
    begin = 0
    state = 0
    for pos, value in enumerate(data):
        state = ((state << 1) + GEAR[value]) & MASK64
        length = pos + 1 - begin
        if length >= min_size and ((state & (target_size - 1)) == 0
                                   or length >= max_size):
            result.append(data[begin:pos + 1])
            begin = pos + 1
            state = 0
    if begin < len(data):
        result.append(data[begin:])
    return result


def send_cdc(data, advertisement, scope, zstd,
             min_size=2048, target_size=4096, max_size=8192):
    validate_params(min_size, target_size, max_size)
    authorized_scope = scope_digest(scope)  # namespace; NOT an access control
    catalog = sorted(parse_advertisement(advertisement, authorized_scope))
    index = {key: i for i, key in enumerate(catalog)}
    pieces = cdc_chunks(data, min_size, target_size, max_size)
    if len(pieces) > MAX_REFS:
        raise ValueError("reference cap exceeded")
    unseen = {}
    fresh_positions = {}
    ordinals = []
    for piece in pieces:
        key = sha(piece)
        if key in index:
            ordinals.append(index[key])
        else:
            if key not in unseen:
                fresh_positions[key] = len(unseen)
                unseen[key] = piece
            elif unseen[key] != piece:
                raise ValueError("content digest collision")
            ordinals.append(len(catalog) + fresh_positions[key])
    if len(catalog) + len(unseen) > MAX_REFS:
        raise ValueError("chunk dictionary cap exceeded")
    frame = call_zstd(b"".join(unseen.values()), zstd) if unseen else b""
    header = HEADER.pack(MAGIC, authorized_scope, sha(advertisement), sha(data),
                         len(data), min_size, target_size, max_size,
                         len(ordinals), len(unseen), len(frame))
    encoded = (header + b"".join(INDEX.pack(i) for i in ordinals)
               + b"".join(NEW_BLOCK.pack(key, len(part))
                          for key, part in unseen.items()) + frame)
    if len(encoded) > MAX_BYTES:
        raise ValueError("encoded message cap exceeded")
    metadata = len(encoded) - len(frame)
    return encoded, {"advertisement_bytes": len(advertisement),
                     "payload_bytes": len(encoded),
                     "metadata_bytes": metadata,
                     "compressed_frame_bytes": len(frame),
                     "wire_bytes": len(advertisement) + len(encoded),
                     "new_unique_chunks": len(unseen),
                     "total_references": len(ordinals),
                     "reused_references": sum(i < len(catalog) for i in ordinals)}


def receive_cdc(packet, advertisement, receiver, zstd):
    """Atomic reconstruction for trusted synthetic frames ONLY."""
    if not HEADER.size <= len(packet) <= MAX_BYTES:
        raise ValueError("invalid CDC packet size")
    (magic, scope, ad_hash, expected_hash, length, min_size, target_size,
     max_size, nrefs, nnew, frame_len) = HEADER.unpack_from(packet)
    if magic != MAGIC or scope != receiver.scope:
        raise ValueError("invalid CDC packet scope or magic")
    validate_params(min_size, target_size, max_size)
    if (length > MAX_BYTES or nrefs > MAX_REFS or nnew > nrefs
            or bool(nrefs) != bool(length)):
        raise ValueError("invalid CDC chunk counts")
    if sha(advertisement) != ad_hash:
        raise ValueError("advertisement binding mismatch")
    known = sorted(parse_advertisement(advertisement, receiver.scope))
    if receiver.advertisement() != advertisement:
        raise ValueError("stale or damaged receiver catalog")
    if (len(known) + nnew > MAX_REFS or frame_len > MAX_BYTES
            or len(packet) != HEADER.size + nrefs * INDEX.size
                              + nnew * NEW_BLOCK.size + frame_len):
        raise ValueError("CDC packet length mismatch")
    position = HEADER.size
    refs = []
    for _ in range(nrefs):
        (value,) = INDEX.unpack_from(packet, position)
        position += INDEX.size
        if value >= len(known) + nnew:
            raise ValueError("invalid CDC chunk reference")
        refs.append(value)
    definitions = []
    seen = set(known)
    for _ in range(nnew):
        key, size = NEW_BLOCK.unpack_from(packet, position)
        position += NEW_BLOCK.size
        if key in seen or not 1 <= size <= max_size:
            raise ValueError("invalid or duplicate CDC chunk definition")
        definitions.append((key, size))
        seen.add(key)
    if {ref - len(known) for ref in refs if ref >= len(known)} != set(range(nnew)):
        raise ValueError("orphan CDC chunk")
    if bool(frame_len) != bool(nnew):
        raise ValueError("invalid CDC frame presence")
    frame = packet[position:]
    # The external zstd process is NOT constrained to max decompressed bytes.
    # Strictly synthetic trusted inputs only; not safe for hostile archives.
    decoded = call_zstd(frame, zstd, decompress=True) if frame else b""
    if len(decoded) != sum(size for _, size in definitions):
        raise ValueError("CDC dictionary data length mismatch")
    new_chunks = {}
    pos = 0
    for key, size in definitions:
        block = decoded[pos:pos + size]
        pos += size
        if sha(block) != key:
            raise ValueError("CDC block integrity mismatch")
        new_chunks[key] = block
    ordered = []
    for ref in refs:
        if ref < len(known):
            key = known[ref]
            block = receiver.chunks.get(key)
        else:
            key = definitions[ref - len(known)][0]
            block = new_chunks[key]
        if block is None or sha(block) != key:
            raise ValueError("missing or corrupted CDC receiver context")
        ordered.append(block)
    restored = b"".join(ordered)
    if len(restored) != length or sha(restored) != expected_hash:
        raise ValueError("CDC snapshot integrity mismatch")
    # Preserve the exact canonical content-defined cutpoint invariant.
    if cdc_chunks(restored, min_size, target_size, max_size) != ordered:
        raise ValueError("CDC cutpoint mismatch")
    receiver.chunks.update(new_chunks)
    return restored


def cdc_compare(name, revisions, zstd,
                min_size=2048, target_size=4096, max_size=8192):
    scope = "fictional/" + name
    receiver = Receiver(scope)
    full_bytes = cold_bytes = warm_bytes = catalog_bytes = frame_bytes = 0
    metadata_bytes = reused = 0
    peak_context = 0
    for revision in revisions:
        full_bytes += len(send_full(revision, scope, zstd))
        empty = Receiver(scope)
        empty_adv = empty.advertisement()
        cold, cold_stats = send_cdc(revision, empty_adv, scope, zstd,
                                    min_size, target_size, max_size)
        if receive_cdc(cold, empty_adv, empty, zstd) != revision:
            raise AssertionError("cold CDC exact recovery failed")
        cold_bytes += cold_stats["wire_bytes"]
        adv = receiver.advertisement()
        packet, stats = send_cdc(revision, adv, scope, zstd,
                                 min_size, target_size, max_size)
        if receive_cdc(packet, adv, receiver, zstd) != revision:
            raise AssertionError("warm CDC exact recovery failed")
        warm_bytes += stats["wire_bytes"]
        catalog_bytes += stats["advertisement_bytes"]
        frame_bytes += stats["compressed_frame_bytes"]
        metadata_bytes += stats["metadata_bytes"]
        reused += stats["reused_references"]
        peak_context = max(peak_context, receiver.stored_context_bytes())
    final_context = receiver.stored_context_bytes()
    receiver.chunks.clear()
    last_adv = receiver.advertisement()
    retry, retry_stats = send_cdc(revisions[-1], last_adv, scope, zstd,
                                  min_size, target_size, max_size)
    if receive_cdc(retry, last_adv, receiver, zstd) != revisions[-1]:
        raise AssertionError("lost-context CDC recovery failed")
    return {"wire_bytes_full_zstd": full_bytes,
            "cold_cdc_wire_bytes": cold_bytes,
            "warm_cdc_wire_bytes": warm_bytes,
            "warm_catalog_bytes": catalog_bytes,
            "warm_payload_metadata_bytes": metadata_bytes,
            "warm_frame_bytes": frame_bytes,
            "reused_chunk_references": reused,
            "retained_context_bytes_peak_lower_bound": peak_context,
            "retained_context_bytes_final_lower_bound": final_context,
            "last_snapshot_context_loss_resend_wire_bytes": retry_stats["wire_bytes"],
            "roundtrip_verified": True}


def fixture_histories():
    rng = random.Random(4492)
    return {**evolving_corpora(),
            "mutating-binary": synthetic_mutating_binary(),
            "shifted-binary": synthetic_shifted_binary(),
            "independent-noise": [rng.randbytes(12000) for _ in range(5)]}


def benchmark(zstd):
    results = []
    for name, versions in fixture_histories().items():
        cdc = cdc_compare(name, versions, zstd)
        fixed = fixed_compare(name, versions, zstd)
        if cdc["wire_bytes_full_zstd"] != fixed["stateless_full_wire_bytes"]:
            raise AssertionError("full-object baseline mismatch")
        results.append({"history": name,
                        "revisions": len(versions),
                        "original_bytes": sum(map(len, versions)),
                        "parameters": {"minimum": 2048, "target": 4096, "maximum": 8192},
                        "full_zstd_wire_bytes": cdc["wire_bytes_full_zstd"],
                        "fixed_4k_batched_warm_wire_bytes": fixed["chained_warm_batched_wire_bytes"],
                        "fixed_4k_batched_cold_wire_bytes": fixed["independent_cold_batched_wire_bytes"],
                        "fixed_context_bytes_lower_bound": fixed["receiver_context_peak_bytes_lower_bound"],
                        **cdc})
    return {"experiment": "001", "phase": "8",
            "benchmark_type": "synthetic-content-defined-vs-fixed-block-wire",
            "performance_claims_permitted": False,
            "measured_network_latency": False,
            "environment": {"python": platform.python_version(),
                            "zstd_version": subprocess.run([zstd, "--version"],
                                 capture_output=True, check=True, text=True).stdout.strip()},
            "limitations": ["Not FastCDC, not an original compression algorithm, not CARE.",
                            "All outputs are trusted synthetic input; decoder not output-bounded.",
                            "Full receiver catalog and all sender metadata bytes are counted.",
                            "Context memory is a lower bound, excluding Python and disk costs.",
                            "No real network, TLS, latency, CPU, energy, persistence or peer authentication.",
                            "The two protocols have different chunk boundary choices; compare context separately."],
            "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zstd", default=shutil.which("zstd"))
    args = parser.parse_args()
    if not args.zstd:
        parser.error("zstd CLI required")
    print(json.dumps(benchmark(args.zstd), indent=2))


if __name__ == "__main__":
    main()
