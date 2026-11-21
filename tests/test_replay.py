"""End-to-end replay of two real events with the documents the sources published.

* EIA Weekly Petroleum Status Report, 18/11/2026 10:30 ET (consensus 0.4M, actual +3.38M).
* DOL weekly claims, 19/11/2026 08:30 ET (consensus 198K, actual 203K).

Only the network is replaced: each URL returns the stored official document, and
release documents are "published" 20 seconds after the scheduled time. Calendar
parsing, consensus, analysis, Telegram formatting/deduplication, journal and price
evaluation run unchanged.
"""
import json
import unittest
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import requests

from oracle import storage
from oracle.calendar import parse_eia_schedule, scheduled_weekly_claims
from oracle.journal import stats
from oracle.main import run
from tests.fixtures import raw, text

EIA = datetime(2026, 11, 18, 15, 30, tzinfo=timezone.utc)
CLAIMS = datetime(2026, 11, 19, 13, 30, tzinfo=timezone.utc)


class Network:
    def __init__(self, clock):
        self.clock = clock
        self.calls = []
        self.yahoo = json.loads(text("yahoo_1m_2026-11-18_19.json"))

    def get(self, url, timeout=10, params=None, **_):
        self.calls.append(url)
        now = self.clock()
        if "faireconomy" in url:
            return Mock(json=lambda: json.loads(text("forexfactory_week_2026-11-16.json")))
        if url.endswith("wpsr/table4.csv"):
            if now < EIA + timedelta(seconds=20):
                raise requests.HTTPError("not yet published")
            return Mock(text=text("eia_table4_2026-11-18.csv"))
        if url.endswith("/ui/data.pdf"):
            if now < CLAIMS + timedelta(seconds=20):
                raise requests.ConnectionError("not yet published")
            return Mock(content=raw("dol_claims_2026-11-19.pdf"))
        if "finance.yahoo.com" in url:
            payload = self.yahoo[url.rsplit("/", 1)[1]]
            return Mock(json=lambda: payload)
        raise requests.ConnectionError(url)


class ReplayTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(patch("oracle.storage.DB_PATH", f"{directory}/journal.sqlite3"))
        start = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
        events = parse_eia_schedule(text("eia_schedule.txt"), start, days=1) + scheduled_weekly_claims(start, 2, set())
        self.assertEqual([e["date_utc"] for e in events], [EIA.isoformat(), CLAIMS.isoformat()])
        self.enterContext(patch("oracle.main.fetch_economic_calendar", return_value=events))
        self.clock = [datetime(2026, 11, 18, 14, 50, tzinfo=timezone.utc)]
        self.network = Network(lambda: self.clock[0])
        self.enterContext(patch("oracle.net.get", side_effect=self.network.get))
        self.telegram = self.enterContext(patch("oracle.main.send_telegram", return_value="delivered"))

    def advance(self, seconds):
        self.clock[0] += timedelta(seconds=seconds)

    def test_full_week_replay(self):
        # A scheduled run starting 40 minutes early stays alive through publication.
        run(loop_minutes=80, clock=lambda: self.clock[0], sleep=self.advance)
        messages = [call.args[0] for call in self.telegram.call_args_list]
        self.assertEqual(len(messages), 2)
        self.assertIn("🎯 Stato: PREVISIONE", messages[0])
        self.assertIn("Previsione non disponibile", messages[0])
        self.assertIn("Consenso: crude_mb 0.4", messages[0])
        self.assertIn("🎯 Stato: DATO PUBBLICATO", messages[1])
        self.assertIn("🥇 WTI — SHORT\n🥈 BRENT — SHORT", messages[1])
        self.assertIn("+3.38 mln barili contro consenso +0.40", messages[1])
        self.assertIn("🕒 Pubblicazione: 16:30 Italia (18/11/2026)", messages[1])

        # Next morning: claims, then a later run records the prices of both signals.
        self.clock[0] = datetime(2026, 11, 19, 12, 55, tzinfo=timezone.utc)
        run(loop_minutes=80, clock=lambda: self.clock[0], sleep=self.advance)
        self.clock[0] = CLAIMS + timedelta(minutes=70)
        run(clock=lambda: self.clock[0], sleep=self.advance)
        self.clock[0] = CLAIMS + timedelta(hours=3)
        run(clock=lambda: self.clock[0], sleep=self.advance)

        messages = [call.args[0] for call in self.telegram.call_args_list]
        self.assertEqual(len(messages), 4)
        self.assertIn("📅 Evento: Richieste di disoccupazione USA", messages[3])
        self.assertIn("🥇 GOLD — LONG\n🥈 COPPER — SHORT", messages[3])
        self.assertIn("Richieste 203.000 contro consenso 198.000", messages[3])
        self.assertIn("🔗 Fonte: https://www.dol.gov/ui/data.pdf", messages[3])
        self.assertTrue(all(message.rstrip().endswith("PAPER ONLY") for message in messages))

        # Each source is asked only when needed: one ForexFactory download per hour at most.
        self.assertLessEqual(sum("faireconomy" in url for url in self.network.calls), 3)

        journal = {entry["event_id"]: entry for entry in storage.journal_entries()}
        eia = journal["EIA:WPSR:2026-11-18"]["published"]
        claims = journal["DOL:CLAIMS:2026-11-19"]["published"]
        self.assertEqual((eia["delay_s"], claims["delay_s"]), (30, 30))
        self.assertEqual(eia["data"]["actual"]["crude_mb"], 3.38)
        self.assertEqual(claims["data"]["consensus"], {"claims": 198000})
        self.assertEqual(claims["data"]["revised"], {"claims": 202000})
        for entry in (eia, claims):
            for asset, row in entry["evaluation"].items():
                self.assertEqual(set(row["prices"]), {"signal", "5m", "15m", "30m", "60m"})
                self.assertIn(row["outcome"], {"CORRETTA", "ERRATA", "INCERTA"})
        # Real market path: gold fell after the claims release, so the LONG call is wrong.
        self.assertEqual(claims["evaluation"]["Gold"]["outcome"], "ERRATA")

        summary = stats(storage.journal_entries(), CLAIMS + timedelta(hours=3))
        self.assertEqual(summary["eventi_conclusi"], 2)
        self.assertEqual(summary["copertura_dato_pubblicato_pct"], 100.0)
        self.assertEqual(summary["ritardo_medio_notifica_s"], 30.0)
        self.assertEqual(summary["dopo_dato"]["valutate"], 4)

    def test_unavailable_source_produces_no_invented_result(self):
        with patch("oracle.net.get", side_effect=requests.ConnectionError("down")):
            self.clock[0] = EIA - timedelta(minutes=30)
            run(clock=lambda: self.clock[0], sleep=self.advance)
            for minutes in (0, 1, 5, 30, 119):
                self.clock[0] = EIA + timedelta(minutes=minutes)
                run(clock=lambda: self.clock[0], sleep=self.advance)
        messages = [call.args[0] for call in self.telegram.call_args_list]
        self.assertEqual(len(messages), 1)  # only the preview, which states that no forecast exists
        self.assertIn("Previsione non disponibile", messages[0])
        self.assertIn("Consenso: n/d", messages[0])
        entry = storage.journal_entries()[0]
        self.assertNotIn("published", entry)
        self.assertEqual(stats([entry], EIA + timedelta(hours=3))["copertura_dato_pubblicato_pct"], 0.0)
