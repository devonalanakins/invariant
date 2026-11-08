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

## Phase 4: cold and warm transfer baseline (simulation only)

`scripts/sync_baselines.py` models a receiver with a scope-specific in-memory
chunk cache. An explicit receiver advertisement contains a scope digest,
chunk count and sorted SHA-256 chunk IDs. A sender reads that advertisement,
sends ordered chunk references and Zstandard-framed missing chunks, and
verifies the reconstructed snapshot SHA-256 after decoding.

The same five revisions are sent three ways: stateless full-Zstandard packets
with versioned integrity headers; independent cold chunk transfers (no cached
context); and chained warm chunk transfers (the receiver retains earlier
chunks). The measured wire cost includes every advertisement and sender packet,
including framing, references, chunk digests and Zstandard data. No simulated
wire bytes are excluded merely because they appear to be "metadata".

Receiver context memory is recorded separately as a **lower bound**:
raw cached chunk bytes plus 32 bytes per ID; Python object, allocator, disk,
index and persistence costs are not counted. Context-loss recovery retransmits
the last complete snapshot after the receiver cache is cleared. Scope rotation
uses a fresh receiver; stale or counterfeit advertisements fail closed and
cannot silently reconstruct data not actually cached.

**Negative result:** Simple 4 KiB block synchronization can transfer *more*
than a full Zstandard snapshot because it pays for individual compressed
blocks, full hash manifests and receiver catalogs. This is an explicit
baseline to improve, not a result to hide.

**Major security limitation:** The scope digest is a syntactic namespace,
*not authentication or authorization*. Hash advertisements leak information
about receiver data. Decoder output from external Zstandard is not strictly
bounded against hostile frames. The program simulates transfers in memory;
it does not implement TLS, network errors, permissions, multi-party
negotiation or production persistence. It must never receive untrusted input
or be incorporated into real archives, backups, apps or services.

Further protocol definitions, counted fields, and the comparison's meaning
are in `docs/SYNC-BASELINE.md`. CI exercises exact round trips and adversarial
synthetic cases, including failure atomicity.

## Phase 5: catalog indexes and batched Zstandard (simulation only)

`scripts/batched_sync.py` adds a comparison candidate that reuses the
receiver's already-advertised sorted block catalog, stores each snapshot
reference as a 4-byte catalog/new-block ordinal rather than a 32-byte hash,
and packs all newly supplied blocks into **one** Zstandard frame. It is
a separate research-only format, not a change to IVN0 or the earlier
Phase 4 wire format. The catalog's scope and exact byte contents are
bound by a SHA-256 digest, but hashes alone are **not authentication**.

Each transfer counts the full receiver advertisement, every reference,
new-block digest/length metadata and the single frame. Warm-catalog context
cost is reported as a separate lower-bound retained-byte count. Failed
decode leaves the cache unchanged; stale or corrupted catalogs, wrong
scopes, bad references, duplicate definitions and damaged frames fail.
The decoder is NOT hardened for malicious Zstandard frames, and there is
no network security or protocol replay defense.

Four synthetic five-snapshot histories are measured. Evolving code and
events are unchanged from earlier experiments. A **favorable** 256 KiB
high-entropy binary history changes one fixed 4 KiB block per revision;
an **unfavorable** 128 KiB high-entropy history receives one-byte
prefix insertions that shift every block boundary. Both counterexamples
are explicitly labeled and generated deterministically. Exact recovery
is asserted for every revision.

Locally observed illustrative wire totals (bytes, five revisions):

| Synthetic history | Stateless full Zstd | Phase 4 warm | Batched warm |
| --- | ---: | ---: | ---: |
| Evolving code | 4,218 | 11,697 | 6,734 |
| Evolving events | 11,126 | 11,307 | 8,203 |
| Stable binary with edits | 1,311,205 | 301,406 | 291,538 |
| Shifted binary boundaries | 655,852 | 680,392 | 673,269 |

**Interpretation:** Batched references reduce overhead relative to
per-chunk frames; the new baseline still **loses to full Zstd** on
small code and shifted high-entropy histories. The favorable case is
an expected benefit of ordinary deduplication, not evidence for CARE,
middle-out encoding, or a new information-theoretic discovery.

See `docs/BATCHED-SYNC.md` for the exact format and limitations. Do not
use for private content, backups, production applications or network traffic.

## Next experiments

1. Commit a reviewed Cargo.lock, pin external benchmark tool versions and run
   reproducible experiments on matching hardware.
2. Establish fair single-process CPU/peak-memory and reproducible latency
   baselines; add real public non-sensitive datasets beyond synthetic cases.
3. Evaluate content-defined chunking, batching variants and compact catalog
   negotiation while including receiver context and recovery costs.
4. Formalize authenticated context exchange and bounded decoding *before*
   considering network use or untrusted content.
5. Implement a narrowly scoped CARE candidate only after baselines and cost
   accounting are independently reviewed; keep results reproducible and
   publish negative findings.

## Exit gate

No originality or speed/ratio claim until reproducible comparisons with
competent contemporary alternatives show a statistically credible advantage.
