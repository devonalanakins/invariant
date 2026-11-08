#!/usr/bin/env python3
"""Deterministic, size-only starter baselines for Experiment 001.

Not a competitive codec benchmark: gzip, bz2 and lzma are included to
exercise repeatability. Add matched zstd, archive/delta/sync competitors
and resource-cost measurements before making performance claims.
"""

import argparse
import bz2
import gzip
import hashlib
import json
import lzma
import random
import subprocess
import tempfile
from pathlib import Path


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
        "repeated-bytes": (b"ABCD" * 50_000),
        "deterministic-noise": random.Random(20261108).randbytes(120_000),
    }


def run(binary: Path):
    results = []
    for name, original in corpora().items():
        with tempfile.TemporaryDirectory(prefix="invariant-bench-") as temp:
            root = Path(temp)
            source = root / "source.bin"
            package = root / "encoded.ivn"
            restored = root / "restored.bin"
            source.write_bytes(original)
            subprocess.run([str(binary), "pack", str(source), str(package)], check=True, capture_output=True)
            subprocess.run([str(binary), "verify", str(package)], check=True, capture_output=True)
            subprocess.run([str(binary), "unpack", str(package), str(restored)], check=True, capture_output=True)
            if restored.read_bytes() != original:
                raise RuntimeError(f"round-trip mismatch: {name}")
            results.append({
                "dataset": name,
                "sha256": hashlib.sha256(original).hexdigest(),
                "original_bytes": len(original),
                "invariant_v0_bytes": package.stat().st_size,
                "gzip_6_bytes": len(gzip.compress(original, compresslevel=6, mtime=0)),
                "bz2_9_bytes": len(bz2.compress(original, compresslevel=9)),
                "lzma_preset6_bytes": len(lzma.compress(original, preset=6)),
                "round_trip_exact": True,
            })
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    args = parser.parse_args()
    binary = args.binary.resolve()
    if not binary.is_file():
        parser.error(f"binary not found: {binary}")
    print(json.dumps({
        "experiment": "001",
        "benchmark_type": "starter-size-only",
        "synthetic_data": True,
        "performance_claims_permitted": False,
        "results": run(binary),
    }, indent=2))


if __name__ == "__main__":
    main()
