"""Synthetic sync baseline acceptance and negative-path verification."""

import shutil
import subprocess
import unittest

from benchmark import evolving_corpora
from sync_baselines import (
    ADVERTISEMENT, BLOCK_BYTES, DELTA, Receiver, benchmark,
    parse_advertisement, receive_delta, receive_full, scope_digest,
    send_delta, send_full, sha,
)


class SyncBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.zstd = shutil.which("zstd")
        if cls.zstd is None:
            raise unittest.SkipTest("zstd CLI unavailable")

    def test_cold_and_warm_reconstruct_every_revision(self):
        for family, snapshots in evolving_corpora().items():
            scope = "fictional/" + family
            live = Receiver(scope)
            for snapshot in snapshots:
                full = send_full(snapshot, scope, self.zstd)
                self.assertEqual(receive_full(full, scope, self.zstd), snapshot)
                cold = Receiver(scope)
                cold_request = cold.advertisement()
                cold_packet, cm = send_delta(snapshot, cold_request, scope, self.zstd)
                self.assertEqual(receive_delta(cold_packet, cold, self.zstd), snapshot)
                self.assertEqual(cm["total_wire_bytes"], len(cold_request) + len(cold_packet))
                request = live.advertisement()
                packet, wm = send_delta(snapshot, request, scope, self.zstd)
                self.assertEqual(receive_delta(packet, live, self.zstd), snapshot)
                self.assertEqual(wm["total_wire_bytes"], wm["advertisement_bytes"] + wm["payload_bytes"])
                self.assertEqual(wm["payload_bytes"], wm["metadata_bytes"] + wm["compressed_chunk_bytes"])
            self.assertGreater(len(live.chunks), 0)

    def test_context_storage_counts_chunk_bytes_and_hashes(self):
        scope = "fictional/bytes"
        receiver = Receiver(scope)
        source = b"1" * 4096 + b"2" * 4096
        packet, _ = send_delta(source, receiver.advertisement(), scope, self.zstd)
        self.assertEqual(receive_delta(packet, receiver, self.zstd), source)
        self.assertEqual(receiver.stored_context_bytes(), 8192 + 2 * 32)

    def test_corrupted_chunk_payload_does_not_commit_partial_cache(self):
        scope = "fictional/failed-frame"
        receiver = Receiver(scope)
        source = b"sample" * 1500
        packet, _ = send_delta(source, receiver.advertisement(), scope, self.zstd)
        broken = bytearray(packet)
        broken[-1] ^= 0x40
        with self.assertRaises((ValueError, subprocess.CalledProcessError)):
            receive_delta(bytes(broken), receiver, self.zstd)
        self.assertEqual(receiver.chunks, {})

    def test_context_loss_resends_and_recovers(self):
        scope = "fictional/lost"
        original = b"a" * 8192 + b"b" * 4096
        receiver = Receiver(scope)
        packet, _ = send_delta(original, receiver.advertisement(), scope, self.zstd)
        self.assertEqual(receive_delta(packet, receiver, self.zstd), original)
        packet2, metrics = send_delta(original, receiver.advertisement(), scope, self.zstd)
        self.assertEqual(metrics["new_chunks"], 0)
        receiver.chunks.clear()
        with self.assertRaisesRegex(ValueError, "missing or corrupt receiver context"):
            receive_delta(packet2, receiver, self.zstd)
        retry, retry_metrics = send_delta(original, receiver.advertisement(), scope, self.zstd)
        self.assertGreater(retry_metrics["new_chunks"], 0)
        self.assertEqual(receive_delta(retry, receiver, self.zstd), original)

    def test_corrupt_local_cache_is_not_advertised(self):
        scope = "fictional/corruption"
        receiver = Receiver(scope)
        source = b"g" * 4500
        first, _ = send_delta(source, receiver.advertisement(), scope, self.zstd)
        receive_delta(first, receiver, self.zstd)
        key = next(iter(receiver.chunks))
        receiver.chunks[key] = b"corrupt-but-same-identifier"
        self.assertNotIn(key, parse_advertisement(receiver.advertisement(), receiver.scope))
        again, _ = send_delta(source, receiver.advertisement(), scope, self.zstd)
        self.assertEqual(receive_delta(again, receiver, self.zstd), source)
        self.assertEqual(sha(receiver.chunks[key]), key)

    def test_failed_packet_never_modifies_cache(self):
        scope = "fictional/atomic"
        receiver = Receiver(scope)
        packet, _ = send_delta(b"Q" * 6144, receiver.advertisement(), scope, self.zstd)
        broken = bytearray(packet)
        broken[DELTA.size] ^= 1  # change first declared block reference
        before = dict(receiver.chunks)
        with self.assertRaises(ValueError):
            receive_delta(bytes(broken), receiver, self.zstd)
        self.assertEqual(receiver.chunks, before)
        self.assertEqual(receive_delta(packet, receiver, self.zstd), b"Q" * 6144)

    def test_scope_rotation_and_mismatch(self):
        old, new = "fictional/original", "fictional/rotated"
        receiver_old = Receiver(old)
        receiver_new = Receiver(new)
        snapshot = b"secret synthetic content" * 400
        packet, _ = send_delta(snapshot, receiver_old.advertisement(), old, self.zstd)
        receive_delta(packet, receiver_old, self.zstd)
        with self.assertRaisesRegex(ValueError, "scope"):
            send_delta(snapshot, receiver_old.advertisement(), new, self.zstd)
        with self.assertRaisesRegex(ValueError, "scope"):
            receive_delta(packet, receiver_new, self.zstd)
        self.assertEqual(len(receiver_new.chunks), 0)
        rotated, metrics = send_delta(snapshot, receiver_new.advertisement(), new, self.zstd)
        self.assertGreater(metrics["new_chunks"], 0)
        self.assertEqual(receive_delta(rotated, receiver_new, self.zstd), snapshot)

    def test_false_advertisement_fails_closed_then_recovers(self):
        scope = "fictional/false"
        data = b"synthetic" * 800
        phantom = Receiver(scope)
        for i in range(0, len(data), BLOCK_BYTES):
            part = data[i:i + BLOCK_BYTES]
            phantom.chunks[sha(part)] = part
        liar_request = phantom.advertisement()
        packet, metrics = send_delta(data, liar_request, scope, self.zstd)
        self.assertEqual(metrics["new_chunks"], 0)
        empty = Receiver(scope)
        with self.assertRaisesRegex(ValueError, "missing or corrupt receiver context"):
            receive_delta(packet, empty, self.zstd)
        retry, _ = send_delta(data, empty.advertisement(), scope, self.zstd)
        self.assertEqual(receive_delta(retry, empty, self.zstd), data)

    def test_malformed_advertisement_is_rejected(self):
        scope = "fictional/a"
        adv = Receiver(scope).advertisement()
        with self.assertRaises(ValueError):
            parse_advertisement(adv + b"garbage", scope_digest(scope))
        duplicate_key = sha(b"same")
        malformed = ADVERTISEMENT.pack(b"IVAD1", scope_digest(scope), 2) + duplicate_key * 2
        with self.assertRaises(ValueError):
            parse_advertisement(malformed, scope_digest(scope))

    def test_truncated_delta_and_full_are_rejected(self):
        scope = "fictional/truncated"
        receiver = Receiver(scope)
        data = b"a" * 5000
        packet, _ = send_delta(data, receiver.advertisement(), scope, self.zstd)
        with self.assertRaises(ValueError):
            receive_delta(packet[:DELTA.size - 1], receiver, self.zstd)
        broken = bytearray(packet)
        broken[0] ^= 0x1
        with self.assertRaises(ValueError):
            receive_delta(bytes(broken), receiver, self.zstd)
        full = send_full(data, scope, self.zstd)
        with self.assertRaises(ValueError):
            receive_full(full[:-1], scope, self.zstd)
        with self.assertRaises(ValueError):
            receive_full(full, "fictional/not-this-scope", self.zstd)
        self.assertEqual(receiver.chunks, {})

    def test_empty_snapshot(self):
        scope = "fictional/empty"
        receiver = Receiver(scope)
        packet, metrics = send_delta(b"", receiver.advertisement(), scope, self.zstd)
        self.assertEqual(receive_delta(packet, receiver, self.zstd), b"")
        self.assertEqual(metrics["new_chunks"], 0)
        self.assertEqual(receive_full(send_full(b"", scope, self.zstd), scope, self.zstd), b"")

    def test_report_distinguishes_methods(self):
        report = benchmark(self.zstd)
        self.assertFalse(report["performance_claims_permitted"])
        self.assertEqual(report["phase"], "4")
        self.assertEqual(len(report["results"]), 2)
        for entry in report["results"]:
            self.assertTrue(entry["roundtrip_verified"])
            self.assertEqual(entry["warm_catalog_bytes"] + entry["warm_payload_bytes"],
                             entry["warm_chained_delta_wire_bytes"])
            self.assertGreater(entry["warm_context_stored_bytes_peak_lower_bound"], 0)
            self.assertGreater(entry["warm_context_unique_chunks_final"], 0)
            self.assertGreater(entry["context_loss_last_snapshot_resend_bytes"], 0)
            self.assertGreater(entry["scope_rotation_last_snapshot_resend_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
