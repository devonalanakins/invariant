"""Negative-path and accounting checks for the research-only two-round protocol."""

import shutil
import subprocess
import unittest

from benchmark import evolving_corpora
from sync_baselines import Receiver, sha
from sync_v2 import (DATA, PROBE, REPLY, benchmark, create_probe, experiment,
                     read_probe, read_reply, receive_data, reply_to_probe,
                     scope_digest, send_data, transfer, stress_histories)


class TwoRoundSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.zstd = shutil.which("zstd")
        if cls.zstd is None:
            raise unittest.SkipTest("zstd CLI unavailable")

    def protocol(self, data, scope="fictional/two-round", chunk_size=4096, receiver=None):
        receiver = receiver or Receiver(scope)
        probe = create_probe(data, scope, chunk_size)
        reply = reply_to_probe(probe, receiver)
        packet, metrics = send_data(data, probe, reply, self.zstd)
        return receiver, probe, reply, packet, metrics

    def test_full_restore_at_multiple_chunk_sizes(self):
        for family, revisions in evolving_corpora().items():
            for chunk_size in (1024, 4096, 16384):
                scope = f"fictional/{family}-{chunk_size}"
                receiver = Receiver(scope)
                for data in revisions:
                    probe = create_probe(data, scope, chunk_size)
                    reply = reply_to_probe(probe, receiver)
                    packet, m = send_data(data, probe, reply, self.zstd)
                    self.assertEqual(m["wire_bytes"], len(probe) + len(reply) + len(packet))
                    self.assertEqual(m["data_bytes"], m["compressed_new_chunk_bytes"] + m["data_metadata_bytes"])
                    self.assertEqual(receive_data(probe, reply, packet, receiver, self.zstd), data)
                self.assertGreater(receiver.stored_context_bytes(), 0)

    def test_identical_repeat_requires_no_new_frame_and_is_exact(self):
        scope = "fictional/repeat"
        receiver = Receiver(scope)
        data = b"ABCD" * 2000
        first = transfer(data, receiver, scope, self.zstd)
        second = transfer(data, receiver, scope, self.zstd)
        self.assertGreater(first["missing_unique_chunks"], 0)
        self.assertEqual(second["missing_unique_chunks"], 0)
        self.assertEqual(second["compressed_new_chunk_bytes"], 0)
        self.assertLess(second["wire_bytes"], first["wire_bytes"])

    def test_empty_snapshot_and_deterministic_messages(self):
        for data in (b"", b"abc", b"Z" * 12288):
            receiver, probe, reply, packet, _ = self.protocol(data)
            self.assertEqual(probe, create_probe(data, "fictional/two-round"))
            self.assertEqual(reply, reply_to_probe(probe, receiver))
            self.assertEqual(packet, send_data(data, probe, reply, self.zstd)[0])
            self.assertEqual(receive_data(probe, reply, packet, receiver, self.zstd), data)

    def test_scope_mismatch_rejected(self):
        data = b"private fictional" * 450
        receiver, probe, reply, packet, _ = self.protocol(data)
        with self.assertRaisesRegex(ValueError, "scope"):
            reply_to_probe(probe, Receiver("fictional/other"))
        with self.assertRaisesRegex(ValueError, "scope"):
            receive_data(probe, reply, packet, Receiver("fictional/other"), self.zstd)
        self.assertEqual(receiver.chunks, {})

    def test_probe_truncation_and_invalid_reference_count_rejected(self):
        data = b"ABC" * 2000
        receiver, probe, reply, packet, _ = self.protocol(data)
        with self.assertRaises(ValueError):
            read_probe(probe[:-1])
        damaged = bytearray(probe)
        damaged[PROBE.size - 1] ^= 1  # reference count
        with self.assertRaises(ValueError):
            read_probe(bytes(damaged))
        with self.assertRaises(ValueError):
            read_probe(probe + b"tail")
        self.assertEqual(receiver.chunks, {})

    def test_reply_hash_mutation_and_bad_padding_rejected(self):
        data = b"f" * 5000
        receiver, probe, reply, packet, _ = self.protocol(data)
        corrupt = bytearray(reply)
        corrupt[REPLY.size - 2] ^= 0xFF
        with self.assertRaises(ValueError):
            read_reply(bytes(corrupt), probe)
        corrupt = bytearray(reply)
        corrupt[-1] |= 0x80  # reference count is 2, so the high bit is padding
        with self.assertRaisesRegex(ValueError, "padding"):
            read_reply(bytes(corrupt), probe)
        self.assertEqual(receiver.chunks, {})

    def test_duplicate_availability_bits_must_agree(self):
        scope = "fictional/duplicates"
        data = b"a" * 4096 * 2
        receiver, probe, reply, packet, _ = self.protocol(data, scope)
        self.assertEqual(len(read_probe(probe)[4]), 2)
        inconsistent = bytearray(reply)
        inconsistent[-1] |= 0x01  # first present but second absent, identical hash
        with self.assertRaisesRegex(ValueError, "duplicate"):
            read_reply(bytes(inconsistent), probe)

    def test_corrupt_chunk_and_trailing_data_fail_atomically(self):
        data = b"first" * 2000
        receiver, probe, reply, packet, _ = self.protocol(data)
        for broken in (packet[:-1], packet + b"extra", bytes(bytearray(packet)[:-1] + b"X")):
            with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                receive_data(probe, reply, broken, receiver, self.zstd)
            self.assertEqual(receiver.chunks, {})
        self.assertEqual(receive_data(probe, reply, packet, receiver, self.zstd), data)

    def test_context_loss_after_reply_fails_and_retries(self):
        scope = "fictional/loss"
        data = b"cache" * 1500
        receiver = Receiver(scope)
        transfer(data, receiver, scope, self.zstd)
        probe = create_probe(data, scope)
        reply = reply_to_probe(probe, receiver)
        packet, metrics = send_data(data, probe, reply, self.zstd)
        self.assertEqual(metrics["missing_unique_chunks"], 0)
        receiver.chunks.clear()
        with self.assertRaisesRegex(ValueError, "missing or corrupt context"):
            receive_data(probe, reply, packet, receiver, self.zstd)
        retry = transfer(data, receiver, scope, self.zstd)
        self.assertGreater(retry["missing_unique_chunks"], 0)

    def test_false_availability_requires_reprobe(self):
        scope = "fictional/false-availability"
        data = b"ABC" * 1700
        liar = Receiver(scope)
        transfer(data, liar, scope, self.zstd)
        probe = create_probe(data, scope)
        false_reply = reply_to_probe(probe, liar)
        packet, _ = send_data(data, probe, false_reply, self.zstd)
        honest = Receiver(scope)
        with self.assertRaisesRegex(ValueError, "missing or corrupt context"):
            receive_data(probe, false_reply, packet, honest, self.zstd)
        self.assertEqual(honest.chunks, {})
        self.assertGreater(transfer(data, honest, scope, self.zstd)["missing_unique_chunks"], 0)

    def test_tampering_immutable_probe_binding_is_rejected(self):
        receiver, probe, reply, packet, _ = self.protocol(b"a" * 8000)
        mutated_probe = bytearray(probe)
        mutated_probe[PROBE.size] ^= 1
        with self.assertRaisesRegex(ValueError, "probe"):
            read_reply(reply, bytes(mutated_probe))
        with self.assertRaisesRegex(ValueError, "sender input"):
            send_data(b"different", probe, reply, self.zstd)
        mutated_packet = bytearray(packet)
        mutated_packet[DATA.size - 8] ^= 1
        with self.assertRaises(ValueError):
            receive_data(probe, reply, bytes(mutated_packet), receiver, self.zstd)
        self.assertEqual(receiver.chunks, {})

    def test_recovery_and_scope_rotation_are_counted(self):
        result = experiment("evolving-events", evolving_corpora()["evolving-events"], self.zstd)
        self.assertTrue(result["roundtrip_verified"])
        self.assertGreater(result["context_loss_last_snapshot_recovery_bytes"], 0)
        self.assertGreater(result["scope_rotation_last_snapshot_bytes"], 0)
        self.assertEqual(result["warm_wire_bytes"], result["warm_probe_bytes"]
                         + result["warm_reply_bytes"] + result["warm_data_bytes"])

    def test_stress_histories_are_deterministic_and_distinct(self):
        first, second = stress_histories(), stress_histories()
        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)
        for history in first.values():
            self.assertEqual(len(history), 5)
            self.assertEqual(len({sha(s) for s in history}), 5)
        self.assertEqual([len(x) for x in first["stress-independent-noise"]],
                         [12 * 1024] * 5)

    def test_preexisting_cache_remains_unchanged_after_failed_new_revision(self):
        scope = "fictional/atomic-existing"
        receiver = Receiver(scope)
        previous = b"A" * 8192
        transfer(previous, receiver, scope, self.zstd)
        before = dict(receiver.chunks)
        next_version = previous + b"new" * 1200
        probe = create_probe(next_version, scope)
        reply = reply_to_probe(probe, receiver)
        packet, _ = send_data(next_version, probe, reply, self.zstd)
        damaged = bytearray(packet)
        damaged[-1] ^= 0x3f
        with self.assertRaises((ValueError, subprocess.CalledProcessError)):
            receive_data(probe, reply, bytes(damaged), receiver, self.zstd)
        self.assertEqual(receiver.chunks, before)
        self.assertEqual(receive_data(probe, reply, packet, receiver, self.zstd),
                         next_version)

    def test_benchmark_has_baselines_and_no_novelty_claim(self):
        report = benchmark(self.zstd, (4096,))
        self.assertFalse(report["performance_claims_permitted"])
        self.assertEqual(len(report["results"]), 4)
        for r in report["results"]:
            self.assertTrue(r["roundtrip_verified"])
            self.assertGreater(r["receiver_context_bytes_peak_lower_bound"], 0)
            self.assertGreater(r["warm_wire_bytes"], 0)
            self.assertGreater(r["v1_full_zstd_wire_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
