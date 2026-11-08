import os, tempfile, unittest
from datetime import datetime, timezone
from oracle.models import Signal
from oracle.storage import save_result

class StorageTests(unittest.TestCase):
    def test_same_catalyst_signal_is_deduplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["DB_PATH"] = os.path.join(tmp, "test.sqlite3")
            import oracle.storage as storage
            old_path = storage.DB_PATH; storage.DB_PATH = os.environ["DB_PATH"]
            try:
                now = datetime.now(timezone.utc)
                signal = Signal("Gold", "GC=F", "LONG", 70, 3, 0.2, 2000, 1985, 2022.5, 2037.5,
                                "test", ["https://example.test/catalyst"], now)
                self.assertTrue(save_result(signal, "Gold", "GC=F", "SIGNAL"))
                self.assertFalse(save_result(signal, "Gold", "GC=F", "SIGNAL"))
            finally:
                storage.DB_PATH = old_path

if __name__ == "__main__":
    unittest.main()
