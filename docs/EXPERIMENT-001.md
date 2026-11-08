# Experiment 001: The Cost of Knowing

Status: **research foundation**, not a discovered algorithm or production codec.
Owner: independent INVARIANT project. No sensitive or real user data in benchmarks.

## Question

Can a bounded shared-context representation reduce total end-to-end costs of
encoding, storing, and synchronizing *evolving* structured information versus
strong existing baselines, without undermining exact reconstruction?

## Locked safeguards

- Lossless results must exactly match original bytes.
- Count dictionaries, context creation and storage, indexes, manifests,
  protocol overhead, CPU time, decompression time, memory, and restore cost.
- Never presume private information may be shared for deduplication.
- Dependencies must eventually be bounded, explicit, immutable and exportable.
- Measurements require frozen datasets, codec versions, equipment/settings,
  repeat runs, verified recovery, and honest negative results.
- No real clinical, business, client, personal, or private project data.

## Scope of first development increment

A **provisional** IVN0 format, not an original compression method:
- Four-byte magic IVN0, one-byte version 0, one-byte codec (0=literal, 1=zstd).
- Little-endian 64-bit original size and encoded payload size.
- SHA-256 digest of original bytes (32 bytes).
- Payload (literal or zstd level 3, whichever is smaller before common header).
- Fixed in-memory input bound of 64 MiB. The encoder is not a streaming API.
- Successful decode requires exact lengths and a matching digest.

This is a testing instrument, not a production archival contract. The decoder
does not authenticate provenance, perform encryption, or provide a stable format
migration guarantee. Archive and synchronization features remain unimplemented.

## Benchmark v2: independent reference codecs and evolving datasets

The Python driver includes standalone `zstd -3` as a modern reference and
gzip level 6, bzip2 level 9, LZMA preset 6 and raw bytes as additional size
baselines. The IVN0 container uses Zstandard level 3 or literal data and adds
its 54-byte test header. For every test it verifies full original-byte recovery
and deterministic encoded bytes. The benchmark refuses to run if the standalone
Zstandard CLI is missing. The printed environment includes binary SHA-256,
Python and Zstandard version, host platform and repeat count.

Besides the four original synthetic corpora it generates two five-revision
histories (synthetic code and synthetic event records). Regression tests pin
all ten history snapshot digests. The report totals each history's
**independently compressed full snapshots**, including frame/header overhead.
These totals are not a warm-sync measurement, delta comparison or a backup
deduplication measurement. Context overhead is zero because **none is used**.

Diagnostic median wall times include different Python runtimes, subprocess
startup and file I/O. They must **not** be used to rank codec performance.
CPU, peak memory, energy, cold/warm network transfer and recovery from damaged
context remain unmeasured. Source-tree dependency versions are not locked
yet, so repeatable dataset bytes do not imply fully pinned benchmark tools.
The research suite is still non-competitive; speed or novelty claims are
prohibited.

## Benchmark v3: real Git histories and self-contained chunk archive

The separate `scripts/history_baselines.py` experiment uses the same two
five-revision, deterministically generated synthetic histories. It measures:

1. **Standalone Zstd**: each entire historical snapshot independently encoded
   as a Zstandard level-3 frame, with full round-trip checks.
2. **Self-contained fixed-block deduplication**: split snapshots into fixed
   4 KiB blocks, identify identical blocks by SHA-256, store a Zstandard
   frame containing every unique block, and include all block hashes, lengths,
   revision digests, block references and framing bytes. The decoder proves
   that every revision reconstructs byte-for-byte.
3. **Actual Git packed history**: initialize a synthetic repository, commit
   each revision using ordinary paths/files, repack Git objects, verify the
   repository with `git fsck`, and reconstruct every historical revision
   via `git show`. Report pack bytes, index bytes, other `.git` metadata,
   and count packed delta entries using `git verify-pack`.

This is a **fixed-block deduplication baseline**, *not* CARE, middle-out
compression, a new general codec or a deployable file format. The fixture
archive is fully self-contained but not random-access optimized; its decoder
is explicitly unsafe to expose to untrusted archive inputs.

Archive bytes, dictionary bytes and metadata bytes are included. Git reports
total `.git` repository bytes, which includes history, indexes, refs and local
metadata. These totals reflect **different semantics**: normal Git repositories
preserve per-file object identity and history; the synthetic fixed-block
archive uses a single solid compressed dictionary for the complete history.
They must not be presented as directly interchangeable storage systems.

There is still **no warm-sync transfer**, external context cost, normalized
throughput, peak memory, energy, resilience to lost dependencies, or
production backup verification. All datasets are synthetic, and all measured
size advantages are workload-specific, not novel research claims.

Run `python3 -m unittest discover -s scripts -p 'test_*.py'` and
`python3 scripts/history_baselines.py`. Git and Zstandard CLI are required.

## Next experiments

1. Freeze the Rust dependency lockfile/toolchain and record all test tools.
2. Measure cold and warm incremental transfers using explicit delta/manifest
   wire formats, including context distribution and dependency recovery cost.
3. Run comparable CPU, memory, throughput, and energy benchmarks under
   normalized execution conditions; add more challenging public fixtures.
4. Independently validate safety and restore behavior; harden a future
   production decoder separately from this synthetic-only prototype.
5. Implement constrained CARE research candidates against these baselines;
   then test anchor-first bidirectional coding and publish negative results.
6. Discard any proposed algorithm that fails matched resource-cost tests.


## Exit gate

No originality or speed/ratio claim until reproducible comparisons with
competent contemporary alternatives show a statistically credible advantage.
