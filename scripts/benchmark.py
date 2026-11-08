#!/usr/bin/env python3
"""Synthetic, lossless, stateless baseline comparisons for Experiment 001.

All recorded sizes include their individual container/frame overhead. Timings
are diagnostic only: subprocess startup and Python execution are not normalized.
No contextual compression, archival deduplication, or network sync is measured.
"""

import argparse
import bz2
import gzip
import hashlib
import json
import lzma
import platform
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CODECS = ("invariant_v0", "zstd_3", "gzip_6", "bz2_9", "lzma_6", "raw")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def corpora():
    rows = []
    for i in range(2500):
        row = {
            "event": ["edit", "read", "commit", "read"][i % 4],
            "file": f"project/{i % 19}/README.md",
            "revision": i // 19,
            "status": "verified",
            "tag": "synthetic-only",
        }
        rows.append(json.dumps(row, sort_keys=True, separators=(",", ":")))
    return {
        "empty": b"",
        "structured-jsonl": ("\n".join(rows) + "\n").encode("utf-8"),
        "repeated-bytes": b"ABCD" * 50_000,
        "deterministic-noise": random.Random(20261108).randbytes(120_000),
    }


def evolving_corpora():
    """Return synthetic histories. No private, user, or production content."""
    modules = {
        f"src/module_{i:03}.rs": (
            f"// Synthetic module {i}\n"
            f"pub fn value_{i}(x: u64) -> u64 {{ x.wrapping_add({i}) }}\n"
            + "// Generated invariant fixture, no user data.\n" * 4
        )
        for i in range(96)
    }
    rows = [
        {"id": i, "kind": ["read", "edit", "build"][i % 3], "revision": 0,
         "value": i % 17, "tag": "fictional-event"}
        for i in range(500)
    ]
    histories = {"evolving-code": [], "evolving-events": []}
    for revision in range(5):
        if revision:
            i = (revision * 17) % len(modules)
            key = f"src/module_{i:03}.rs"
            modules[key] += f"// synthetic patch {revision}\n"
            rows[revision * 23]["revision"] = revision
            rows[revision * 23]["value"] += revision
        code = "".join(f"=== {path} ===\n{value}" for path, value in sorted(modules.items()))
        events = "\n".join(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows) + "\n"
        histories["evolving-code"].append(code.encode("utf-8"))
        histories["evolving-events"].append(events.encode("utf-8"))
    return histories


def execute(args, *, input_bytes=None):
    return subprocess.run(args, input=input_bytes, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=True).stdout


def encode(codec, source, original, binary, zstd, workdir):
    start = time.perf_counter_ns()
    if codec == "invariant_v0":
        destination = workdir / "package.ivn"
        execute([str(binary), "pack", str(source), str(destination)])
        result = destination.read_bytes()
        destination.unlink()
    elif codec == "zstd_3":
        result = execute([zstd, "-3", "-q", "-c", str(source)])
    elif codec == "gzip_6":
        result = gzip.compress(original, compresslevel=6, mtime=0)
    elif codec == "bz2_9":
        result = bz2.compress(original, compresslevel=9)
    elif codec == "lzma_6":
        result = lzma.compress(original, preset=6)
    else:
        result = original
    return result, (time.perf_counter_ns() - start) / 1_000_000


def decode(codec, encoded, binary, zstd, workdir):
    start = time.perf_counter_ns()
    if codec == "invariant_v0":
        package = workdir / "verify.ivn"
        restored = workdir / "restored.bin"
        package.write_bytes(encoded)
        execute([str(binary), "verify", str(package)])
        execute([str(binary), "unpack", str(package), str(restored)])
        result = restored.read_bytes()
        restored.unlink()
        package.unlink()
    elif codec == "zstd_3":
        result = execute([zstd, "-d", "-q", "-c"], input_bytes=encoded)
    elif codec == "gzip_6":
        result = gzip.decompress(encoded)
    elif codec == "bz2_9":
        result = bz2.decompress(encoded)
    elif codec == "lzma_6":
        result = lzma.decompress(encoded)
    else:
        result = encoded
    return result, (time.perf_counter_ns() - start) / 1_000_000


def measure_case(name, original, binary, zstd, repetitions):
    measurements = {}
    with tempfile.TemporaryDirectory(prefix="invariant-bench-") as temp:
        root = Path(temp)
        source = root / "source.bin"
        source.write_bytes(original)
        for codec in CODECS:
            enc_times, dec_times, first = [], [], None
            for _ in range(repetitions):
                encoded, enc_ms = encode(codec, source, original, binary, zstd, root)
                decoded, dec_ms = decode(codec, encoded, binary, zstd, root)
                if decoded != original:
                    raise RuntimeError(f"lossless verification failed: {name} / {codec}")
                if first is not None and first != encoded:
                    raise RuntimeError(f"nondeterministic output: {name} / {codec}")
                first = encoded
                enc_times.append(enc_ms)
                dec_times.append(dec_ms)
            measurements[codec] = {
                "encoded_bytes": len(first),
                "lossless_verified": True,
                "encode_wall_ms_median_diagnostic": round(statistics.median(enc_times), 3),
                "decode_wall_ms_median_diagnostic": round(statistics.median(dec_times), 3),
            }
    return {"dataset": name, "sha256": digest(original),
            "original_bytes": len(original), "codecs": measurements}


def run(binary, zstd=None, repetitions=3):
    binary = Path(binary).resolve()
    if not binary.is_file():
        raise FileNotFoundError(f"INVARIANT binary not found: {binary}")
    zstd = zstd or shutil.which("zstd")
    if not zstd:
        raise FileNotFoundError("zstd CLI is required for independent Zstandard baseline")
    zstd_version = execute([zstd, "--version"]).decode("utf-8", "replace").strip()
    results = [measure_case(name, data, binary, zstd, repetitions)
               for name, data in corpora().items()]
    totals = []
    for family, revisions in evolving_corpora().items():
        cases = [measure_case(f"{family}/r{i:02}", data, binary, zstd, repetitions)
                 for i, data in enumerate(revisions)]
        results.extend(cases)
        totals.append({
            "history": family,
            "revisions": len(cases),
            "total_original_bytes": sum(c["original_bytes"] for c in cases),
            "independent_full_snapshot_bytes": {
                codec: sum(c["codecs"][codec]["encoded_bytes"] for c in cases)
                for codec in CODECS
            },
            "shared_context_bytes": 0,
            "scope": "independent-stateless-full-snapshots-not-delta-sync",
        })
    return {
        "experiment": "001",
        "schema_version": 2,
        "benchmark_type": "synthetic-stateless-full-object",
        "synthetic_data": True,
        "performance_claims_permitted": False,
        "measurement_limits": [
            "Timing includes different Python/subprocess and file-I/O costs; no fair speed ranking.",
            "No peak memory, energy, cold/warm sync, deduplication or context creation measured.",
            "Full snapshot totals are not actual incremental network transfer measurements.",
        ],
        "environment": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "binary_sha256": digest(binary.read_bytes()),
            "zstd_version": zstd_version,
            "repetitions": repetitions,
        },
        "results": results,
        "history_totals": totals,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--zstd", default=None, help="Path to zstd CLI (defaults to PATH)")
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.repetitions <= 20:
        parser.error("--repetitions must be between 1 and 20")
    print(json.dumps(run(args.binary, args.zstd, args.repetitions), indent=2))


if __name__ == "__main__":
    main()
