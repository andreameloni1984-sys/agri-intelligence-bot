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
        self.assertIsNone(signal); self.assertEqual(status, "NO_QUOTE")
    def test_stale_quote_blocks_signal(self):
        old = Quote("GC=F", 2000, 1990, 10, self.now - timedelta(hours=3))
        signal, status = build_signal(self.gold, old, [self.item("Gold safe haven demand")])
        self.assertIsNone(signal); self.assertTrue(status.startswith("STALE_QUOTE_"))
    def test_generic_headline_does_not_create_direction(self):
        score, matched = score_news(self.gold, [self.item("Gold market update: sanctions announced")])
        self.assertEqual(score, 0); self.assertEqual(matched, [])
    def test_asset_specific_long_requires_price_confirmation(self):
        quote = Quote("GC=F", 2010, 2000, 10, self.now, "test", 2005, 1990, 60, 2008, 1980)
        signal, status = build_signal(self.gold, quote, [self.item("Gold safe haven demand rises amid geopolitical escalation")])
        self.assertEqual(status, "SIGNAL"); self.assertEqual(signal.direction, "LONG")
        self.assertLess(signal.stop_loss, signal.reference_price)
        self.assertGreater(signal.target_1, signal.reference_price)
        self.assertGreater(signal.target_2, signal.target_1)
    def test_asset_specific_short(self):
        quote = Quote("GC=F", 1990, 2000, 10, self.now)
        signal, status = build_signal(self.gold, quote, [self.item("Gold real yields rise and dollar strengthens")])
        self.assertEqual(status, "SIGNAL"); self.assertEqual(signal.direction, "SHORT")
        self.assertGreater(signal.stop_loss, signal.reference_price)
        self.assertLess(signal.target_1, signal.reference_price)
        self.assertLess(signal.target_2, signal.target_1)
    def test_price_mismatch_blocks_signal(self):
        quote = Quote("GC=F", 1990, 2000, 10, self.now)
        signal, status = build_signal(self.gold, quote, [self.item("Gold safe haven demand rises amid geopolitical escalation")])
        self.assertIsNone(signal); self.assertEqual(status, "PRICE_CONFIRMATION_MISSING")

if __name__ == "__main__":
    unittest.main()
