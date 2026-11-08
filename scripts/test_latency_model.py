"""Independent invariants for illustrative network-delay sensitivity model."""

import shutil
import unittest

from latency_model import (DEFAULT_SCENARIOS, MESSAGE_COUNTS,
                           compare_history, fixture_histories,
                           modeled_completion_ms, run)
from sync_baselines import Receiver


class AnalyticModelUnitTests(unittest.TestCase):
    def test_known_time_and_unit_conversion(self):
        # 1000 bytes * 8 bits / 10 Mb/s = 0.8 ms, plus 25 ms propagation.
        self.assertEqual(modeled_completion_ms(1000, 1, 1, 50, 10), 25.8)
        self.assertEqual(modeled_completion_ms(1000, 1, 3, 50, 10), 75.8)

    def test_extra_protocol_message_costs_half_rtt_per_revision(self):
        kwargs = dict(total_wire_bytes=1000, revisions=5, rtt_ms=50, bandwidth_mbps=10)
        with_two = modeled_completion_ms(messages_per_revision=2, **kwargs)
        with_three = modeled_completion_ms(messages_per_revision=3, **kwargs)
        self.assertEqual(round(with_three - with_two, 5), 125.0)

    def test_invalid_inputs_rejected(self):
        cases = [(-1, 1, 1, 50, 10), (1000, 0, 1, 50, 10),
                 (1000, 1, 0, 50, 10), (1000, 1, 1, -1, 10),
                 (1000, 1, 1, 50, 0), (1000, 1, 1, 50, float("nan"))]
        for args in cases:
            with self.subTest(args=args), self.assertRaises(ValueError):
                modeled_completion_ms(*args)

    def test_monotonic_costs(self):
        low = modeled_completion_ms(1000, 5, 2, 5, 100)
        self.assertLess(low, modeled_completion_ms(1000, 5, 2, 50, 100))
        self.assertLess(low, modeled_completion_ms(2000, 5, 2, 5, 100))
        self.assertLess(low, modeled_completion_ms(1000, 5, 2, 5, 1))

    def test_scenarios_and_data_are_deterministic(self):
        self.assertEqual(len(DEFAULT_SCENARIOS), 4)
        self.assertEqual(set(MESSAGE_COUNTS), {
            "full_zstd", "legacy_per_chunk", "catalog_index_batched", "need_specific_probe"})
        data_a = fixture_histories()
        self.assertEqual(data_a, fixture_histories())
        self.assertEqual(len(data_a), 6)
        self.assertEqual({len(rev) for rev in data_a.values()}, {5})
        self.assertGreater(len(data_a["mutating-binary"][0]),
                           len(data_a["stress-independent-noise"][0]))


class AnalyticModelIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.zstd = shutil.which("zstd")
        if cls.zstd is None:
            raise unittest.SkipTest("zstd CLI required")

    def test_1_history_roundtrip_and_accounting(self):
        history = fixture_histories()["evolving-events"]
        report = compare_history("evolving-events", history, self.zstd)
        self.assertEqual(report["revisions"], 5)
        methods = report["protocols"]
        self.assertEqual(set(methods), set(MESSAGE_COUNTS))
        self.assertTrue(all(method["exact_restore_verified"] for method in methods.values()))
        self.assertTrue(all(method["context_loss_last_revision_wire_bytes"] > 0
                            for method in methods.values()))
        self.assertEqual(methods["full_zstd"]["context_stored_bytes_lower_bound"], 0)
        self.assertTrue(all(methods[k]["context_stored_bytes_lower_bound"] > 0
                            for k in methods if k != "full_zstd"))
        zero = report["modeled_total_completion_ms"]["zero-rtt-10mbps"]
        for key in methods:
            self.assertEqual(zero[key],
                             modeled_completion_ms(methods[key]["wire_bytes"], 5,
                                                   methods[key]["messages_per_revision"], 0, 10))

    def test_high_rtt_changes_byte_advantage_interpretation(self):
        report = compare_history("evolving-events", fixture_histories()["evolving-events"],
                                 self.zstd)
        zero = report["modeled_total_completion_ms"]["zero-rtt-10mbps"]
        wan = report["modeled_total_completion_ms"]["wan-50ms-10mbps"]
        self.assertLess(zero["need_specific_probe"], zero["catalog_index_batched"])
        self.assertGreater(wan["need_specific_probe"], wan["catalog_index_batched"])

    def test_full_report_discloses_assumptions_and_losing_cases(self):
        report = run(self.zstd)
        self.assertEqual(report["phase"], "7")
        self.assertFalse(report["performance_claims_permitted"])
        self.assertFalse(report["measured_network_latency"])
        self.assertEqual(len(report["results"]), 6)
        by_name = {r["history"]: r for r in report["results"]}
        self.assertGreater(by_name["shifted-binary"]["protocols"]["need_specific_probe"]["wire_bytes"],
                           by_name["shifted-binary"]["protocols"]["full_zstd"]["wire_bytes"])
        self.assertGreater(by_name["stress-independent-noise"]["protocols"]["need_specific_probe"]["wire_bytes"],
                           by_name["stress-independent-noise"]["protocols"]["full_zstd"]["wire_bytes"])


if __name__ == "__main__":
    unittest.main()
