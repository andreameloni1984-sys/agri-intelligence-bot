import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from oracle import storage


class JournalTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.path = Path(directory) / "journal.sqlite3"
        self.enterContext(patch("oracle.storage.DB_PATH", str(self.path)))
        self.now = datetime.now(timezone.utc)

    def test_concurrent_delivery_claim_is_unique(self):
        storage.save("ready", True)
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: storage.record("event", "published", "abc", self.now, {}), range(6)))
        self.assertEqual(results.count(True), 1)

    def test_definite_rejection_retries_but_unknown_delivery_does_not(self):
        key = ("event", "published", "abc")
        self.assertTrue(storage.record(*key, self.now, {}))
        storage.finish(*key, "retry")
        self.assertTrue(storage.record(*key, self.now, {}))
        storage.finish(*key, "unknown")
        self.assertFalse(storage.record(*key, self.now, {}))

    def test_earlier_journal_database_is_preserved(self):
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE runs (id INTEGER PRIMARY KEY)")
            db.execute("INSERT INTO runs VALUES (1)")
        storage.save("official_calendar", {"events": []})
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT id FROM runs").fetchall(), [(1,)])
