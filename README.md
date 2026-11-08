# INVARIANT

Experimental research into lossless information representation, contextual
compression, synchronization efficiency, and trustworthy reconstruction.

**Status: first development increment / NOT production ready.** This project
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
