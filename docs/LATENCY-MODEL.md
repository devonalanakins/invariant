# Experiment 001 — Analytical latency sensitivity, Phase 7

**Status:** falsifiable synthetic modeling, not a measured network benchmark.
This report must not be used for production service design or any general
performance or originality claim.

## Question

How much of the apparent advantage in *encoded bytes* remains once every
sequential protocol message has propagation delay, even if CPU and server
processing were free?

Phases 4, 5 and 6 all encode and restore **exactly the same fictional
histories**. They differ in the amount and order of metadata they exchange:

| Protocol | One-way messages per snapshot | Context required |
| --- | ---: | --- |
| Standalone full Zstandard | 1 | None for the transfer |
| Phase 4 per-chunk | 2 | Verified receiver chunk cache |
| Phase 5 catalog-index | 2 | Verified receiver chunk cache |
| Phase 6 need-specific probe/bitmap | 3 | Verified receiver chunk cache |

The model counts message *exchanges*, not individual real IP/TCP packets.

## Explicit equation

For each protocol, with a sum of transmitted message sizes B in bytes,
link bandwidth W in **megabits per second**, five sequential revisions N,
M one-way messages per revision, and round-trip propagation R milliseconds:

    modeled_ms = (8 * B / (1000 * W)) + (N * M * R / 2)

This assumes a symmetric link where each message takes R/2 propagation.
Every message is sequential. No exchanges overlap or pipeline. Byte
serialization and propagation alone determine completion; no actual
network is connected.

Four sensitivity scenarios: zero RTT at 10 Mbps; 5 ms RTT at 100 Mbps;
50 ms RTT at 10 Mbps; and 150 ms RTT at 1 Mbps. These are input
assumptions, NOT user-location measurements or Internet observations.

It is valid to compare the *hypothetical modeled costs* under the
same assumptions. It is invalid to call them measurements of transfer
speed, throughput or real-world latency.

## Dataset and storage accounting

Six five-snapshot histories, all fictional and reproducibly generated:

- evolving-code and evolving-events;
- mutating-binary (deliberately favorable stable random bytes with edits);
- shifted-binary (deliberately unfavorable fixed-boundary insertions);
- stress-shifted-binary and stress-independent-noise (additional adverse inputs).

Each protocol's source output is verified byte-for-byte internally before
any modeled cost is recorded. The results include the bytes actually
constructed by each baseline, its message counts, and the last-snapshot
cache-loss resend cost. For protocols with reusable chunks, context
storage is *only a lower bound*: sum of raw chunk bytes and 32-byte
digests, NOT durable/cache-index/OS/Python allocation or replication.

The full snapshot method does not require a receiver chunk catalog;
its context-overhead field is zero **for protocol context only**, not
because receiving data has no storage cost.

## Why negative cases matter

At 50 ms RTT and 10 Mbps, for the evolving-events five-revision
dataset (local synthetic computation):

| Protocol | Wire bytes | Modeled completion (ms) |
| --- | ---: | ---: |
| Full Zstandard | 11,126 | 133.9008 |
| Phase 5 catalog-index | 8,203 | 256.5624 |
| Phase 6 probe/bitmap | 7,834 | 381.2672 |

Phase 6 saves 369 wire bytes relative to Phase 5 but pays five extra
one-way propagation delays, or 125 ms in this scenario. This reverses
the byte-only ranking. Phase 6's exact latency is not observed and
would differ under pipelining, acknowledgements, queueing and real RTT.

Other histories include both negative and favorable byte outcomes. A
future method should be measured on a real link with controlled latency
and bandwidth before drawing practical conclusions.

## Exclusions / threat boundaries

No actual network, RTT measurement, asynchronous sender/receiver,
CPU, compression time, memory allocation, TLS, encryption, access
control, retransmission, packet loss, reliability, failure recovery
timing, bandwidth contention, throughput confidence intervals, or
real-user data is included. Synthetic scope hashes do not authorize
access. Legacy experimental decoders are not safe against malicious
Zstandard frames. Never feed private/clinical or untrusted data.

**This is not CARE, middle-out, a novel codec, or production software.**

## Reproduce

Requires Python 3.11+, Zstandard CLI and existing self-contained
synthetic benchmark scripts:

    python3 -m unittest discover -s scripts -p 'test_*.py'
    python3 scripts/latency_model.py

The JSON report explicitly marks measured_network_latency=false and
performance_claims_permitted=false, and includes all scenario assumptions.

Rust reproducibility note: rust-toolchain.toml selects 1.99.1 and the
committed Cargo.lock pins the prototype's 21 Rust dependency packages.
The exact external Python, Zstandard, Git and operating-system versions
remain runner-dependent and must be captured for all published experiments.
