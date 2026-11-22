import json
import unittest
from unittest.mock import patch
from datetime import date, datetime, timedelta

from oracle.consensus import ff_context, parse_ff_value, parse_nowcast, reference_month
from oracle.news import parse_context
from tests.fixtures import text


class ContextTests(unittest.TestCase):
    event = {"id": "EIA:WPSR:2026-11-18", "event": "Weekly Petroleum Status Report",
             "date_utc": "2026-11-18T15:30:00+00:00"}
    stamp = datetime.fromisoformat(event["date_utc"])

    def test_feed_separates_scenario_consensus_and_ignores_untrusted_data(self):
        row = {"event_id": self.event["id"], "source_url": "https://example.com/poll",
               "as_of": "2026-11-18T14:00:00+00:00",
               "consensus": {"crude_mb": -1.5, "gasoline_mb": "0"},
               "scenario": {"crude_mb": -4.5}, "actual": {"crude_mb": 10}}
        context = parse_context(row, self.event, self.stamp - timedelta(minutes=30))
        self.assertEqual(context.consensus, {"crude_mb": -1.5})
        self.assertEqual(context.scenario, {"crude_mb": -4.5})
        self.assertEqual(context.scenario_source, "example.com")

    def test_feed_rejects_forecast_after_release_and_before_its_timestamp(self):
        row = {"event_id": self.event["id"], "source_url": "https://example.com/poll",
               "as_of": "2026-11-18T15:31:00+00:00", "consensus": {"crude_mb": -1.5}}
        self.assertFalse(parse_context(row, self.event, self.stamp + timedelta(minutes=4)).consensus)
        row["as_of"] = "2026-11-18T15:25:00+00:00"
        self.assertFalse(parse_context(row, self.event, self.stamp - timedelta(minutes=30)).consensus)


class ForexFactoryTests(unittest.TestCase):
    rows = json.loads(text("forexfactory_week_2026-11-16.json"))

    def test_values_and_units(self):
        self.assertEqual(parse_ff_value("198K"), 198000)
        self.assertEqual(parse_ff_value("0.4M"), 0.4)
        self.assertEqual(parse_ff_value("-0.1%"), -0.1)
        self.assertIsNone(parse_ff_value(""))
        self.assertIsNone(parse_ff_value("160.7B"))

    def test_real_week_gives_claims_and_crude_consensus_at_exact_time(self):
        claims = ff_context(self.rows, "claims", datetime.fromisoformat("2026-11-19T13:30:00+00:00"))
        self.assertEqual((claims.consensus, claims.previous), ({"claims": 198000}, {"claims": 200000}))
        crude = ff_context(self.rows, "eia", datetime.fromisoformat("2026-11-18T15:30:00+00:00"))
        self.assertEqual((crude.consensus, crude.previous), ({"crude_mb": 0.4}, {"crude_mb": 4.7}))
        self.assertFalse(ff_context(self.rows, "claims", datetime.fromisoformat("2026-11-19T14:30:00+00:00")).consensus)


class NowcastTests(unittest.TestCase):
    charts = json.loads(text("cleveland_nowcast_2026-09_10.json"))

    def test_reference_month_from_official_titles(self):
        self.assertEqual(reference_month("Consumer Price Index for October 2026"), (2026, 10))
        self.assertEqual(reference_month("Personal Income and Outlays, September 2026"), (2026, 9))

    def test_uses_last_estimate_published_before_release_day(self):
        # PCE for September 2026 was released on 2026-10-29.
        self.assertEqual(parse_nowcast(self.charts, "pce", (2026, 9), date(2026, 10, 29)),
                         {"headline_mom_pct": 0.5, "core_mom_pct": 0.3})
        # CPI for October 2026 was released on 2026-11-10.
        cpi = parse_nowcast(self.charts, "cpi", (2026, 10), date(2026, 11, 10))
        self.assertEqual(set(cpi), {"headline_mom_pct", "core_mom_pct"})
        self.assertEqual(parse_nowcast(self.charts, "cpi", (2026, 12), date(2027, 1, 10)), {})


class UserAgentTests(unittest.TestCase):
    def test_contact_only_for_bls_and_dol(self):
        from oracle import net
        with patch.object(net, "CONTACT_USER_AGENT", "Stella-Rossa/1.0 (contact: x@y.z)"):
            self.assertIn("contact", net.user_agent_for("https://www.bls.gov/schedule/2026/home.htm"))
            self.assertIn("contact", net.user_agent_for("https://www.dol.gov/ui/data.pdf"))
            self.assertNotIn("contact", net.user_agent_for("https://nfs.faireconomy.media/ff_calendar_thisweek.json"))
            self.assertNotIn("contact", net.user_agent_for("https://query1.finance.yahoo.com/v8/finance/chart/GC=F"))
            self.assertNotIn("contact", net.user_agent_for("https://evilbls.gov.example.com/"))
