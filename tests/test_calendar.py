import unittest
from datetime import datetime, timezone
from oracle.calendar import parse_bls_calendar, parse_eia_schedule

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

    def test_eia_generates_next_wednesday_in_utc(self):
        now = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
        events = parse_eia_schedule("<html></html>", now=now, days=5)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event"], "Weekly Petroleum Status Report")
        self.assertEqual(events[0]["date_utc"], "2026-11-11T15:30:00+00:00")

if __name__ == "__main__":
    unittest.main()
