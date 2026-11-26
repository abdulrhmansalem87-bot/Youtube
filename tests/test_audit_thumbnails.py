import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from wealthradar_audit import episode, hook, thumbnails
from wealthradar_audit.charts import PALETTE


class ThumbnailPairTests(unittest.TestCase):
    def setUp(self):
        self.brief = episode.build_brief(100000, 2021, 2025)

    def test_figures_come_from_the_verified_cash_result(self):
        figs = thumbnails.key_figures(self.brief)
        cash = next(r for r in self.brief["results"] if r["key"] == "cash")
        self.assertAlmostEqual(figs["pct"], cash["real_return_pct"])
        self.assertTrue(figs["loss"])

    def test_pair_is_1280x720_under_2mb_and_different(self):
        with tempfile.TemporaryDirectory() as d:
            meta = thumbnails.make_pair(self.brief, d)
            a, b = Image.open(meta["variants"]["A"]), Image.open(meta["variants"]["B"])
            for image, path in ((a, meta["variants"]["A"]), (b, meta["variants"]["B"])):
                self.assertEqual(image.size, (1280, 720))
                self.assertLess(Path(path).stat().st_size, thumbnails.MAX_BYTES)
            self.assertNotEqual(a.tobytes(), b.tobytes())
            saved = json.loads((Path(d) / "thumbnails.json").read_text(encoding="utf-8"))
            self.assertEqual(set(saved["hypotheses"]), {"A", "B"})

    def test_palette_a_is_used(self):
        with tempfile.TemporaryDirectory() as d:
            meta = thumbnails.make_pair(self.brief, d)
            for key in "AB":
                image = Image.open(meta["variants"][key]).convert("RGB")
                self.assertLess(sum(abs(x - y) for x, y in zip(image.getpixel((640, 2)), PALETTE["bg1"])), 30)
                colours = {c for _, c in image.getcolors(maxcolors=1_000_000)}
                self.assertTrue(any(sum(abs(x - y) for x, y in zip(c, PALETTE["gold"])) < 12 for c in colours))

    def test_gain_uses_mint_and_plus_sign(self):
        figs = {"amount": 100000.0, "start_year": 2021, "end_year": 2025, "pct": 12.0, "loss": False, "scenario_ar": "ذهب"}
        with tempfile.TemporaryDirectory() as d:
            out = thumbnails.variant_a(figs, Path(d) / "a.jpg")
            colours = {c for _, c in Image.open(out).convert("RGB").getcolors(maxcolors=1_000_000)}
            self.assertTrue(any(sum(abs(x - y) for x, y in zip(c, PALETTE["gain"])) < 20 for c in colours))

    def test_no_verified_result_means_no_thumbnail(self):
        brief = dict(self.brief, results=[dict(r, status="blocked", real_return_pct=None) for r in self.brief["results"]])
        with self.assertRaises(ValueError):
            thumbnails.key_figures(brief)

    def test_episode_package_includes_the_pair(self):
        with tempfile.TemporaryDirectory() as d:
            package = hook.prepare_episode(d)
            self.assertEqual(set(package["thumbnails"]), {"A", "B"})
            self.assertTrue(Path(package["thumbnails"]["B"]).is_file())


if __name__ == "__main__":
    unittest.main()
