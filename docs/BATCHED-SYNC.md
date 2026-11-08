# Phase 5: batched catalog-index sync (EXPERIMENTAL)

This is a **synthetic-only** measurement protocol, NOT a hardened decoder,
authenticated network service, novel compressor, approved archive format,
or production integration. The experiment does not alter the Rust IVN0
container. It tests whether batching known data patterns reduces overhead.

## Version-1 experimental layout

All integers are little-endian. The receiver's advertisement uses the
Phase 4 `IVAD1` structure, with a 32-byte scope digest and sorted unique
SHA-256 chunk IDs (32 bytes each). These bytes are counted as transmitted.

The Phase 5 `IVBT1` sender message carries:

| Field | Bytes |
| --- | ---: |
| Magic | 5 |
| Scope identifier | 32 |
| SHA-256 of the *exact* receiver advertisement | 32 |
| SHA-256 of reconstructed snapshot | 32 |
| Original snapshot length | 8 |
| Fixed block size | 4 |
| Number of block references | 4 |
| Number of new unique blocks | 4 |
| Compressed frame length | 4 |
| Each ordered reference | 4 |
| Each new unique block: SHA-256 and raw length | 36 |
| Single concatenated-new-block Zstd frame | Variable |

A reference ordinal less than the size of the sorted advertised catalog
points to an existing chunk. Ordinals starting at that catalog length
refer to new chunks in first-occurrence order. Every new chunk must be
used, declared exactly once, and match its digest; all reconstructed
snapshots must match their length and SHA-256. The receiver commits new
cache blocks only after full verification.

When there are zero new chunks, the sender omits the Zstd frame. The
decoder refuses unrecognized magic, stale/wrong advertisement, wrong
scope, malformed lengths, impossible indexes, orphan definitions,
tampered blocks, and trailing data. This supports exact reconstruction
for **trusted synthetic input only**. The external Zstd CLI decompresses
unbounded output and no signature/MAC or trusted identity exists.

## Measurements and fairness

For every five-revision fictional history:

* **Full** uses a standalone whole-snapshot Zstd packet per revision,
  including its Phase 4 header but no receiver advertisement.
* **Cold batched** sends every revision to a new empty receiver, counting
  its advertisement plus the full batched sender packet.
* **Warm batched** carries verified receiver chunks between revisions,
  counting all five advertisements plus every sender packet.
* **Phase 4 warm** retains its individual compressed chunk frames and
  32-byte reference entries as the direct prior baseline.
* Receiver storage is reported separately: retained raw chunk lengths
  plus 32 digest bytes per key. This explicitly excludes Python and
  operating-system memory overhead, disk/index persistence, and
  sender-side context storage.
* Cache-loss recovery resends the final snapshot from empty context.

The two existing histories are augmented by deliberately favorable
stable high-entropy data with localized edits and deliberately unfavorable
high-entropy data with one-byte insertions that shift block boundaries.

There is **no** hardware-normalized CPU or energy measurement, actual
network transport, TLS, peer authentication, revocation enforcement,
adversarial decoder hardening, durable state recovery, or publication-
grade performance claim. Fingerprint advertisements disclose information
about receiver contents; scope hashes are *not* authorization and cannot
separate tenants securely. This must never operate on private/client data.

## Reproduce

Requires Python 3.11+ and Zstandard CLI (same external version for
comparisons). The repository pins Rust 1.99.1, but does **not** yet commit
a complete Cargo dependency lockfile.

```sh
python3 -m unittest discover -s scripts -p 'test_*.py'
python3 scripts/batched_sync.py
```

The next research candidate should compare content-defined chunking
against these fixed boundaries, then test realistic data without
cherry-picking favorable workloads. No claims of compression novelty
or portable deployment readiness are permitted.
