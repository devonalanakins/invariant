"""Falsification-first acceptance cases for the synthetic batched sync candidate."""

import shutil
import subprocess
import unittest

from batched_sync import (HEADER, INDEX, NEW_BLOCK, Receiver, compare,
                          receive_batched, run, send_batched,
                          synthetic_mutating_binary, synthetic_shifted_binary)
from benchmark import evolving_corpora
from sync_baselines import BLOCK_BYTES, sha


class BatchedSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.zstd = shutil.which("zstd")
        if not cls.zstd:
            raise unittest.SkipTest("zstd CLI unavailable")

    def exchange(self, data, scope="fictional/acceptance", receiver=None):
        receiver = receiver or Receiver(scope)
        adv = receiver.advertisement()
        packet, stats = send_batched(data, adv, scope, self.zstd)
        self.assertEqual(stats["total_wire_bytes"], len(adv) + len(packet))
        self.assertEqual(stats["payload_bytes"], stats["metadata_bytes"] + stats["compressed_frame_bytes"])
        self.assertEqual(receive_batched(packet, adv, receiver, self.zstd), data)
        return receiver, adv, packet, stats

    def test_fixture_histories_restore_exactly(self):
        histories = evolving_corpora()
        histories["mutating-binary"] = synthetic_mutating_binary()
        histories["shifted-binary"] = synthetic_shifted_binary()
        for name, revisions in histories.items():
            scope = "fictional/" + name
            receiver = Receiver(scope)
            for revision in revisions:
                receiver, _, _, _ = self.exchange(revision, scope, receiver)
            self.assertGreater(receiver.stored_context_bytes(), 0)

    def test_empty_and_all_known_carry_no_frame(self):
        scope = "fictional/empty"
        receiver, _, _, stats = self.exchange(b"", scope)
        self.assertEqual(stats["new_chunks"], 0)
        self.assertEqual(stats["compressed_frame_bytes"], 0)
        data = b"a" * BLOCK_BYTES * 2
        receiver, _, _, stats = self.exchange(data, scope, receiver)
        self.assertEqual(stats["new_chunks"], 1)  # duplicate blocks deduplicated
        receiver, _, _, stats = self.exchange(data, scope, receiver)
        self.assertEqual(stats["new_chunks"], 0)
        self.assertEqual(stats["compressed_frame_bytes"], 0)
        self.assertEqual(stats["reused_references"], 2)

    def test_missing_advertised_context_fails_without_mutation(self):
        scope = "fictional/loss"
        data = b"a" * 6000 + b"b" * 6000
        receiver, _, _, _ = self.exchange(data, scope)
        old_catalog = receiver.advertisement()
        packet, _ = send_batched(data, old_catalog, scope, self.zstd)
        receiver.chunks.clear()
        with self.assertRaisesRegex(ValueError, "stale or corrupt"):
            receive_batched(packet, old_catalog, receiver, self.zstd)
        self.assertEqual(receiver.chunks, {})
        receiver, _, _, _ = self.exchange(data, scope, receiver)
        self.assertGreater(len(receiver.chunks), 0)

    def test_changed_catalog_fails_closed(self):
        scope = "fictional/catalog-change"
        receiver = Receiver(scope)
        original = b"a" * 5000
        adv = receiver.advertisement()
        packet, _ = send_batched(original, adv, scope, self.zstd)
        receiver.chunks[sha(b"other")] = b"other"
        before = dict(receiver.chunks)
        with self.assertRaisesRegex(ValueError, "stale or corrupt"):
            receive_batched(packet, adv, receiver, self.zstd)
        self.assertEqual(receiver.chunks, before)

    def test_corrupted_payload_fails_and_never_commits(self):
        scope = "fictional/tamper"
        receiver = Receiver(scope)
        data = b"g" * 5000 + b"h" * 5000
        adv = receiver.advertisement()
        packet, _ = send_batched(data, adv, scope, self.zstd)
        tampered = bytearray(packet)
        tampered[-1] ^= 0x20
        with self.assertRaises((ValueError, subprocess.CalledProcessError)):
            receive_batched(bytes(tampered), adv, receiver, self.zstd)
        self.assertEqual(receiver.chunks, {})

    def test_tampered_reference_digest_fails_and_never_commits(self):
        scope = "fictional/broken-ref"
        receiver = Receiver(scope)
        adv = receiver.advertisement()
        packet, _ = send_batched(b"z" * 5000, adv, scope, self.zstd)
        modified = bytearray(packet)
        modified[HEADER.size] ^= 0xff  # first u32 reference index
        with self.assertRaises(ValueError):
            receive_batched(bytes(modified), adv, receiver, self.zstd)
        self.assertEqual(receiver.chunks, {})

    def test_tampered_chunk_header_fails_and_never_commits(self):
        scope = "fictional/broken-chunk"
        receiver = Receiver(scope)
        adv = receiver.advertisement()
        packet, _ = send_batched(b"x" * 5000, adv, scope, self.zstd)
        modified = bytearray(packet)
        offset = HEADER.size + 2 * INDEX.size
        modified[offset] ^= 0x01  # hash of first declared new chunk
        with self.assertRaises(ValueError):
            receive_batched(bytes(modified), adv, receiver, self.zstd)
        self.assertEqual(receiver.chunks, {})

    def test_truncation_and_trailing_bytes_rejected(self):
        scope = "fictional/truncated"
        receiver = Receiver(scope)
        adv = receiver.advertisement()
        packet, _ = send_batched(b"a" * 5000, adv, scope, self.zstd)
        for candidate in (packet[:-1], packet + b"garbage", packet[:HEADER.size - 1]):
            with self.assertRaises(ValueError):
                receive_batched(candidate, adv, receiver, self.zstd)
        self.assertEqual(receiver.chunks, {})

    def test_scope_rotation_disallows_cross_context_references(self):
        original = "fictional/old"
        receiver, adv, packet, _ = self.exchange(b"s" * 9000, original)
        rotated = Receiver("fictional/new")
        with self.assertRaisesRegex(ValueError, "scope"):
            receive_batched(packet, adv, rotated, self.zstd)
        with self.assertRaisesRegex(ValueError, "scope"):
            send_batched(b"s" * 9000, adv, "fictional/new", self.zstd)
        self.assertEqual(rotated.chunks, {})
        self.exchange(b"s" * 9000, "fictional/new", rotated)

    def test_receiver_cache_corruption_is_not_referenced(self):
        scope = "fictional/bad-cache"
        receiver, _, _, _ = self.exchange(b"j" * 6000, scope)
        key = next(iter(receiver.chunks))
        receiver.chunks[key] = b"invalid"
        receiver, _, _, stats = self.exchange(b"j" * 6000, scope, receiver)
        self.assertGreater(stats["new_chunks"], 0)
        self.assertEqual(sha(receiver.chunks[key]), key)

    def test_bad_sender_advertisement_is_rejected(self):
        scope = "fictional/bad-ad"
        receiver = Receiver(scope)
        adv = receiver.advertisement()
        with self.assertRaises(ValueError):
            send_batched(b"a", adv + b"x", scope, self.zstd)
        packet, _ = send_batched(b"a", adv, scope, self.zstd)
        with self.assertRaisesRegex(ValueError, "incorrect advertisement digest"):
            receive_batched(packet, adv + b"x", receiver, self.zstd)

    def test_invalid_block_size_rejected(self):
        scope = "fictional/bad-size"
        adv = Receiver(scope).advertisement()
        with self.assertRaises(ValueError):
            send_batched(b"hello", adv, scope, self.zstd, chunk_size=0)
        with self.assertRaises(ValueError):
            send_batched(b"hello", adv, scope, self.zstd, chunk_size=65537)

    def test_known_bytes_are_preserved_when_failure_occurs(self):
        scope = "fictional/atomic-cache"
        receiver, _, _, _ = self.exchange(b"X" * 6000, scope)
        before = dict(receiver.chunks)
        adv = receiver.advertisement()
        packet, _ = send_batched(b"X" * 5000 + b"Y" * 8000, adv, scope, self.zstd)
        broken = bytearray(packet)
        broken[-1] ^= 0x01
        with self.assertRaises((ValueError, subprocess.CalledProcessError)):
            receive_batched(bytes(broken), adv, receiver, self.zstd)
        self.assertEqual(receiver.chunks, before)

    def test_benchmark_reports_both_favorable_and_unfavorable_cases(self):
        report = run(self.zstd)
        self.assertFalse(report["performance_claims_permitted"])
        cases = {r["history"]: r for r in report["results"]}
        self.assertEqual(len(cases), 4)
        for item in cases.values():
            self.assertTrue(item["roundtrip_verified"])
            self.assertEqual(item["revisions"], 5)
            self.assertGreater(item["chained_warm_batched_wire_bytes"], item["warm_advertisement_bytes"])
        self.assertLess(cases["mutating-binary"]["chained_warm_batched_wire_bytes"],
                        cases["mutating-binary"]["stateless_full_wire_bytes"])
        self.assertGreater(cases["shifted-binary"]["chained_warm_batched_wire_bytes"],
                           cases["shifted-binary"]["stateless_full_wire_bytes"])


if __name__ == "__main__":
    unittest.main()
