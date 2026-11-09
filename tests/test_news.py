import sys, types, unittest
from datetime import timezone
from unittest.mock import patch, Mock
fake_feedparser = types.ModuleType("feedparser")
fake_feedparser.parse = lambda payload: None
sys.modules.setdefault("feedparser", fake_feedparser)
from oracle.news import _parse_date, _fetch_feed
from oracle.config import RSS_URLS

class NewsTests(unittest.TestCase):
    def test_reuters_google_news_feed_is_configured(self):
        self.assertTrue(any("news.google.com/rss/search" in url and "site%3Areuters.com" in url for url in RSS_URLS))

    def test_undated_news_is_not_fabricated_as_current(self):
        self.assertIsNone(_parse_date({"title": "undated"}))
    def test_published_timestamp_is_timezone_aware(self):
        entry = {"published_parsed": (2026, 11, 8, 10, 0, 0, 6, 312, 0)}
        parsed = _parse_date(entry)
        self.assertEqual(parsed.tzinfo, timezone.utc); self.assertEqual(parsed.year, 2026)
    @patch("oracle.news.requests.get")
    def test_feed_fetch_has_timeout_and_status_check(self, get):
        response = Mock(); response.content = b"<rss/>"; response.raise_for_status.return_value = None
        get.return_value = response
        _fetch_feed("https://example.test/feed")
        get.assert_called_once(); self.assertEqual(get.call_args.kwargs["timeout"], 12)

if __name__ == "__main__":
    unittest.main()
