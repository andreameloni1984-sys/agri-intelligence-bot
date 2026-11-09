import os
import tempfile
import unittest
from unittest.mock import patch

from oracle import storage
from oracle.market import fetch_quotes
from oracle.main import _choose_one, _should_run_cycle


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

    def test_idle_cycle_skips_work_without_candidate(self):
        self.assertFalse(_should_run_cycle(False, None))
        self.assertTrue(_should_run_cycle(True, None))
        self.assertTrue(_should_run_cycle(False, {"symbol": "GC=F"}))

    def test_only_top_ranked_news_candidate_is_selected(self):
        first = {"instrument": "Gold", "news_score": 6}
        second = {"instrument": "Wheat", "news_score": 4}
        self.assertIs(_choose_one([first, second]), first)
        self.assertIsNone(_choose_one([]))

    @patch("oracle.market.yf.download")
    def test_empty_active_universe_skips_market_provider(self, download):
        self.assertEqual(fetch_quotes([]), {})
        download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
