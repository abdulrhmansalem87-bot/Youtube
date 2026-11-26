import tempfile
import unittest
from pathlib import Path

from PIL import Image

from wealthradar_audit import calculator, charts, data, description, episode, receipts


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

    def test_certificate_rollover_uses_sourced_january_rates(self):
        res = {r.key: r for r in calculator.run_scenarios(100000, 2021, 2025)}
        self.assertEqual(res["certificate"].status, "ok")
        self.assertAlmostEqual(res["certificate"].multiple, 1.11 * 1.25 * 1.27 * 1.30, places=9)
        self.assertAlmostEqual(res["certificate"].real_return_pct, 2.7, delta=0.1)
        self.assertTrue(calculator.publishable(list(res.values()))[0])

    def test_certificate_missing_years_block(self):
        res = {r.key: r for r in calculator.run_scenarios(100000, 2021, 2025, {2022: 11.0})}
        self.assertEqual(res["certificate"].status, "blocked")
        self.assertFalse(calculator.publishable(list(res.values()))[0])

    def test_custom_rates_are_never_publishable(self):
        rates = {2022: 10.0, 2023: 10.0}
        res = {r.key: r for r in calculator.run_scenarios(100000, 2021, 2023, rates)}
        self.assertAlmostEqual(res["certificate"].end_value, 121000, places=4)
        self.assertFalse(res["certificate"].verified)
        self.assertFalse(calculator.publishable(list(res.values()))[0])

    def test_every_certificate_rate_has_its_own_source(self):
        by_year = data.CERTIFICATE_RATE["by_year"]
        for y, rate in data.CERTIFICATE_RATE["values"].items():
            self.assertEqual(by_year[y]["rate"], rate)
            self.assertTrue(by_year[y]["url"].startswith("https://"))

    def test_gulf_view_pegged_gold_and_real_multiples(self):
        g = calculator.gulf_view(2021, 2025)
        self.assertAlmostEqual(g["gold_multiple_usd_terms"], 3441.58 / 1799.42, places=6)
        sau = g["countries"]["SAU"]
        self.assertAlmostEqual(sau["gold_real_multiple"], g["gold_multiple_usd_terms"] / sau["cumulative_inflation_multiple"], places=9)
        self.assertLess(sau["cumulative_inflation_multiple"], 1.2)

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
    def test_structure_is_9_to_11_minutes_with_and_without_receipt(self):
        for ok in (True, False):
            episode.validate_structure(ok)
            self.assertGreaterEqual(episode.total_seconds(ok), 540)
            self.assertLessEqual(episode.total_seconds(ok), 660)

    def test_required_segments_present(self):
        keys = [s[0] for s in episode.SEGMENTS]
        for k in ("hook", "what_happened", "why", "winners_egypt", "winners_gulf", "scenarios", "receipt", "takeaways"):
            self.assertIn(k, keys)

    def test_brief_is_publishable_and_drops_receipt_when_ledger_empty(self):
        brief = episode.build_brief(100000, 2021, 2025, ledger={"predictions": []})
        self.assertTrue(brief["publishable"], brief["blockers"])
        self.assertEqual(brief["receipt"]["status"], "empty")
        self.assertNotIn("receipt", [s["key"] for s in brief["segments"]])
        self.assertEqual(brief["total_seconds"], 540)
        self.assertEqual(sum(s["seconds"] for s in brief["segments"]), brief["total_seconds"])
        self.assertEqual(brief["chapters"][0], ("0:00", "الخطاف"))

    def test_brief_carries_method_and_on_air_points(self):
        brief = episode.build_brief(100000, 2021, 2025, ledger={"predictions": []})
        self.assertIn(calculator.CERTIFICATE_METHOD_AR, brief["on_screen_required"])
        self.assertTrue(any("18%" in p for p in brief["on_air_points"]))
        self.assertTrue(brief["certificate_gaps"])
        self.assertAlmostEqual(brief["gulf"]["gold_multiple_usd_terms"], 3441.58 / 1799.42, places=6)

    def test_receipt_segment_empty_by_default_ledger(self):
        self.assertEqual(receipts.receipt_segment({"predictions": []})["status"], "empty")
        self.assertEqual(receipts.receipt_segment({"predictions": [{"id": "x"}]})["status"], "empty")


class DescriptionTests(unittest.TestCase):
    def test_placeholders_and_disclosure(self):
        text = description.render_description("ملخص", episode.chapters())
        self.assertEqual(sorted(description.unresolved_placeholders(text)), sorted(description.AFFILIATE_SLOTS))
        self.assertIn("https://www.almasryalyoum.com/news/details/2784538", text)
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
            res = calculator.run_scenarios(100000, 2021, 2025, {2022: 11.0})
            self.assertEqual([r.key for r in res if r.status != "ok"], ["certificate"])
            paths = charts.scenario_charts(res, tmp, 2021, 2025)
            self.assertEqual(len(paths), 2)
            self.assertTrue(all(Path(p).is_file() for p in paths))


if __name__ == "__main__":
    unittest.main()
