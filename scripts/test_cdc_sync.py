"""Falsification-first tests for a simple content-defined chunking baseline."""

import shutil
import subprocess
import unittest
from unittest.mock import patch

from benchmark import evolving_corpora
from batched_sync import synthetic_shifted_binary
from cdc_sync import (HEADER, INDEX, NEW_BLOCK, Receiver, benchmark, cdc_chunks,
                      cdc_compare, fixture_histories, receive_cdc, send_cdc,
                      validate_params)


class ChunkingTests(unittest.TestCase):
    def test_repeatability_and_exact_join(self):
        data = synthetic_shifted_binary()[0]
        chunks = cdc_chunks(data)
        self.assertEqual(chunks, cdc_chunks(data))
        self.assertEqual(b"".join(chunks), data)
        self.assertTrue(all(1 <= len(c) <= 8192 for c in chunks))
        self.assertTrue(all(len(c) >= 2048 for c in chunks[:-1]))

    def test_empty_and_short_inputs(self):
        self.assertEqual(cdc_chunks(b""), [])
        self.assertEqual(cdc_chunks(b"ab"), [b"ab"])
        self.assertEqual(cdc_chunks(b"X" * 2048)[0], b"X" * 2048)

    def test_invalid_parameters(self):
        for params in [(0, 4096, 8192), (2048, 3000, 8192),
                       (8192, 4096, 8192), (2048, 4096, 1024),
                       (2048, 4096, 65537)]:
            with self.subTest(params=params), self.assertRaises(ValueError):
                validate_params(*params)

    def test_cutpoints_resynchronize_after_prefix_insertion(self):
        versions = synthetic_shifted_binary()
        first, shifted = [set(cdc_chunks(v)) for v in versions[:2]]
        self.assertGreater(len(first & shifted), 10)
        self.assertNotEqual(versions[0], versions[1])

    def test_synthetic_fixture_is_deterministic(self):
        self.assertEqual(fixture_histories(), fixture_histories())
        self.assertEqual(set(fixture_histories()), {
            "evolving-code", "evolving-events", "mutating-binary",
            "shifted-binary", "independent-noise"})


class CdcProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.zstd = shutil.which("zstd")
        if not cls.zstd:
            raise unittest.SkipTest("zstd CLI required")

    def build(self, data=b"DATA" * 1600, scope="fictional/test", receiver=None):
        receiver = receiver or Receiver(scope)
        ad = receiver.advertisement()
        packet, metrics = send_cdc(data, ad, scope, self.zstd)
        return receiver, ad, packet, metrics

    def test_all_history_snapshots_restore_exactly(self):
        for name, versions in fixture_histories().items():
            scope = "fictional/" + name
            receiver = Receiver(scope)
            for value in versions:
                receiver, ad, packet, stat = self.build(value, scope, receiver)
                self.assertEqual(stat["wire_bytes"], len(ad) + len(packet))
                self.assertEqual(stat["payload_bytes"],
                                 stat["metadata_bytes"] + stat["compressed_frame_bytes"])
                self.assertEqual(receive_cdc(packet, ad, receiver, self.zstd), value)
            self.assertGreater(receiver.stored_context_bytes(), 0)

    def test_empty_and_repeated_input(self):
        receiver, ad, pkt, stat = self.build(b"")
        self.assertEqual(stat["new_unique_chunks"], 0)
        self.assertEqual(stat["compressed_frame_bytes"], 0)
        self.assertEqual(receive_cdc(pkt, ad, receiver, self.zstd), b"")
        data = b"repeated" * 1400
        receiver, ad, pkt, stat = self.build(data, receiver=receiver)
        self.assertEqual(receive_cdc(pkt, ad, receiver, self.zstd), data)
        receiver, ad, pkt, stat = self.build(data, receiver=receiver)
        self.assertEqual(stat["new_unique_chunks"], 0)
        self.assertEqual(receive_cdc(pkt, ad, receiver, self.zstd), data)

    def test_atomicity_on_corrupt_reference(self):
        receiver, ad, packet, _ = self.build()
        mutated = bytearray(packet)
        mutated[HEADER.size] ^= 0x7f
        with self.assertRaises(ValueError):
            receive_cdc(bytes(mutated), ad, receiver, self.zstd)
        self.assertEqual(receiver.chunks, {})
        self.assertEqual(receive_cdc(packet, ad, receiver, self.zstd), b"DATA" * 1600)

    def test_corrupt_compressed_frame_is_rejected(self):
        receiver, ad, packet, _ = self.build()
        damaged = bytearray(packet)
        damaged[-1] ^= 0x44
        with self.assertRaises((ValueError, subprocess.CalledProcessError)):
            receive_cdc(bytes(damaged), ad, receiver, self.zstd)
        self.assertEqual(receiver.chunks, {})

    def test_wrong_scope_and_bad_advertisement_rejected(self):
        receiver, ad, packet, _ = self.build()
        with self.assertRaisesRegex(ValueError, "scope"):
            receive_cdc(packet, ad, Receiver("fictional/other"), self.zstd)
        with self.assertRaises(ValueError):
            send_cdc(b"abc", ad + b"extra", "fictional/test", self.zstd)
        self.assertEqual(receiver.chunks, {})

    def test_context_loss_and_stale_catalog(self):
        receiver, ad, packet, _ = self.build()
        receive_cdc(packet, ad, receiver, self.zstd)
        reused_ad = receiver.advertisement()
        next_packet, stat = send_cdc(b"DATA" * 1600, reused_ad,
                                     "fictional/test", self.zstd)
        self.assertEqual(stat["new_unique_chunks"], 0)
        receiver.chunks.clear()
        with self.assertRaisesRegex(ValueError, "stale"):
            receive_cdc(next_packet, reused_ad, receiver, self.zstd)
        new_ad = receiver.advertisement()
        restore, _ = send_cdc(b"DATA" * 1600, new_ad, "fictional/test", self.zstd)
        self.assertEqual(receive_cdc(restore, new_ad, receiver, self.zstd), b"DATA" * 1600)

    def test_wrong_payload_length_and_trailing_bytes_rejected(self):
        receiver, ad, packet, _ = self.build()
        for forged in (packet[:HEADER.size - 1], packet[:-1], packet + b"suffix"):
            with self.subTest(n=len(forged)), self.assertRaises(ValueError):
                receive_cdc(forged, ad, receiver, self.zstd)
        self.assertEqual(receiver.chunks, {})

    def test_corrupt_existing_cached_block_forces_retransfer(self):
        receiver, ad, packet, _ = self.build()
        receive_cdc(packet, ad, receiver, self.zstd)
        key = next(iter(receiver.chunks))
        receiver.chunks[key] = b"incorrect"
        new_ad = receiver.advertisement()
        pkt, m = send_cdc(b"DATA" * 1600, new_ad, "fictional/test", self.zstd)
        self.assertGreater(m["new_unique_chunks"], 0)
        self.assertEqual(receive_cdc(pkt, new_ad, receiver, self.zstd), b"DATA" * 1600)

    def test_noncanonical_chunk_boundaries_fail_before_cache_commit(self):
        from cdc_sync import cdc_chunks as real_chunks
        scope = "fictional/noncanonical"
        data = b"RANDOM-BYTES-SYNTHETIC" * 460
        receiver = Receiver(scope)
        adv = receiver.advertisement()
        # A forged sender provides a valid whole-object digest but violates
        # canonical CDC cutpoints; receiver must independently reject it.
        forged_pieces = [data[:5000], data[5000:]]
        with patch("cdc_sync.cdc_chunks", return_value=forged_pieces):
            forged, _ = send_cdc(data, adv, scope, self.zstd)
        self.assertNotEqual(real_chunks(data), forged_pieces)
        with self.assertRaisesRegex(ValueError, "cutpoint"):
            receive_cdc(forged, adv, receiver, self.zstd)
        self.assertEqual(receiver.chunks, {})

    def test_bad_new_chunk_length_is_rejected_atomically(self):
        receiver, ad, packet, _ = self.build()
        payload = bytearray(packet)
        (magic, scope, ad_hash, digest, total, lo, target, hi, nrefs,
         nnew, frame_len) = HEADER.unpack_from(payload)
        self.assertGreater(nnew, 0)
        length_position = HEADER.size + nrefs * INDEX.size + 32
        payload[length_position:length_position + 4] = (hi + 1).to_bytes(4, "little")
        with self.assertRaisesRegex(ValueError, "definition"):
            receive_cdc(bytes(payload), ad, receiver, self.zstd)
        self.assertEqual(receiver.chunks, {})

    def test_shifted_binary_wire_savings_are_workload_specific(self):
        report = cdc_compare("shifted-binary", synthetic_shifted_binary(), self.zstd)
        self.assertTrue(report["roundtrip_verified"])
        self.assertLess(report["warm_cdc_wire_bytes"], report["wire_bytes_full_zstd"])
        self.assertGreater(report["retained_context_bytes_peak_lower_bound"], 0)

    def test_full_comparison_preserves_negative_cases(self):
        report = benchmark(self.zstd)
        self.assertFalse(report["performance_claims_permitted"])
        self.assertFalse(report["measured_network_latency"])
        self.assertEqual(len(report["results"]), 5)
        cases = {x["history"]: x for x in report["results"]}
        for name, item in cases.items():
            self.assertTrue(item["roundtrip_verified"], name)
            self.assertEqual(item["wire_bytes_full_zstd"], item["full_zstd_wire_bytes"])
            self.assertGreater(item["last_snapshot_context_loss_resend_wire_bytes"], 0)
        self.assertGreater(cases["independent-noise"]["warm_cdc_wire_bytes"],
                           cases["independent-noise"]["full_zstd_wire_bytes"])


if __name__ == "__main__":
    unittest.main()
