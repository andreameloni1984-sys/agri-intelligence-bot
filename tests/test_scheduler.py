import unittest
from datetime import datetime, timedelta
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from oracle import storage
from oracle.main import main, run
from oracle.models import Context, Release
from oracle.notify import send_telegram


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(patch("oracle.storage.DB_PATH", f"{directory}/journal.sqlite3"))
        self.event = {"id": "EIA:WPSR:2026-11-18", "event": "Weekly Petroleum Status Report",
                      "date_utc": "2026-11-18T15:30:00+00:00", "url": "https://www.eia.gov/petroleum/supply/weekly/",
                      "source": "EIA", "period": "2026-11-13"}
        self.stamp = datetime.fromisoformat(self.event["date_utc"])
        self.calendar = self.enterContext(patch("oracle.main.fetch_economic_calendar", return_value=[self.event]))
        self.context = self.enterContext(patch("oracle.main.fetch_context", return_value=Context(
            consensus={"crude_mb": 1}, scenario={"crude_mb": -1}, scenario_source="feed.example")))
        self.release = self.enterContext(patch("oracle.main.fetch_release", return_value=None))
        self.telegram = self.enterContext(patch("oracle.main.send_telegram", return_value="delivered"))
        self.prices = self.enterContext(patch("oracle.main.evaluate", return_value={}))

    def test_idle_only_loads_calendar_and_sleeps_until_preliminary_window(self):
        self.assertEqual(main(self.stamp - timedelta(minutes=45)), 900)
        self.calendar.assert_called_once()
        self.context.assert_not_called()
        self.release.assert_not_called()
        self.telegram.assert_not_called()

    def test_calendar_is_cached_between_runs(self):
        main(self.stamp - timedelta(hours=5))
        main(self.stamp - timedelta(hours=4, minutes=30))  # one source only: hourly refresh
        self.calendar.assert_called_once()

    def test_one_preview_then_one_published_message_without_repeated_checks(self):
        self.assertEqual(main(self.stamp - timedelta(minutes=30)), 1800)  # next look at publication
        main(self.stamp - timedelta(minutes=10))
        self.assertEqual(self.telegram.call_count, 1)
        self.context.assert_called_once()
        preview = self.telegram.call_args.args[0]
        self.assertIn("🎯 Stato: PREVISIONE", preview)
        self.assertIn("🥇 WTI — LONG\n🥈 BRENT — LONG", preview)
        self.assertIn("🕒 Pubblicazione: 16:30 Italia (18/11/2026)", preview)
        self.assertIn("Stima feed.example", preview)

        self.assertEqual(main(self.stamp), 15)  # release not out yet: fast polling
        self.assertEqual(self.telegram.call_count, 1)
        self.release.return_value = Release({"crude_mb": 3.38}, "https://ir.eia.gov/wpsr/table4.csv")
        main(self.stamp + timedelta(seconds=15))
        published = self.telegram.call_args.args[0]
        self.assertIn("🎯 Stato: DATO PUBBLICATO", published)
        self.assertIn("🥇 WTI — SHORT\n🥈 BRENT — SHORT", published)
        self.assertIn("🔗 Fonte: https://ir.eia.gov/wpsr/table4.csv", published)
        calls = self.release.call_count
        main(self.stamp + timedelta(minutes=11))
        self.assertEqual((self.telegram.call_count, self.release.call_count), (2, calls))
        self.context.assert_called_once()  # consensus fetched once and reused

        entry = storage.journal_entries()[0]
        self.assertEqual(entry["published"]["delay_s"], 15)
        self.assertEqual(entry["published"]["data"]["consensus"], {"crude_mb": 1})
        self.assertEqual(entry["preliminary"]["directions"], {"WTI": "LONG", "Brent": "LONG"})

    def test_preview_without_independent_estimate_says_unavailable(self):
        self.context.return_value = Context(consensus={"crude_mb": 0.4}, previous={"crude_mb": 4.7})
        main(self.stamp - timedelta(minutes=29))
        message = self.telegram.call_args.args[0]
        self.assertIn("Previsione non disponibile", message)
        self.assertIn("NON DETERMINABILE", message)
        self.assertNotIn("— LONG", message)
        self.assertNotIn("— SHORT", message)

    def test_publication_with_no_consensus_reports_unknown_instead_of_signal(self):
        self.context.return_value = Context()
        self.release.return_value = Release({"crude_mb": 3.38}, "https://eia.gov")
        main(self.stamp)
        self.assertIn("NON DETERMINABILE", self.telegram.call_args.args[0])

    def test_late_start_still_processes_event_inside_window(self):
        self.release.return_value = Release({"crude_mb": 3.38}, "https://eia.gov")
        main(self.stamp + timedelta(minutes=95))
        self.assertIn("DATO PUBBLICATO", self.telegram.call_args.args[0])

    def test_telegram_rate_limit_is_retried_but_not_duplicated(self):
        self.release.return_value = Release({"crude_mb": 3.38}, "https://eia.gov")
        self.telegram.return_value = "retry"
        self.assertEqual(main(self.stamp), 30)
        self.telegram.return_value = "delivered"
        main(self.stamp + timedelta(seconds=30))
        main(self.stamp + timedelta(seconds=60))
        self.assertEqual(self.telegram.call_count, 2)

    def test_uncertain_delivery_is_not_resent(self):
        self.release.return_value = Release({"crude_mb": 3.38}, "https://eia.gov")
        self.telegram.return_value = "unknown"
        main(self.stamp)
        storage.save(f"done:{self.event['id']}:published", False)  # even if state were lost
        main(self.stamp + timedelta(seconds=30))
        self.assertEqual(self.telegram.call_count, 1)

    def test_prices_are_recorded_61_minutes_after_signal(self):
        self.release.return_value = Release({"crude_mb": 3.38}, "https://eia.gov")
        main(self.stamp)
        self.prices.return_value = {"WTI": {"outcome": "CORRETTA"}}
        self.assertLessEqual(main(self.stamp + timedelta(minutes=30)), 31 * 60)
        self.prices.assert_not_called()
        main(self.stamp + timedelta(minutes=61))
        self.prices.assert_called_once()
        self.assertEqual(storage.journal_entries()[0]["published"]["evaluation"], {"WTI": {"outcome": "CORRETTA"}})
        main(self.stamp + timedelta(minutes=70))
        self.prices.assert_called_once()

    def test_dry_run_does_not_call_telegram(self):
        self.release.return_value = Release({"crude_mb": 3.38}, "https://eia.gov")
        main(self.stamp, dry_run=True)
        self.telegram.assert_not_called()
        self.assertEqual(storage.journal_entries()[0]["published"]["delivery"], "dry_run")

    def test_loop_mode_waits_through_publication_then_exits(self):
        clock = [self.stamp - timedelta(minutes=40)]
        self.release.side_effect = lambda event: (Release({"crude_mb": 3.38}, "https://eia.gov")
                                                  if clock[0] >= self.stamp + timedelta(seconds=15) else None)

        def sleep(seconds):
            clock[0] += timedelta(seconds=seconds)

        run(loop_minutes=80, clock=lambda: clock[0], sleep=sleep)
        self.assertEqual(self.telegram.call_count, 2)
        self.assertEqual(storage.journal_entries()[0]["published"]["delay_s"], 15)

    def test_telegram_transport_only_calls_send_message(self):
        with patch("oracle.notify.TELEGRAM_BOT_TOKEN", "test"), patch("oracle.notify.TELEGRAM_CHAT_ID", "chat"):
            with patch("oracle.notify.requests.post", return_value=Mock(status_code=200, json=lambda: {"ok": True})) as post:
                self.assertEqual(send_telegram("PAPER ONLY"), "delivered")
            with patch("oracle.notify.requests.post", return_value=Mock(status_code=401)):
                self.assertEqual(send_telegram("PAPER ONLY"), "rejected")
        self.assertEqual(post.call_args.args[0], "https://api.telegram.org/bottest/sendMessage")
        self.assertEqual(post.call_args.kwargs["json"]["text"], "PAPER ONLY")
        self.assertEqual(send_telegram("x"), "unconfigured")
