#!/usr/bin/env python3
"""Self-contained chunk and real Git-history baselines for fictional data.

This is research instrumentation, not a new codec or safe archive format.
The chunk package is decoded in memory and MUST NOT be used on untrusted files.
"""

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import tempfile
import time
from pathlib import Path

from benchmark import evolving_corpora

MAGIC = b"IVCB1"
HEADER = struct.Struct("<5sIIIQQ")
ENTRY = struct.Struct("<32sI")
REVISION = struct.Struct("<32sQI")
REF = struct.Struct("<I")
BLOCK_SIZE = 4096
MAX_HISTORY_BYTES = 64 * 1024 * 1024


def digest(data):
    return hashlib.sha256(data).digest()


def command(argv, data=None, env=None):
    result = subprocess.run(argv, input=data, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env, check=True,
                            timeout=90)
    return result.stdout


def zstd_frame(data, zstd):
    return command([zstd, "-3", "-q", "-c"], data)


def unzstd_frame(data, zstd):
    return command([zstd, "-d", "-q", "-c"], data)


def encode_chunk_archive(revisions, zstd, block_size=BLOCK_SIZE):
    if not revisions or not 1 <= block_size <= 65536:
        raise ValueError("invalid history or block size")
    if sum(map(len, revisions)) > MAX_HISTORY_BYTES:
        raise ValueError("synthetic history exceeds maximum")
    unique = []
    by_hash = {}
    refs = []
    for revision in revisions:
        ids = []
        for i in range(0, len(revision), block_size):
            block = revision[i:i + block_size]
            key = digest(block)
            identifier = by_hash.get(key)
            if identifier is not None and unique[identifier] != block:
                raise ValueError("chunk identity collision")
            if identifier is None:
                identifier = len(unique)
                by_hash[key] = identifier
                unique.append(block)
            ids.append(identifier)
        refs.append(ids)
    dictionary = b"".join(unique)
    frame = zstd_frame(dictionary, zstd)
    out = bytearray(HEADER.pack(MAGIC, block_size, len(unique),
                                len(revisions), len(dictionary), len(frame)))
    for block in unique:
        out += ENTRY.pack(digest(block), len(block))
    for revision, ids in zip(revisions, refs):
        out += REVISION.pack(digest(revision), len(revision), len(ids))
        for identifier in ids:
            out += REF.pack(identifier)
    out += frame
    return bytes(out), {
        "unique_blocks": len(unique),
        "total_block_references": sum(map(len, refs)),
        "dictionary_raw_bytes": len(dictionary),
        "compressed_dictionary_bytes": len(frame),
        "metadata_bytes": len(out) - len(frame),
        "archive_bytes": len(out),
    }


def decode_chunk_archive(package, zstd):
    """Trusted synthetic inputs only; no streaming or bomb-safe decode yet."""
    if len(package) < HEADER.size or len(package) > MAX_HISTORY_BYTES:
        raise ValueError("invalid chunk archive size")
    magic, block_size, count, revisions_count, raw_size, frame_size = HEADER.unpack_from(package)
    if (magic != MAGIC or not 1 <= block_size <= 65536 or
            count > MAX_HISTORY_BYTES // ENTRY.size or
            revisions_count == 0 or revisions_count > 100 or
            raw_size > MAX_HISTORY_BYTES or frame_size > MAX_HISTORY_BYTES):
        raise ValueError("invalid chunk archive header")
    position = HEADER.size
    chunks = []
    for _ in range(count):
        if position + ENTRY.size > len(package):
            raise ValueError("truncated chunk metadata")
        sha, size = ENTRY.unpack_from(package, position)
        if size == 0 or size > block_size:
            raise ValueError("invalid chunk length")
        chunks.append((sha, size))
        position += ENTRY.size
    snapshots = []
    for _ in range(revisions_count):
        if position + REVISION.size > len(package):
            raise ValueError("truncated revision metadata")
        sha, size, nrefs = REVISION.unpack_from(package, position)
        position += REVISION.size
        if size > MAX_HISTORY_BYTES or nrefs > (size + block_size - 1) // block_size:
            raise ValueError("invalid revision manifest")
        if position + nrefs * REF.size > len(package):
            raise ValueError("truncated chunk references")
        indexes = []
        for _ in range(nrefs):
            index, = REF.unpack_from(package, position)
            position += REF.size
            if index >= count:
                raise ValueError("invalid chunk reference")
            indexes.append(index)
        snapshots.append((sha, size, indexes))
    if position + frame_size != len(package):
        raise ValueError("trailing or missing frame")
    data = unzstd_frame(package[position:], zstd)
    if len(data) != raw_size or sum(size for _, size in chunks) != raw_size:
        raise ValueError("dictionary length mismatch")
    unique = []
    offset = 0
    for sha, size in chunks:
        block = data[offset:offset + size]
        offset += size
        if digest(block) != sha:
            raise ValueError("chunk digest mismatch")
        unique.append(block)
    restored = []
    for sha, size, indexes in snapshots:
        revision = b"".join(unique[index] for index in indexes)
        if len(revision) != size or digest(revision) != sha:
            raise ValueError("revision digest mismatch")
        restored.append(revision)
    return restored


def as_files(family, snapshot):
    if family == "evolving-events":
        return {"events.jsonl": snapshot}
    if family != "evolving-code":
        raise ValueError("unsupported synthetic history")
    markers = list(re.finditer(rb"^=== (src/[a-z0-9_./-]+) ===\n", snapshot, re.MULTILINE))
    if not markers or markers[0].start() != 0:
        raise ValueError("malformed code fixture")
    files = {}
    for i, marker in enumerate(markers):
        path = marker.group(1).decode("ascii")
        stop = markers[i + 1].start() if i + 1 < len(markers) else len(snapshot)
        if path in files:
            raise ValueError("duplicate fixture path")
        files[path] = snapshot[marker.end():stop]
    return files


def from_files(family, files):
    if family == "evolving-events":
        return files["events.jsonl"]
    return b"".join(b"=== " + name.encode() + b" ===\n" + content
                    for name, content in sorted(files.items()))


def git_history(revisions, family, git):
    with tempfile.TemporaryDirectory(prefix="invariant-git-baseline-") as temp:
        root = Path(temp)
        repo = root / "repo"
        template = root / "template"
        repo.mkdir()
        template.mkdir()
        cmd = lambda *args, data=None, env=None: command([git, "-C", str(repo), *args], data, env)
        command([git, "init", "-q", "--template", str(template), "-b", "main", str(repo)])
        env = os.environ.copy()
        env.update({
            "GIT_AUTHOR_NAME": "Synthetic Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "Synthetic Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
            "GIT_CONFIG_NOSYSTEM": "1",
        })
        revisions_commits = []
        for i, snapshot in enumerate(revisions):
            files = as_files(family, snapshot)
            if from_files(family, files) != snapshot:
                raise ValueError("fixture representation is not reversible")
            for path, content in files.items():
                target = repo / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            cmd("add", "--all", env=env)
            stamp = f"2026-01-{i + 1:02}T00:00:00+00:00"
            env["GIT_AUTHOR_DATE"] = stamp
            env["GIT_COMMITTER_DATE"] = stamp
            cmd("-c", "commit.gpgsign=false", "commit", "-q", "-m", f"Fictional revision {i}", env=env)
            revisions_commits.append(cmd("rev-parse", "HEAD", env=env).decode().strip())
        start = time.perf_counter_ns()
        cmd("repack", "-a", "-d", "-f", "--window=10", "--depth=50", env=env)
        pack_wall_ms_diagnostic = round((time.perf_counter_ns() - start) / 1_000_000, 3)
        cmd("fsck", "--full", "--no-reflogs", env=env)
        for commit_sha, expected in zip(revisions_commits, revisions):
            listing = cmd("ls-tree", "-r", "--name-only", commit_sha, env=env)
            paths = listing.decode().splitlines()
            files = {path: cmd("show", f"{commit_sha}:{path}", env=env) for path in paths}
            if from_files(family, files) != expected:
                raise ValueError("Git snapshot mismatch")
        objects = list((repo / ".git").rglob("*"))
        files = [path for path in objects if path.is_file()]
        pack_bytes = sum(p.stat().st_size for p in files if p.suffix == ".pack")
        index_bytes = sum(p.stat().st_size for p in files if p.suffix == ".idx")
        total = sum(p.stat().st_size for p in files)
        delta_entries = 0
        packfiles = [p for p in files if p.suffix == ".pack"]
        if not packfiles:
            raise RuntimeError("Git repack produced no packfile")
        for packfile in packfiles:
            for line in cmd("verify-pack", "-v", str(packfile), env=env).decode().splitlines():
                pieces = line.split()
                if len(pieces) >= 7 and pieces[1] in {"blob", "tree", "commit", "tag"}:
                    delta_entries += 1
        return {
            "git_directory_bytes": total,
            "pack_bytes": pack_bytes,
            "index_bytes": index_bytes,
            "delta_entries": delta_entries,
            "other_git_bytes": total - pack_bytes - index_bytes,
            "git_pack_wall_ms_diagnostic": pack_wall_ms_diagnostic,
            "commits": len(revisions_commits),
            "round_trip_verified": True,
        }


def benchmark(zstd, git):
    results = []
    for family, revisions in evolving_corpora().items():
        if sum(map(len, revisions)) > MAX_HISTORY_BYTES:
            raise ValueError("fixture exceeds research cap")
        frames = [zstd_frame(data, zstd) for data in revisions]
        if any(unzstd_frame(frame, zstd) != data for frame, data in zip(frames, revisions)):
            raise ValueError("Zstandard baseline round trip failed")
        package, metrics = encode_chunk_archive(revisions, zstd)
        if decode_chunk_archive(package, zstd) != revisions:
            raise ValueError("chunk baseline round trip failed")
        results.append({
            "history": family,
            "original_total_bytes": sum(map(len, revisions)),
            "revisions": len(revisions),
            "revision_sha256": [digest(data).hex() for data in revisions],
            "standalone_zstd_3": {"stored_bytes": sum(map(len, frames)), "round_trip_verified": True},
            "self_contained_fixed_chunk_archive": {**metrics, "round_trip_verified": True},
            "git_repository": git_history(revisions, family, git),
        })
    return {
        "experiment": "001", "schema_version": 1,
        "benchmark_type": "synthetic-history-storage-not-network-transfer",
        "performance_claims_permitted": False,
        "environment": {
            "platform": platform.platform(),
            "git_version": command([git, "--version"]).decode().strip(),
            "zstd_version": command([zstd, "--version"]).decode().strip(),
        },
        "limitations": [
            "Git uses a normal synthetic per-file working tree; .git storage includes metadata and indexes.",
            "Fixed-size chunk archive embeds its entire dictionary; no external context or warm sync.",
            "All histories are fictional; compression sizes are not general-performance claims.",
            "No normalized CPU, peak-memory, energy, transport or crash-recovery measurements.",
            "Chunk decoder is not hardened for untrusted data and is never a production archive.",
        ],
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zstd", default=shutil.which("zstd"))
    parser.add_argument("--git", default=shutil.which("git"))
    args = parser.parse_args()
    if not args.zstd or not args.git:
        parser.error("both git and zstd are required")
    print(json.dumps(benchmark(args.zstd, args.git), indent=2))


if __name__ == "__main__":
    main()
