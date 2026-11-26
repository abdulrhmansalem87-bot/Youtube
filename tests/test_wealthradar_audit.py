import tempfile
import unittest
from pathlib import Path

from PIL import Image

from wealthradar_audit import calculator, charts, data, description, episode


class CalculatorTests(unittest.TestCase):
    def test_cumulative_inflation_matches_world_bank_series(self):
        self.assertAlmostEqual(calculator.cumulative_inflation(2021, 2025), 2.2313, places=3)

    def test_cash_loses_real_value(self):
        cash = calculator.run_scenarios(100000, 2021, 2025)[0]
        self.assertEqual(cash.end_value, 100000)
        self.assertAlmostEqual(cash.real_end_value, 44818, delta=5)

    def test_dollar_and_gold_multiples(self):
        res = {r.key: r for r in calculator.run_scenarios(100000, 2021, 2025)}
        self.assertAlmostEqual(res["dollar"].multiple, 49.2278 / 15.6445, places=6)
        gold = (3441.58 * 49.2278) / (1799.42 * 15.6445)
        self.assertAlmostEqual(res["gold"].multiple, gold, places=6)
        self.assertGreater(res["gold"].multiple, res["dollar"].multiple)

    def test_certificate_blocked_until_rates_are_sourced(self):
        res = {r.key: r for r in calculator.run_scenarios(100000, 2021, 2025)}
        self.assertEqual(res["certificate"].status, "blocked")
        ok, problems = calculator.publishable(list(res.values()))
        self.assertFalse(ok)
        self.assertTrue(any("certificate" in p for p in problems))

    def test_certificate_runs_with_supplied_rates_but_is_not_publishable(self):
        rates = {2022: 10.0, 2023: 10.0}
        res = {r.key: r for r in calculator.run_scenarios(100000, 2021, 2023, rates)}
        self.assertEqual(res["certificate"].status, "ok")
        self.assertAlmostEqual(res["certificate"].end_value, 121000, places=4)
        self.assertFalse(res["certificate"].verified)
        self.assertFalse(calculator.publishable(list(res.values()))[0])

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            calculator.run_scenarios(-1, 2021, 2025)
        with self.assertRaises(ValueError):
            calculator.run_scenarios(100, 2025, 2021)
        with self.assertRaises(ValueError):
            calculator.run_scenarios(100, 2021, 2030)

    def test_every_series_has_source_url(self):
        for name, s in data.SOURCES.items():
            self.assertTrue(s["url"].startswith("https://"), name)
            self.assertTrue(s["values"], name)


class EpisodeTests(unittest.TestCase):
    def test_structure_is_9_to_11_minutes(self):
        episode.validate_structure()
        self.assertGreaterEqual(episode.total_seconds(), 540)
        self.assertLessEqual(episode.total_seconds(), 660)

    def test_required_segments_present(self):
        keys = [s[0] for s in episode.SEGMENTS]
        for k in ("hook", "what_happened", "why", "winners_egypt", "winners_gulf", "scenarios", "receipt", "takeaways"):
            self.assertIn(k, keys)

    def test_brief_blocks_publication_while_certificate_data_missing(self):
        brief = episode.build_brief(100000, 2021, 2025)
        self.assertFalse(brief["publishable"])
        self.assertEqual(brief["chapters"][0], ("0:00", "الخطاف"))
        self.assertEqual(sum(s["seconds"] for s in brief["segments"]), brief["total_seconds"])
        self.assertAlmostEqual(brief["gulf_gold_multiple_usd_terms"], 3441.58 / 1799.42, places=6)


class DescriptionTests(unittest.TestCase):
    def test_placeholders_and_disclosure(self):
        text = description.render_description("ملخص", episode.chapters())
        self.assertEqual(sorted(description.unresolved_placeholders(text)), sorted(description.AFFILIATE_SLOTS))
        self.assertIn(description.DISCLOSURE_AR, text)
        self.assertIn("المصادر:", text)
        self.assertIn("https://fred.stlouisfed.org/data/FPCPITOTLZGEGY", text)

    def test_strict_mode_refuses_unresolved(self):
        with self.assertRaises(ValueError):
            description.render_description("x", [], strict=True)
        links = {s: f"https://example.com/{s}" for s in description.AFFILIATE_SLOTS}
        text = description.render_description("x", [], links, strict=True)
        self.assertEqual(description.unresolved_placeholders(text), [])


class ChartTests(unittest.TestCase):
    def test_bar_and_line_charts_render_non_blank_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            p1 = charts.bar_chart(Path(tmp) / "b.png", "عنوان", ["أ", "ب"], [1, 2], size=(640, 360))
            p2 = charts.line_chart(Path(tmp) / "l.png", "عنوان", ["2021", "2022", "2023"], [1, 3, 2], size=(640, 360))
            for p in (p1, p2):
                img = Image.open(p)
                self.assertEqual(img.size, (640, 360))
                self.assertGreater(len(set(img.convert("RGB").resize((64, 36)).getdata())), 20)

    def test_chart_rejects_missing_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                charts.bar_chart(Path(tmp) / "x.png", "t", ["a", "b"], [1, None])

    def test_scenario_charts_skip_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = calculator.run_scenarios(100000, 2021, 2025)
            paths = charts.scenario_charts(res, tmp, 2021, 2025)
            self.assertEqual(len(paths), 2)
            self.assertTrue(all(Path(p).is_file() for p in paths))


if __name__ == "__main__":
    unittest.main()
