import unittest
from datetime import date

from newsflow import predictions as p


def entry(**kw):
    base = {"id": "a1", "speaker": "فلان", "asset": "usd_egp", "predicted_value": 50,
            "stated_on": "2026-08-01", "due_date": "2026-11-02", "source_url": "https://example.com/x"}
    base.update(kw)
    return base


class PredictionsTests(unittest.TestCase):
    def test_validation(self):
        self.assertEqual(p.validate_entry(entry()), [])
        self.assertTrue(p.validate_entry(entry(source_url="http://x")))
        self.assertTrue(p.validate_entry(entry(asset="btc")))
        self.assertTrue(p.validate_entry(entry(due_date="soon")))

    def test_fetch_and_gold_inversion(self):
        getter = lambda url: {"usd": {"egp": 55.5, "xau": 0.00025}}
        self.assertEqual(p.fetch_actual("usd_egp", "2026-11-02", getter), 55.5)
        self.assertAlmostEqual(p.fetch_actual("gold_usd_oz", "2026-11-02", getter), 4000.0)
        with self.assertRaises(ValueError):
            p.fetch_actual("policy_rate", "2026-11-02", getter)

    def test_mirror_fallback(self):
        calls = []
        def getter(url):
            calls.append(url)
            if len(calls) == 1:
                raise OSError("down")
            return {"usd": {"egp": 50.0}}
        self.assertEqual(p.fetch_actual("usd_egp", "2026-11-02", getter), 50.0)
        self.assertEqual(len(calls), 2)

    def test_evaluate_hit_and_miss(self):
        self.assertEqual(p.evaluate(entry(), 51)["verdict"], "hit")
        miss = p.evaluate(entry(), 55.5)
        self.assertEqual(miss["verdict"], "miss")
        self.assertEqual(miss["diff_pct"], 11.0)

    def test_settle_only_due_and_hit_rate(self):
        ledger = {"predictions": [entry(), entry(id="a2", due_date="2027-01-01"),
                                  entry(id="a3", asset="policy_rate", predicted_value=20)]}
        getter = lambda url: {"usd": {"egp": 55.5}}
        self.assertEqual(p.settle_due(ledger, date(2026, 11, 26), getter), ["a1"])
        self.assertEqual(p.hit_rate(ledger), {"hits": 0, "total": 1, "percent": 0})
        ledger["predictions"][2].update(actual_value=20, actual_source_url="https://cbe.org.eg")
        self.assertEqual(p.settle_due(ledger, date(2026, 11, 26), getter), ["a3"])
        self.assertEqual(p.hit_rate(ledger)["hits"], 1)

    def test_card_and_metadata_are_arabic_neutral_with_sources(self):
        ledger = {"predictions": [entry()]}
        p.settle_due(ledger, date(2026, 11, 26), lambda u: {"usd": {"egp": 55.5}})
        card = p.receipt_card(ledger["predictions"][0], p.hit_rate(ledger))
        self.assertIn("لم يتحقق", card["marker_ar"])
        self.assertIn("0 من 1", card["counter_ar"])
        meta = p.receipt_metadata(ledger)
        self.assertIn("https://example.com/x", meta["description"])
        self.assertIn(p.DISCLAIMER_AR, meta["description"])

    def test_shipped_ledger_is_valid(self):
        self.assertIsInstance(p.load_ledger()["predictions"], list)


if __name__ == "__main__":
    unittest.main()
