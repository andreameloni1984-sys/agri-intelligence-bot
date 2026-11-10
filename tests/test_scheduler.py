import os
import tempfile
import unittest
from unittest.mock import patch

from oracle import storage
from oracle.market import fetch_quotes


class SchedulerTests(unittest.TestCase):
    def test_scheduler_state_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "state.sqlite3")
            with patch("oracle.storage.DB_PATH", db_path):
                storage.save_scheduler_state("last_news_scan", "2026-11-09T10:00:00+00:00")
                storage.save_scheduler_state("cached_news", [{"title": "Wheat drought"}])
                self.assertEqual(
                    storage.get_scheduler_state("last_news_scan"),
                    "2026-11-09T10:00:00+00:00",
                )
                self.assertEqual(
                    storage.get_scheduler_state("cached_news"),
                    [{"title": "Wheat drought"}],
                )

    @patch("oracle.market.yf.download")
    def test_empty_active_universe_skips_market_provider(self, download):
        self.assertEqual(fetch_quotes([]), {})
        download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
