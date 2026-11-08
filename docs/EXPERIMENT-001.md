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

## Current benchmark boundaries

The synthetic Python driver verifies round trips and reports on-disk sizes.
Its gzip, bz2 and lzma comparisons are **sanity checks**, not the best practical
baselines. They do not measure speed or energy. Rust CI must pass before its
binary can be considered verified.

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
