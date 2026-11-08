# Phase 6 — Need-specific probe/bitmap synchronization experiment

Status: **synthetic research-only comparator**. Not a secure or deployable
codec, communication protocol, archive, or compression invention.

## Why it exists

Phase 5 transmits the receiver's entire verified chunk-ID catalog on every
revision, then references known chunks by four-byte ordinal and batches
new chunks into one Zstandard frame. Phase 6 sends only the hashes needed
for this specific source snapshot, receives a compact presence bitmap,
and batches missing chunks. This removes repeated broad catalog transfers
at the price of an **additional protocol message** (and potentially
another latency-sensitive exchange).

## Experimental message formats

All integers are little-endian. Hashes are SHA-256, 32 bytes each.

- Probe IVP21: 5-byte magic, 32-byte scope digest, 32-byte source digest,
  original byte length u64, fixed chunk size u32, reference count u32,
  followed by one 32-byte hash for each ordered block. Duplicate hashes
  represent repeated blocks.
- Reply IVR21: 5-byte magic, 32-byte scope digest, 32-byte SHA-256 of
  the exact probe, reference count u32, and one bit per reference.
  Bits indicate which chunks the receiver currently holds and can
  hash-verify. Duplicate chunk identities must have consistent bits,
  and unused bits in the final byte must be zero.
- Data IVD21: 5-byte magic, 32-byte scope digest, 32-byte SHA-256 of the
  probe, u32 missing-unique-block count, u32 compressed frame length,
  u32 raw length for each first-occurring missing unique block, then
  exactly one Zstandard level-3 frame holding their concatenated bytes.
  No frame is sent when every block is already known.

The receiver reconstructs from locally verified cached blocks and
missing blocks, checks every missing block identity and the entire
result digest, and *only then* commits newly received chunks. A false
availability advertisement or context loss after negotiation causes
an explicit failure requiring a fresh probe. No repair is assumed.

## Measurement contract

The report counts every probe, reply, data header, chunk reference,
block length and compressed frame byte. Full-object Zstandard packets
provide the stateless comparison. Phase 4 figures use its original
4 KiB configuration. Phase 5 4 KiB results are a separate benchmark
with a different receiver-advertisement protocol; compare only common
data fixtures and matched chunk sizes.

Warm transfers reuse an in-memory receiver cache across five revisions;
cold transfers begin with empty context for every revision. The report
separately counts cached raw bytes plus a 32-byte ID per unique block.
This is a **lower bound** excluding Python object overhead, storage,
indexes and persistence. The last snapshot is retransmitted after
deliberate cache loss and again into a newly rotated scope.

The protocol sends three messages per revision, compared to two in
Phase 5. Real transport latency, TLS, authentication, retry packets,
durable cache creation, CPU/energy and memory usage are **not** measured.

## Adversarial synthetic cases and explicit limitations

The two existing evolving histories are joined by random bytes with
prefix insertions (shifting block boundaries) and independent random
revisions. Chunk sizes are 1024, 4096 and 16384 bytes. Exact round trips
are tested along with corruption, stale/lying claims, failed-cache
atomicity, malformed messages, duplicate/bitmap consistency, wrong
scope, lost context and empty input.

There is NO authentication, authorization, encryption, metadata privacy
or bound on the actual output allocated by external Zstandard decoding.
The scope digest is a namespace marker, not proof of access. Chunk
fingerprints expose information and cannot be shared across privacy
boundaries. The experiment processes trusted fictional data only.
Do not use it for client records, private backups, network traffic or
any untrusted compressed content.

No speed/novelty/Weissman claims are supported by the experiment.

## Reproduce

Python 3.11+ and Zstandard CLI are required:

    python3 -m unittest discover -s scripts -p 'test_*.py'
    python3 scripts/sync_v2.py --chunk-sizes 1024,4096,16384

Results explicitly declare performance_claims_permitted=false.
