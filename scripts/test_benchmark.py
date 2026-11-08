"""Determinism and exact-restore tests for synthetic benchmarking fixtures."""

import shutil
import tempfile
import unittest
from pathlib import Path

from benchmark import CODECS, corpora, decode, digest, encode, evolving_corpora


class CorpusTests(unittest.TestCase):
    def test_original_fixtures_remain_deterministic(self):
        first, second = corpora(), corpora()
        self.assertEqual(first, second)
        self.assertEqual(
            {name: digest(data) for name, data in first.items()},
            {name: digest(data) for name, data in second.items()},
        )
        self.assertEqual(first["empty"], b"")
        self.assertEqual(len(first["repeated-bytes"]), 200_000)
        self.assertEqual(len(first["deterministic-noise"]), 120_000)
        self.assertEqual(len(first), 4)

    def test_evolving_histories_are_reproducible_and_change(self):
        a, b = evolving_corpora(), evolving_corpora()
        self.assertEqual(a, b)
        self.assertEqual(set(a), {"evolving-code", "evolving-events"})
        for revisions in a.values():
            self.assertEqual(len(revisions), 5)
            self.assertEqual(len({digest(r) for r in revisions}), 5)
            self.assertTrue(all(len(r) > 10_000 for r in revisions))
            self.assertTrue(all(len(revisions[i]) >= len(revisions[i - 1]) - 100
                                for i in range(1, len(revisions))))

    def test_pinned_history_hashes(self):
        expected = {
            "evolving-code": [
                "893b4dc6bde3cb5b9a9f061f014633e4ef7fb2707b61f51602ddcdc46be60477",
                "922c6a4e30a0b124e5f03e716f28bfabbe9b90d0d4d390f3e3a9350b7d9ea8f6",
                "10814f4ee2eb0d589d44fe112b6ef0eb27a2c2fb30ef1d203758812c51395a14",
                "27d017509da7a8e473b231f572827c36ffa715a3ce673696d1474c1b3f6fc73a",
                "326d2227d531a070d7a15e0461d2e30af1a4637c8c6977064bc0f8cb14c1a471",
            ],
            "evolving-events": [
                "318351ad99cd42479e21335347dbb203a536f9f2d8725329cde810fd8a1e890c",
                "17a97920d7f21d17582e4c4756b155303c33cf372c06f381c4e0dbca9cb83a21",
                "569bbbfdcd87be37a1db0a6c21fe25f8e28fcd07288e971540d265f8ff81c7eb",
                "1c2d7d907741c02d70e80a5af5c76ef187efd91ee85ad7f734b9a29df9bd5551",
                "b9b2383193245014eb44a79e7bddff78741f6ac599b8342bd3d93a2794296bd8",
            ],
        }
        actual = {name: [digest(data) for data in history]
                  for name, history in evolving_corpora().items()}
        self.assertEqual(actual, expected)

    def test_standalone_codec_roundtrip_and_determinism(self):
        zstd = shutil.which("zstd")
        codecs = [c for c in CODECS if c != "invariant_v0" and (c != "zstd_3" or zstd)]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.bin"
            for name, original in corpora().items():
                source.write_bytes(original)
                for codec in codecs:
                    once, _ = encode(codec, source, original, None, zstd, root)
                    twice, _ = encode(codec, source, original, None, zstd, root)
                    restored, _ = decode(codec, once, None, zstd, root)
                    self.assertEqual(once, twice, (name, codec))
                    self.assertEqual(restored, original, (name, codec))


if __name__ == "__main__":
    unittest.main()
