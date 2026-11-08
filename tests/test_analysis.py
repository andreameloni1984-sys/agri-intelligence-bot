import unittest
from datetime import datetime, timezone, timedelta
from oracle.analysis import build_signal, score_news
from oracle.config import UNIVERSE
from oracle.models import NewsItem, Quote

class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.gold = next(x for x in UNIVERSE if x.name == "Gold")
        self.now = datetime.now(timezone.utc)

    def item(self, title):
        return NewsItem(title, "https://example.test/" + str(abs(hash(title))), self.now, "test")

    def test_no_quote_never_emits_signal(self):
        signal, status = build_signal(self.gold, None, [])
        self.assertIsNone(signal)
        self.assertEqual(status, "NO_QUOTE")

    def test_stale_quote_blocks_signal(self):
        old = Quote("GC=F", 2010, 2000, 10, self.now - timedelta(hours=3),
                    "test", 2005, 1990, 60, 2008, 1980)
        signal, status = build_signal(self.gold, old, [])
        self.assertIsNone(signal)
        self.assertTrue(status.startswith("STALE_QUOTE_"))

    def test_generic_headline_does_not_create_direction(self):
        score, matched = score_news(self.gold, [self.item("Gold market update: sanctions announced")])
        self.assertEqual(score, 0)
        self.assertEqual(matched, [])

    def test_technical_long_does_not_require_news(self):
        quote = Quote("GC=F", 2010, 2005, 10, self.now, "test", 2005, 1990, 60, 2008, 1980)
        signal, status = build_signal(self.gold, quote, [])
        self.assertEqual(status, "SIGNAL")
        self.assertEqual(signal.direction, "LONG")
        self.assertEqual(signal.news_score, 0)
        self.assertLess(signal.stop_loss, signal.reference_price)
        self.assertGreater(signal.target_1, signal.reference_price)
        self.assertGreater(signal.target_2, signal.target_1)

    def test_technical_short_does_not_require_news(self):
        quote = Quote("GC=F", 1990, 1995, 10, self.now, "test", 2000, 2010, 40, 2015, 1992)
        signal, status = build_signal(self.gold, quote, [])
        self.assertEqual(status, "SIGNAL")
        self.assertEqual(signal.direction, "SHORT")
        self.assertGreater(signal.stop_loss, signal.reference_price)
        self.assertLess(signal.target_1, signal.reference_price)
        self.assertLess(signal.target_2, signal.target_1)

    def test_news_contradiction_blocks_setup(self):
        quote = Quote("GC=F", 2010, 2005, 10, self.now, "test", 2005, 1990, 60, 2008, 1980)
        news = [self.item("Gold real yields rise and dollar strengthens")]
        signal, status = build_signal(self.gold, quote, news)
        self.assertIsNone(signal)
        self.assertEqual(status, "NEWS_CONTRADICTS_TECHNICAL")

    def test_incomplete_technical_data_does_not_emit_signal(self):
        quote = Quote("GC=F", 2010, 2005, 10, self.now)
        signal, status = build_signal(self.gold, quote, [])
        self.assertIsNone(signal)
        self.assertEqual(status, "TECHNICAL_SETUP_NOT_CONFIRMED")

    def test_invalid_atr_blocks_signal(self):
        quote = Quote("GC=F", 2010, 2005, 0, self.now, "test", 2005, 1990, 60, 2008, 1980)
        signal, status = build_signal(self.gold, quote, [])
        self.assertIsNone(signal)
        self.assertEqual(status, "INVALID_MARKET_DATA")

    def test_asset_specific_catalysts_are_mapped(self):
        copper = next(x for x in UNIVERSE if x.name == "Copper")
        soybeans = next(x for x in UNIVERSE if x.name == "Soybeans")
        wti = next(x for x in UNIVERSE if x.name == "WTI")
        score, matched = score_news(copper, [self.item("China announces stimulus for manufacturing")])
        self.assertEqual(score, 2)
        self.assertEqual(len(matched), 1)
        score, _ = score_news(soybeans, [self.item("China import demand for soybeans rises")])
        self.assertEqual(score, 2)
        score, _ = score_news(wti, [self.item("Oil supply disruption threatens exports")])
        self.assertEqual(score, 2)

    def test_negative_supply_and_harvest_catalysts_are_mapped(self):
        wheat = next(x for x in UNIVERSE if x.name == "Wheat")
        score, matched = score_news(wheat, [self.item("Bumper wheat crop expected this season")])
        self.assertEqual(score, -2)
        self.assertEqual(len(matched), 1)

    def test_explicitly_negated_catalyst_is_ignored(self):
        wti = next(x for x in UNIVERSE if x.name == "WTI")
        score, matched = score_news(wti, [self.item("OPEC says no production cut is planned")])
        self.assertEqual(score, 0)
        self.assertEqual(matched, [])

if __name__ == "__main__":
    unittest.main()
