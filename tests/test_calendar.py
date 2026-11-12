import unittest
from datetime import datetime, timezone
from oracle.calendar import (
    parse_bls_calendar, parse_eia_schedule, parse_fomc_calendar, parse_wasde_calendar, relevant_events, scheduled_weekly_claims,
)


class CalendarTests(unittest.TestCase):
    def test_bls_parser_extracts_high_impact_release_and_utc_time(self):
        html = """
        <div>Tuesday, November 10, 2026 08:30 AM Consumer Price Index for October 2026</div>
        <div>Tuesday, November 10, 2026 08:30 AM Real Earnings for October 2026</div>
        <div>Friday, November 13, 2026 08:30 AM Producer Price Index for October 2026</div>
        NOTE: All times on calendar are Eastern Time.
        """
        now = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
        events = parse_bls_calendar(html, now=now)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["event"], "Consumer Price Index for October 2026")
        self.assertEqual(events[0]["date_utc"], "2026-11-10T13:30:00+00:00")

    def test_bls_ignores_unselected_events(self):
        html = "<div>Tuesday, November 10, 2026 10:00 AM State Employment and Unemployment</div>"
        now = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(parse_bls_calendar(html, now=now), [])

    def test_weekly_claims_activates_gold_at_1400_italy(self):
        from oracle.config import UNIVERSE
        now = datetime(2026, 11, 12, 13, 0, tzinfo=timezone.utc)
        events = scheduled_weekly_claims(now=now, days=1)
        self.assertEqual(events[0]["date_utc"], "2026-11-12T13:30:00+00:00")
        gold = next(item for item in UNIVERSE if item.name == "Gold")
        copper = next(item for item in UNIVERSE if item.name == "Copper")
        self.assertEqual(relevant_events(gold, events, now)[0]["minutes_to_event"], 30)
        self.assertEqual(relevant_events(copper, events, now), [])

    def test_eia_generates_next_wednesday_in_utc(self):
        now = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
        events = parse_eia_schedule("<html></html>", now=now, days=5)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event"], "Weekly Petroleum Status Report")
        self.assertEqual(events[0]["date_utc"], "2026-11-11T15:30:00+00:00")

    def test_eia_holiday_shift_is_found_on_thursday_release_day(self):
        html = """
        <table><tr><td>November 6, 2026</td><td>November 12, 2026</td>
        <td>Thursday</td><td>12:00 p.m.</td><td>Veterans Day</td></tr></table>
        """
        now = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)
        events = parse_eia_schedule(html, now=now, days=2)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["date_utc"], "2026-11-12T17:00:00+00:00")

    def test_fomc_parser_uses_second_meeting_day(self):
        html = "<h2>2026 FOMC Meetings</h2><p>November 27-28</p><p>December 8-9*</p><h2>2025 FOMC Meetings</h2>"
        now = datetime(2026, 11, 1, tzinfo=timezone.utc)
        events = parse_fomc_calendar(html, now=now, days=60)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["date_utc"], "2026-11-28T19:00:00+00:00")

    def test_wasde_parser_reads_official_annual_dates(self):
        html = "<h3>2026 WASDE Release Dates (12:00pm ET)</h3> In 2026 the WASDE report will be released on Jan. 12, Feb. 10, Nov. 10, and Dec. 10."
        now = datetime(2026, 11, 8, tzinfo=timezone.utc)
        events = parse_wasde_calendar(html, now=now, days=60)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["event"], "USDA WASDE supply and demand report")
        self.assertEqual(events[0]["date_utc"], "2026-11-10T17:00:00+00:00")


    def test_event_mapping_targets_relevant_assets_and_ignores_unrelated_assets(self):
        from oracle.config import UNIVERSE
        now = datetime(2026, 11, 10, 16, 0, tzinfo=timezone.utc)
        events = [
            {"event": "USDA WASDE supply and demand report", "source": "USDA",
             "date_utc": "2026-11-10T17:00:00+00:00", "url": "https://usda.gov"},
            {"event": "Weekly Petroleum Status Report", "source": "EIA",
             "date_utc": "2026-11-11T15:30:00+00:00", "url": "https://eia.gov"},
        ]
        wheat = next(item for item in UNIVERSE if item.name == "Wheat")
        wti = next(item for item in UNIVERSE if item.name == "WTI")
        gold = next(item for item in UNIVERSE if item.name == "Gold")
        self.assertEqual(relevant_events(wheat, events, now)[0]["phase"], "IN ARRIVO")
        self.assertEqual(relevant_events(wti, events, now)[0]["source"], "EIA")
        self.assertEqual(relevant_events(gold, events, now), [])


if __name__ == "__main__":
    unittest.main()
