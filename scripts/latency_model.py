#!/usr/bin/env python3
"""Latency sensitivity for EXISTING synthetic sync protocols, not network tests.

Uses exact encoded-message byte counts from four independently round-tripped
synthetic comparison paths. A simple store-and-forward propagation and link-
serialization model estimates completion latency under stated assumptions.
No sockets, authentication, measured CPU, real packet loss or actual RTT.
"""

import argparse
import json
import math
import platform
import shutil

from batched_sync import compare as catalog_comparison
from batched_sync import synthetic_mutating_binary, synthetic_shifted_binary
from benchmark import evolving_corpora
from sync_baselines import experiment as legacy_comparison, send_full
from sync_v2 import experiment as probe_comparison, stress_histories

DEFAULT_SCENARIOS = (
    ("zero-rtt-10mbps", 0.0, 10.0),
    ("lan-5ms-100mbps", 5.0, 100.0),
    ("wan-50ms-10mbps", 50.0, 10.0),
    ("slow-150ms-1mbps", 150.0, 1.0),
)


# Explicitly count each one-way message for one revision. These message
# counts describe the *synthetic* protocols, NOT actual TCP packets.
MESSAGE_COUNTS = {
    "full_zstd": 1,
    "legacy_per_chunk": 2,
    "catalog_index_batched": 2,
    "need_specific_probe": 3,
}


def modeled_completion_ms(total_wire_bytes, revisions, messages_per_revision,
                          rtt_ms, bandwidth_mbps):
    """Sum idealized sequential completion: link serialization + propagation.

    Assumes every message is sent in order on a symmetric link, one-way
    propagation is RTT / 2, all revision exchanges are independent, and
    protocols do not pipeline. CPU, framing, TLS, setup, queuing, congestion,
    retries and network jitter are excluded. Not an empirical measurement.
    """
    if (not isinstance(total_wire_bytes, int) or total_wire_bytes < 0 or
            not isinstance(revisions, int) or revisions < 1 or
            not isinstance(messages_per_revision, int) or messages_per_revision < 1 or
            not math.isfinite(rtt_ms) or rtt_ms < 0 or
            not math.isfinite(bandwidth_mbps) or bandwidth_mbps <= 0):
        raise ValueError("invalid synthetic network-model parameters")
    serialization_ms = total_wire_bytes * 8 / (bandwidth_mbps * 1000)
    propagation_ms = revisions * messages_per_revision * rtt_ms / 2
    return round(serialization_ms + propagation_ms, 6)


def fixture_histories():
    """Identical inputs for all protocols; includes unfavorable workloads."""
    return {
        **evolving_corpora(),
        "mutating-binary": synthetic_mutating_binary(),
        "shifted-binary": synthetic_shifted_binary(),
        **stress_histories(),
    }


def compare_history(name, revisions, zstd, scenarios=DEFAULT_SCENARIOS):
    """Compare four protocol paths on exactly the same restored snapshots."""
    old = legacy_comparison(name, revisions, zstd)
    batched = catalog_comparison(name, revisions, zstd)
    probe = probe_comparison(name, revisions, zstd)
    full_wire = old["stateless_full_zstd_wire_bytes"]
    if (not old["roundtrip_verified"] or not batched["roundtrip_verified"] or
            not probe["roundtrip_verified"] or
            full_wire != batched["stateless_full_wire_bytes"]):
        raise AssertionError("mismatched full-object baseline or recovery")
    scope = "fictional/" + name
    protocols = {
        "full_zstd": {
            "wire_bytes": full_wire,
            "context_stored_bytes_lower_bound": 0,
            "context_loss_last_revision_wire_bytes": len(send_full(revisions[-1], scope, zstd)),
        },
        "legacy_per_chunk": {
            "wire_bytes": old["warm_chained_delta_wire_bytes"],
            "context_stored_bytes_lower_bound": old["warm_context_stored_bytes_peak_lower_bound"],
            "context_loss_last_revision_wire_bytes": old["context_loss_last_snapshot_resend_bytes"],
        },
        "catalog_index_batched": {
            "wire_bytes": batched["chained_warm_batched_wire_bytes"],
            "context_stored_bytes_lower_bound": batched["receiver_context_peak_bytes_lower_bound"],
            "context_loss_last_revision_wire_bytes": batched["context_loss_resend_bytes"],
        },
        "need_specific_probe": {
            "wire_bytes": probe["warm_wire_bytes"],
            "context_stored_bytes_lower_bound": probe["receiver_context_bytes_peak_lower_bound"],
            "context_loss_last_revision_wire_bytes": probe["context_loss_last_snapshot_recovery_bytes"],
        },
    }
    for key, protocol in protocols.items():
        protocol["messages_per_revision"] = MESSAGE_COUNTS[key]
        protocol["exact_restore_verified"] = True
        if protocol["wire_bytes"] <= 0 or protocol["context_loss_last_revision_wire_bytes"] <= 0:
            raise AssertionError("invalid wire accounting")
    modeled = {}
    for label, rtt_ms, bandwidth_mbps in scenarios:
        modeled[label] = {
            key: modeled_completion_ms(protocol["wire_bytes"], len(revisions),
                                       protocol["messages_per_revision"],
                                       rtt_ms, bandwidth_mbps)
            for key, protocol in protocols.items()
        }
    return {
        "history": name,
        "revisions": len(revisions),
        "total_original_bytes": sum(map(len, revisions)),
        "protocols": protocols,
        "modeled_total_completion_ms": modeled,
    }


def run(zstd, scenarios=DEFAULT_SCENARIOS):
    if not zstd:
        raise ValueError("standalone zstd CLI required")
    if not scenarios or len({label for label, _, _ in scenarios}) != len(scenarios):
        raise ValueError("need distinct nonempty modeling scenarios")
    for _, rtt, bandwidth in scenarios:
        modeled_completion_ms(0, 1, 1, rtt, bandwidth)
    data = fixture_histories()
    results = [compare_history(name, revisions, zstd, scenarios)
               for name, revisions in data.items()]
    return {
        "experiment": "001",
        "phase": "7",
        "benchmark_type": "analytical-network-latency-sensitivity-not-measured",
        "measured_network_latency": False,
        "performance_claims_permitted": False,
        "environment": {"python": platform.python_version(),
                        "zstd": shutil.which(zstd) or zstd},
        "protocol_message_counts": MESSAGE_COUNTS,
        "scenarios": [{"id": label, "rtt_ms": rtt, "link_bandwidth_mbps": bandwidth}
                      for label, rtt, bandwidth in scenarios],
        "model": "sum-of-per-revision (encoded_wire_bits/bandwidth + one-way-propagation-per-message)",
        "assumptions": [
            "One-way propagation equals half RTT, all messages sequential, no pipelining.",
            "All counted protocol bytes serialized on the same symmetric fixed-rate link.",
            "Measurements are synthetic encoded bytes; latencies are computed, not observed.",
            "Full snapshot requires 1 one-way message; Phase 4/5 2; Phase 6 3.",
            "All four paths use the identical revision byte sequences per history.",
            "Context storage is raw chunks plus digests only, not allocator, disk or other costs.",
            "No CPU, handshake, TLS, congestion, ack, retransmission, jitter or energy costs.",
            "This script MUST NOT be used as a real networking, security or novelty benchmark.",
        ],
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zstd", default=shutil.which("zstd"))
    args = parser.parse_args()
    print(json.dumps(run(args.zstd), indent=2))


if __name__ == "__main__":
    main()
