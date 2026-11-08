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

## Build and verify (Rust stable, Python 3.11+)

    cargo test --all-targets
    cargo build --bin invariant
    python3 -m unittest discover -s scripts -p 'test_*.py'
    zstd --version
    python3 scripts/benchmark.py --binary target/debug/invariant --repetitions 3
    git --version
    python3 scripts/history_baselines.py

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
