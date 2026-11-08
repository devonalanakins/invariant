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

    cargo clippy --locked --all-targets -- -D warnings
    cargo test --locked --all-targets
    cargo build --locked --bin invariant
    python3 -m unittest discover -s scripts -p 'test_*.py'
    zstd --version
    python3 scripts/benchmark.py --binary target/debug/invariant --repetitions 3
    git --version
    python3 scripts/history_baselines.py
    python3 scripts/sync_baselines.py
    python3 scripts/batched_sync.py
    python3 scripts/sync_v2.py --chunk-sizes 1024,4096,16384
    python3 scripts/latency_model.py
    python3 scripts/cdc_sync.py

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

The repository selects Rust 1.99.1 with `rust-toolchain.toml`; a
generated, reviewed `Cargo.lock` records all 21 resolved Rust packages.
GitHub CI enforces `cargo --locked` during lints, tests and builds.
This freezes Rust dependencies for this prototype, not the full benchmark
environment. Zstandard/Python/Git/OS versions remain runner-dependent and
are reported by the benchmarks rather than claimed pinned.

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

## Analytical latency sensitivity (Phase 7; NOT network measurements)

scripts/latency_model.py compares Phase 4 per-chunk, Phase 5 batched-index,
Phase 6 need-specific probe/bitmap, and stateless Zstandard transfers on
the exact same six deterministic five-revision synthetic histories. It
reports their encoded wire bytes, message counts, receiver-context storage
lower bounds, last-snapshot context-loss resends, and modeled completion
times under four explicit round-trip-time/bandwidth assumptions.

Times are **computed**, not observed. The simplistic sequential-message
model excludes real network conditions, protocol processing, CPU/memory,
authentication, TLS and retries. No performance, security, or compression
novelty claim is supported. See docs/LATENCY-MODEL.md.

## Phase 8: deterministic content-defined chunking (synthetic only)

scripts/cdc_sync.py implements a simple, deterministic gear-hash
content-defined chunker using 2 KiB minimum, 4 KiB target and 8 KiB
maximum blocks. It **reuses Phase 5's advertisement, ordered 4-byte
references and single Zstandard frame approach**, but carries the
chunking parameters in a distinct experimental format. Warm, cold and
lost-context exact reconstruction are checked before reporting bytes.

It compares five fictional five-revision histories with Phase 5's fixed
4 KiB batched approach, counting every receiver catalog, sender header,
reference, unique-chunk digest/length and frame byte. Receiver context
storage is reported separately as a lower bound. A byte insertion near
the start of a large random file heavily favors content-defined
boundaries, while stable aligned edits favor fixed blocks. Completely
new random data typically loses to full Zstandard; no universal win.

This research implementation is **not FastCDC, CARE, original compression
research proof, a production protocol, or a safe decoder**. Decoder
output is not bounded for hostile compressed frames; no real networking,
latency/CPU/energy equivalence or authorization has been implemented.
See docs/CDC-BASELINE.md for format, fairness and negative results.

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
