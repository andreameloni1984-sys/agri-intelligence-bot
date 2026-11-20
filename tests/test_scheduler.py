import unittest
from datetime import datetime, timedelta
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from oracle import storage
from oracle.main import main
from oracle.models import Context, Release
from oracle.notify import send_telegram


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(patch("oracle.storage.DB_PATH", f"{directory}/journal.sqlite3"))
        self.event = {"id": "EIA:WPSR:2026-11-18", "event": "Weekly Petroleum Status Report",
                      "date_utc": "2026-11-18T15:30:00+00:00", "url": "https://www.eia.gov/schedule",
                      "source": "EIA"}
        self.stamp = datetime.fromisoformat(self.event["date_utc"])
        self.calendar = self.enterContext(patch("oracle.main.fetch_economic_calendar", return_value=[self.event]))
        self.context = self.enterContext(patch("oracle.main.fetch_context", return_value=Context(
            consensus={"crude_mb": 1}, scenario={"crude_mb": -1})))
        self.release = self.enterContext(patch("oracle.main.fetch_release"))
        self.telegram = self.enterContext(patch("oracle.main.send_telegram", return_value="delivered"))

    def test_idle_only_loads_calendar_and_sleeps_until_preliminary_window(self):
        self.assertEqual(main(self.stamp - timedelta(minutes=45)), 900)
        self.calendar.assert_called_once()
        self.context.assert_not_called()
        self.release.assert_not_called()
        self.telegram.assert_not_called()

    def test_preliminary_and_published_are_distinct_and_updates_deduplicate(self):
        self.release.return_value = None
        main(self.stamp - timedelta(minutes=30))
        main(self.stamp - timedelta(minutes=20))
        self.assertEqual(self.telegram.call_count, 1)
        preview = self.telegram.call_args.args[0]
        self.assertIn("PREVISIONE PRELIMINARE", preview)
        self.assertIn("1. WTI — 🟢 LONG\n2. BRENT — 🟢 LONG", preview)
        self.assertIn("18/11/2026 16:30 CET", preview)

        self.assertEqual(main(self.stamp), 30)
        self.assertEqual(self.telegram.call_count, 1)
        self.release.return_value = Release({"crude_mb": 3.38}, "https://ir.eia.gov/wpsr/table4.csv")
        main(self.stamp + timedelta(seconds=30))
        published = self.telegram.call_args.args[0]
        self.assertIn("ANALISI DEL DATO PUBBLICATO", published)
        self.assertIn("1. WTI — 🔴 SHORT\n2. BRENT — 🔴 SHORT", published)
        self.assertIn("🔗 Fonte: https://ir.eia.gov/wpsr/table4.csv", published)
        main(self.stamp + timedelta(minutes=11))
        self.assertEqual(self.telegram.call_count, 2)
        self.release.return_value.actual["crude_mb"] = -2
        main(self.stamp + timedelta(minutes=21))
        self.assertIn("AGGIORNAMENTO", self.telegram.call_args.args[0])
        main(self.stamp + timedelta(minutes=32))
        self.assertEqual(self.telegram.call_count, 3)

    def test_publication_with_no_consensus_reports_unknown_instead_of_signal(self):
        self.context.return_value = Context()
        self.release.return_value = Release({"crude_mb": 3.38}, "https://eia.gov")
        main(self.stamp)
        self.assertIn("NON DETERMINABILE", self.telegram.call_args.args[0])

    def test_dry_run_does_not_call_telegram(self):
        self.release.return_value = Release({"crude_mb": 3.38}, "https://eia.gov")
        main(self.stamp, dry_run=True)
        self.telegram.assert_not_called()
        self.assertIsNotNone(storage.load(f"outcome:{self.event['id']}:published"))

    def test_telegram_transport_only_calls_send_message(self):
        with patch("oracle.notify.TELEGRAM_BOT_TOKEN", "test"), patch("oracle.notify.TELEGRAM_CHAT_ID", "chat"):
            with patch("oracle.notify.requests.post", return_value=Mock(status_code=200, json=lambda: {"ok": True})) as post:
                self.assertEqual(send_telegram("PAPER ONLY"), "delivered")
        self.assertEqual(post.call_args.args[0], "https://api.telegram.org/bottest/sendMessage")
        self.assertEqual(post.call_args.kwargs["json"]["text"], "PAPER ONLY")
