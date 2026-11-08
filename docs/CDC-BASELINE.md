# Experiment 001 - Phase 8: Content-defined chunking baseline

**Research-only synthetic experiment.** It does not implement CARE, a
novel compressor, standard FastCDC, a deployable archive, or a secure
network service. Only deterministic fictional data may be processed.

## Why compare content-defined boundaries?

Phase 5 fixed 4 KiB blocks can lose almost all reuse when a single byte
is inserted near the beginning of high-entropy data: every downstream
block boundary shifts. A simple gear-hash content-defined method cuts
at boundaries derived from actual bytes, so the same unchanged region
can recover stable blocks after a short disturbed prefix.

The experiment deliberately includes workloads that disfavor CDC.
There is no claim of universal advantage or benchmark optimization.

## Cutpoint algorithm

1. A fixed 256-entry 64-bit gear table derives deterministically from
   Python Random seeds 20261108 + 131 * byte_index.
2. Iterate each input byte, updating a 64-bit accumulator as
   accumulator = ((accumulator << 1) + gear[byte]) modulo 2**64.
3. Once at least 2048 bytes have accumulated, cut if the low 12 bits
   are zero; force a cut at 8192 bytes.
4. Reset accumulator on a cut. The last chunk may be shorter than
   the 2048-byte minimum. Empty input has zero chunks.
5. Inputs are limited to 64 MiB and at most 16384 chunk references
   or combined receiver/new dictionary entries.

This is a **simplified deterministic research chunker**, not a full
published FastCDC implementation. It has no cryptographic or adversarial
collision-resistance guarantee beyond SHA-256 block identity checks.
The gear parameters are fixed for this experiment, not optimized on
reported datasets. Future work must compare strong mature alternatives.

## Research-only IVCD1 message

All integers are little-endian. The sender first receives the exact
Phase 4 IVAD1 sorted SHA-256 receiver catalog (scope digest, count, IDs).
The entire advertisement is counted as transmitted bytes. IVCD1 packet:

| Field | Bytes |
| --- | ---: |
| Magic IVCD1 | 5 |
| Synthetic scope digest | 32 |
| SHA-256 of exact receiver advertisement | 32 |
| SHA-256 of restored whole object | 32 |
| Original object length (u64) | 8 |
| Minimum/target/maximum chunk lengths (3 x u32) | 12 |
| Chunk reference count/new unique chunk count/frame size (3 x u32) | 12 |
| Each ordered chunk reference (u32 index) | 4 |
| Each new unique chunk SHA-256 + raw length | 36 |
| One Zstandard level-3 frame of new unique chunk contents | Variable |

Receiver ordinals index the sorted advertised catalog; new ordinals
reference the new chunks in their first-occurrence order. The receiver
checks catalog staleness, counts, lengths, duplicate definitions,
out-of-range/orphan references, digests, reconstructed length/whole
SHA-256, and *recomputes canonical CDC cutpoints*. It updates cached
chunks only after the entire snapshot is verified. A missing or damaged
cache requires fresh negotiation and resending data, not silent success.

A scope digest is NOT authentication or authorization, and chunk
fingerprints disclose metadata. The external zstd decoder is NOT
decompressed-output-bounded for adversarial frames. This code must
never run against private, clinical, production, untrusted or external
network data.

## Matched comparison and explicit costs

Compare five exact, fictional revision histories with Phase 5's
catalog-index batched format. Both retain the full receiver catalog
advertisement, 4-byte reference ordinals and one frame for missing
unique chunks, allowing a boundary-method comparison. IVCD1 adds
three boundary parameters (Phase 5 has one fixed size), and all extra
bytes are included rather than waived. All snapshots reconstruct
byte-for-byte, in separate cold and chained warm scenarios.

Datasets: evolving-code, evolving-events, localized-edit stable binary,
prefix-insert shifted binary, and independent random noise. Test both
favorable and unfavorable cases; other datasets may behave differently.

The report separately exposes: total full-object Zstandard bytes,
fixed and CDC warm/cold transfer bytes, CDC advertisement/metadata/
frame bytes, used reference counts, lower-bound raw receiver cache
bytes plus 32 digest bytes per ID, and last-snapshot recovery bytes
after losing context. Storage on disk, cache index/allocator overhead,
authentication, encryption, real network latency, CPU/energy, loss
retransmissions and research originality are NOT measured.

## Local synthetic observation

| Workload | Full Zstd | Fixed Phase 5 | CDC |
| --- | ---: | ---: | ---: |
| Evolving code | 4,218 | 6,734 | 4,924 |
| Evolving events | 11,126 | 8,203 | 7,687 |
| Stable binary edits | 1,311,205 | 291,538 | 322,483 |
| Shifted binary prefix inserts | 655,852 | 673,269 | 180,677 |
| Independent noise | 60,470 | 62,455 | 62,495 |

Not a general speed or ratio claim. Fixed chunks still win on aligned
edits; CDC wins on content shifts. Both lose to independent full
Zstandard on some workloads. The experiment's Python implementation
is not optimized and no normalized processing-time ranking exists.

## Reproduce

Requires Python 3.11+ and standalone Zstandard CLI:

    python3 -m unittest discover -s scripts -p 'test_*.py'
    python3 scripts/cdc_sync.py

The machine-readable report sets performance_claims_permitted=false
and measured_network_latency=false.
