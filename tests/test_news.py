import unittest
from datetime import datetime, timedelta

from oracle.news import _reuters_crude_consensus, parse_context, parse_te_consensus


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

    def test_feed_rejects_forecast_after_release_and_before_its_timestamp(self):
        row = {"event_id": self.event["id"], "source_url": "https://example.com/poll",
               "as_of": "2026-11-18T15:31:00+00:00", "consensus": {"crude_mb": -1.5}}
        self.assertFalse(parse_context(row, self.event, self.stamp + timedelta(minutes=4)).consensus)
        row["as_of"] = "2026-11-18T15:25:00+00:00"
        self.assertFalse(parse_context(row, self.event, self.stamp - timedelta(minutes=30)).consensus)

    def test_provider_requires_exact_event_time_and_unit(self):
        rows = [{"Country": "United States", "Event": "EIA Crude Oil Stocks Change",
                 "Date": "2026-11-18T15:30:00", "Forecast": "-1.5M", "Previous": "4.657M", "Actual": "3.38M"},
                {"Country": "United States", "Event": "EIA Crude Oil Stocks Change",
                 "Date": "2026-11-25T15:30:00", "Forecast": "8M"}]
        context = parse_te_consensus(rows, "eia", self.stamp)
        self.assertEqual(context.consensus, {"crude_mb": -1.5})
        self.assertEqual(context.previous, {"crude_mb": 4.657})
        rows[0]["Forecast"] = "15K"
        self.assertFalse(parse_te_consensus(rows, "eia", self.stamp).consensus)

    def test_reuters_poll_is_recognized_without_treating_actual_as_consensus(self):
        self.assertEqual(_reuters_crude_consensus("Reuters poll: U.S. crude stocks seen falling by 1.5 million barrels"), -1.5)
        self.assertIsNone(_reuters_crude_consensus("U.S. crude inventories fell 4 million barrels"))
