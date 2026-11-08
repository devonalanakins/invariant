"""Test fixture determinism independently of the Rust executable."""

import hashlib
import unittest

from benchmark import corpora


class CorpusTests(unittest.TestCase):
    def test_determinism(self):
        first = corpora()
        second = corpora()
        self.assertEqual(first, second)
        self.assertEqual(
            {name: hashlib.sha256(data).hexdigest() for name, data in first.items()},
            {name: hashlib.sha256(data).hexdigest() for name, data in second.items()},
        )

    def test_corpus_variation(self):
        data = corpora()
        self.assertEqual(data["empty"], b"")
        self.assertGreater(len(data["structured-jsonl"]), 100_000)
        self.assertEqual(len(data["repeated-bytes"]), 200_000)
        self.assertEqual(len(data["deterministic-noise"]), 120_000)
        self.assertEqual(len(data), 4)


if __name__ == "__main__":
    unittest.main()
