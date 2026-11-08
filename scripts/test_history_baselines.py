"""Independent restoration and accounting checks for baseline archives."""

import shutil
import unittest

from benchmark import evolving_corpora
from history_baselines import (HEADER, benchmark, decode_chunk_archive,
                               encode_chunk_archive, git_history)


class HistoryBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.zstd = shutil.which("zstd")
        cls.git = shutil.which("git")
        if not cls.git or not cls.zstd:
            raise unittest.SkipTest("Git and Zstandard CLI required")

    def test_fixed_chunk_archive_roundtrips_complete_histories(self):
        for revisions in evolving_corpora().values():
            package, metrics = encode_chunk_archive(revisions, self.zstd)
            self.assertEqual(decode_chunk_archive(package, self.zstd), revisions)
            self.assertEqual(len(package), metrics["archive_bytes"])
            self.assertEqual(metrics["archive_bytes"], metrics["metadata_bytes"] +
                             metrics["compressed_dictionary_bytes"])
            self.assertGreater(metrics["total_block_references"], metrics["unique_blocks"])

    def test_duplicate_blocks_are_reused(self):
        versions = [b"ABCD" * 200, b"ABCD" * 200, b"ABCD" * 190 + b"WXYZ" * 10]
        package, metrics = encode_chunk_archive(versions, self.zstd, block_size=64)
        self.assertEqual(decode_chunk_archive(package, self.zstd), versions)
        self.assertLess(metrics["unique_blocks"], metrics["total_block_references"])

    def test_rejects_corrupt_manifest_and_trailing_data(self):
        package, _ = encode_chunk_archive([b"abcdef"], self.zstd)
        corrupted = bytearray(package)
        corrupted[HEADER.size] ^= 1
        with self.assertRaises(ValueError):
            decode_chunk_archive(bytes(corrupted), self.zstd)
        with self.assertRaises(ValueError):
            decode_chunk_archive(package + b"extra", self.zstd)
        with self.assertRaises(ValueError):
            decode_chunk_archive(package[:HEADER.size - 1], self.zstd)

    def test_rejects_invalid_limits(self):
        with self.assertRaises(ValueError):
            encode_chunk_archive([], self.zstd)
        with self.assertRaises(ValueError):
            encode_chunk_archive([b"data"], self.zstd, block_size=0)

    def test_git_recoverability_and_accounting(self):
        for family, revisions in evolving_corpora().items():
            result = git_history(revisions, family, self.git)
            self.assertEqual(result["commits"], 5)
            self.assertTrue(result["round_trip_verified"])
            self.assertGreater(result["pack_bytes"], 0)
            self.assertGreaterEqual(result["git_directory_bytes"],
                                    result["pack_bytes"] + result["index_bytes"])
            self.assertGreaterEqual(result["delta_entries"], 0)

    def test_full_report_declares_scope_and_verifies_restore(self):
        report = benchmark(self.zstd, self.git)
        self.assertEqual(report["schema_version"], 1)
        self.assertFalse(report["performance_claims_permitted"])
        self.assertEqual(len(report["results"]), 2)
        for result in report["results"]:
            self.assertEqual(result["revisions"], 5)
            self.assertTrue(result["self_contained_fixed_chunk_archive"]["round_trip_verified"])
            self.assertTrue(result["standalone_zstd_3"]["round_trip_verified"])
            self.assertTrue(result["git_repository"]["round_trip_verified"])


if __name__ == "__main__":
    unittest.main()
