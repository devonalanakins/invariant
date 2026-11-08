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

## Next experiments

1. Add independent zstd frame, strong codec competitors, delta encoding,
   Git/backup and sync baselines with comparable overhead.
2. Build frozen evolving data fixtures and account for initial context cost.
3. Measure cold/warm transfer, cumulative storage, CPU, memory, latency,
   decoding costs, and corruption recovery.
4. Implement a constrained CARE prototype, then compare it fairly.
5. Test anchor-first bidirectional coding against forward-only alternatives.
6. Discard or revise any algorithm that fails matched resource-cost tests.

## Exit gate

No originality or speed/ratio claim until reproducible comparisons with
competent contemporary alternatives show a statistically credible advantage.
