import os
import tempfile
import unittest
from datetime import datetime, timezone
from oracle.models import Signal
from oracle import storage


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = storage.DB_PATH
        storage.DB_PATH = os.path.join(self.tmp.name, "test.sqlite3")

    def tearDown(self):
        storage.DB_PATH = self.old_path
        self.tmp.cleanup()

    def signal_at(self, stamp, direction="LONG", news_urls=None):
        return Signal("Gold", "GC=F", direction, 70, 0, 0.2, 2000, 1985, 2022.5, 2037.5,
                      "test", news_urls or [], stamp)

    def test_same_direction_is_deduplicated_within_hour_even_if_news_changes(self):
        first = self.signal_at(datetime(2026, 11, 8, 10, 5, tzinfo=timezone.utc),
                               news_urls=["https://example.test/a"])
        repeated = self.signal_at(datetime(2026, 11, 8, 10, 55, tzinfo=timezone.utc),
                                  news_urls=["https://example.test/b"])
        self.assertTrue(storage.save_result(first, "Gold", "GC=F", "SIGNAL"))
        self.assertFalse(storage.save_result(repeated, "Gold", "GC=F", "SIGNAL"))

    def test_same_direction_can_alert_again_in_next_hour(self):
        first = self.signal_at(datetime(2026, 11, 8, 10, 55, tzinfo=timezone.utc))
        next_hour = self.signal_at(datetime(2026, 11, 8, 11, 1, tzinfo=timezone.utc))
        self.assertTrue(storage.save_result(first, "Gold", "GC=F", "SIGNAL"))
        self.assertTrue(storage.save_result(next_hour, "Gold", "GC=F", "SIGNAL"))

    def test_failed_telegram_delivery_can_be_retried(self):
        signal = self.signal_at(datetime(2026, 11, 8, 10, 5, tzinfo=timezone.utc))
        self.assertTrue(storage.save_result(signal, "Gold", "GC=F", "SIGNAL"))
        storage.delete_signal(signal)
        self.assertTrue(storage.save_result(signal, "Gold", "GC=F", "SIGNAL"))


if __name__ == "__main__":
    unittest.main()
