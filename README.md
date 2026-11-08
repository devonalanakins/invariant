# INVARIANT

Experimental research into lossless information representation, contextual
compression, synchronization efficiency, and trustworthy reconstruction.

**Status: experimental research / NOT production ready.** This project
does not claim to have invented a new compression algorithm. The current
prototype is a bounded version-0 container choosing literal or existing
Zstandard compression, with SHA-256 checking and deterministic synthetic tests.

## Research direction

The foundational question: can authorized shared context make evolving data
more efficient to store, transmit, and process, *after counting the cost of
that context*? CARE (Context-Anchored Residual Encoding), bidirectional
anchor-first reconstruction, compressed-domain operations, and semantic
communication are research hypotheses, not implemented capabilities.

See docs/EXPERIMENT-001.md for the experiment, falsifiers, current scope,
and next milestones. Benchmark v2 compares direct Zstandard level 3, gzip,
bzip2, LZMA, and uncompressed data against IVN0 on deterministic synthetic
single objects and evolving full-snapshot histories. All codec sizes include
frame/container overhead. No contextual algorithm or fair speed comparison
has been established.

## Build and verify (Rust 1.99.1 pinned, Python 3.11+)

    cargo test --all-targets
    cargo build --bin invariant
    python3 -m unittest discover -s scripts -p 'test_*.py'
    zstd --version
    python3 scripts/benchmark.py --binary target/debug/invariant --repetitions 3
    git --version
    python3 scripts/history_baselines.py
    python3 scripts/sync_baselines.py
    python3 scripts/batched_sync.py
    python3 scripts/sync_v2.py --chunk-sizes 1024,4096,16384

## Version-history baselines (synthetic only)

`scripts/history_baselines.py` runs three separately verified storage baselines
on two fictional five-revision histories:

- Separate Zstandard level-3 frames for every full snapshot.
- A **self-contained fixed-4-KiB-block deduplication baseline** with SHA-256
  references, a whole-dictionary Zstandard frame, and counted manifest overhead.
- A real Git repository containing each history as normal files and commits;
  Git packs and verifies its objects, and all revisions are read back.

The report includes whole-repository Git metadata, archive manifests and
all dictionary bytes. Git's repository size is **not** the same measurement as
a network sync payload. These approaches are materially different and cannot
support speed, novelty or universal compression claims. The research-only
chunk decoder is not hardened for untrusted inputs.

## Cold/warm transfer model (fictional data only)

`scripts/sync_baselines.py` compares stateless full-Zstandard packets,
independent cold transfers and sequential warm transfers of the same five
revisions. Every request advertisement, reference manifest, block frame,
scope digest and recovery resend is counted in the in-memory protocol's
wire-byte totals. A separate **lower-bound** measurement counts retained
receiver context bytes, excluding Python allocation and disk overhead.

The baseline uses existing 4 KiB chunk deduplication and Zstandard, **not**
CARE or a new compression algorithm. It is deliberately not an authenticated
or hardened network protocol. Tests cover exact reconstruction, stale or
corrupt context, false advertisements, scope mismatch/rotation, packet damage
and atomic failure. See `docs/SYNC-BASELINE.md` for exact semantics, limitations
and the threat boundary. Nothing here is safe to deploy.

## Batched reference-index research baseline (synthetic only)

`scripts/batched_sync.py` extends the previous fixed-block comparison using
four-byte indexes into a receiver-advertised, sorted chunk catalog. All newly
transmitted blocks share one Zstandard frame rather than separate frames.
The packet binds its content and the advertisement by SHA-256 and verifies
the entire restored snapshot before adding any cache entries.

The report compares full Zstandard, previous per-block warm sync, cold batched
sync and warm batched sync on evolving code, evolving events, stable binary
with small edits (favorable), and binary with shifted block boundaries
(unfavorable). All modeled advertisement, metadata and payload bytes count.
Retained receiver bytes are shown separately as a **lower bound**.

This is a known-primitive research baseline, NOT CARE, a production wire
protocol or an authenticated cross-device system. The test decoder is
not safe for hostile compressed input. See `docs/BATCHED-SYNC.md`.

The repository selects Rust 1.99.1 with `rust-toolchain.toml`; Rust dependency
versions are not fully locked until a reviewed `Cargo.lock` is committed.
Exact Zstandard/Python/Git versions remain runner-dependent and are reported
by the benchmarks rather than claimed pinned.

## Need-specific probe/bitmap sync (Phase 6, synthetic only)

scripts/sync_v2.py is a separate comparison against the existing Phase 5
batched catalog-index protocol. The sender transmits only the chunk hashes
required for its next snapshot, the receiver returns a bitmap of its verified
chunks, and the sender batches missing unique chunks into one Zstandard
frame. This reduces repeated full-cache advertisements but introduces
a **third protocol message**; the extra latency is not measured.

The benchmark tests the two evolving histories plus unfavorable shifted
random bytes and independent noise, with 1, 4 and 16 KiB chunks. All probe,
bitmap, frame, reference and metadata bytes are included; exact round trips,
cache loss, corruption, stale claims and scope rotation are tested.
Receiver context storage is separately reported as a lower bound.

On two shared 4 KiB fixtures the new protocol uses fewer warm wire bytes
than Phase 5, but it still loses to full Zstandard for evolving code.
The stress fixtures also lose to full Zstandard. This is a **known-primitive
research variant**, not CARE, a novel compressor, an authenticated service
or a safe decoder. See docs/PROBE-BITMAP-SYNC.md.

## Experimental CLI

    invariant pack original.bin new-output.ivn
    invariant verify new-output.ivn
    invariant unpack new-output.ivn restored.bin

The CLI intentionally refuses to overwrite an existing output, limits
input size to 64 MiB, and reports corrupt or unsupported containers.
Do not trust it for long-term archives or production backups. Restore
independent copies with mature systems.

## Design rules

- Exact byte-for-byte recovery, or explicit failure.
- Strict resource limits and independent readback.
- Isolated privacy and authorization domains; no implicit cross-scope context.
- Fully self-hostable, open implementation direction; no hosted AI dependency.
- No performance claims without reproducible comparisons.
- No production integration before independent acceptance.

## Licensing

A final open-source license will be selected after dependency and compatibility
review. Public source visibility alone is not a license grant.
