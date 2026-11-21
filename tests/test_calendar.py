import unittest
from datetime import date, datetime, timezone
from oracle.calendar import (
    parse_bls_calendar, parse_eia_schedule, parse_fomc_calendar, parse_wasde_calendar, parse_bea_calendar, federal_holiday_conflicts, scheduled_weekly_claims,
    holiday_week_claims,
)
from tests.fixtures import text


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
        events = parse_eia_schedule("<html>The standard release time is Wednesday.</html>", now=now, days=5)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event"], "Weekly Petroleum Status Report")
        self.assertEqual(events[0]["date_utc"], "2026-11-11T15:30:00+00:00")

    def test_eia_holiday_shift_is_found_on_thursday_release_day(self):
        html = """
        The standard release time is Wednesday.
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


    def test_eia_does_not_generate_events_from_an_error_page(self):
        self.assertEqual(parse_eia_schedule("<html>Access Denied</html>"), [])

    def test_dol_omits_holiday_weeks_without_confirmed_exception(self):
        now = datetime(2026, 11, 10, tzinfo=timezone.utc)
        events = scheduled_weekly_claims(now, 20, federal_holiday_conflicts(2026))
        self.assertEqual([event["date_utc"][:10] for event in events], ["2026-11-19"])

    def test_bea_uses_published_utc_time(self):
        ics = """BEGIN:VEVENT
SUMMARY:Personal Income and Outlays\\, October 2026
DTSTART:20261125T133000Z
END:VEVENT"""
        now = datetime(2026, 11, 10, tzinfo=timezone.utc)
        self.assertEqual(parse_bea_calendar(ics, now)[0]["date_utc"], "2026-11-25T13:30:00+00:00")

    def test_partial_dst_overlap_uses_us_release_time(self):
        now = datetime(2026, 3, 7, tzinfo=timezone.utc)
        html = "<p>Wednesday, March 11, 2026 08:30 AM Consumer Price Index for February 2026</p>"
        self.assertEqual(parse_bls_calendar(html, now)[0]["date_utc"], "2026-03-11T12:30:00+00:00")


class OfficialCalendarFixtureTests(unittest.TestCase):
    """Calendar pages downloaded from the agencies on 2026-11-21."""
    now = datetime(2026, 11, 21, 5, 0, tzinfo=timezone.utc)

    def test_bls_2026_schedule(self):
        events = parse_bls_calendar(text("bls_schedule_2026.txt"), self.now)
        self.assertEqual([(e["date_utc"], e["url"]) for e in events], [
            ("2026-12-04T13:30:00+00:00", "https://www.bls.gov/news.release/empsit.nr0.htm"),
            ("2026-12-10T13:30:00+00:00", "https://www.bls.gov/news.release/cpi.nr0.htm"),
            ("2026-12-15T13:30:00+00:00", "https://www.bls.gov/news.release/ppi.nr0.htm"),
        ])

    def test_fomc_ignores_note_about_next_year_meeting(self):
        events = parse_fomc_calendar(text("fomc_calendar.txt"), self.now, days=180)
        days = [e["date_utc"][:10] for e in events]
        self.assertEqual(days, ["2026-12-09", "2027-01-27", "2027-03-17", "2027-04-28"])
        self.assertEqual(events[0]["date_utc"], "2026-12-09T19:00:00+00:00")  # 14:00 EST
        self.assertEqual(events[2]["date_utc"], "2027-03-17T18:00:00+00:00")  # 14:00 EDT
        self.assertTrue(events[0]["url"].endswith("/monetary20261209a.htm"))

    def test_wasde_eia_bea_official_pages(self):
        wasde = parse_wasde_calendar(text("wasde_calendar.txt"), self.now, days=60)
        self.assertEqual(wasde[0]["date_utc"], "2026-12-10T17:00:00+00:00")
        self.assertTrue(wasde[0]["url"].endswith("/wasde1226.pdf"))
        eia = parse_eia_schedule(text("eia_schedule.txt"), self.now, days=14)
        self.assertEqual(eia[0]["date_utc"], "2026-11-25T15:30:00+00:00")
        bea = parse_bea_calendar(text("bea_calendar.ics"), self.now)
        self.assertEqual((bea[0]["event"], bea[0]["date_utc"]),
                         ("Personal Income and Outlays, October 2026", "2026-11-25T13:30:00+00:00"))

    def test_holiday_week_claims_use_listed_time_only_where_cadence_is_omitted(self):
        listed = [datetime(2026, 11, 25, 13, 30, tzinfo=timezone.utc), datetime(2026, 12, 3, 13, 30, tzinfo=timezone.utc)]
        regular = scheduled_weekly_claims(self.now, 20, federal_holiday_conflicts(2026))
        extra = holiday_week_claims(listed, regular, self.now)
        self.assertEqual([e["id"] for e in extra], ["DOL:CLAIMS:2026-11-25"])
        self.assertIn("ForexFactory", extra[0]["note"])

    def test_rome_time_follows_both_daylight_saving_calendars(self):
        from oracle.analysis import Analysis
        from oracle.notify import format_message
        analysis = Analysis({"Gold": "SHORT", "Copper": "LONG"}, "test")
        for day, rome in (("March 11, 2026", "13:30"), ("March 31, 2026", "14:30"), ("November 3, 2026", "14:30"),
                          ("October 28, 2026", "13:30"), ("November 10, 2026", "14:30")):
            weekday = datetime.strptime(day, "%B %d, %Y").strftime("%A")
            html = f"<p>{weekday}, {day} 08:30 AM Consumer Price Index for February 2026</p>"
            event = parse_bls_calendar(html, datetime(2026, 1, 1, tzinfo=timezone.utc))[0]
            self.assertIn(f"🕒 Pubblicazione: {rome} Italia", format_message(event, analysis, "x"), day)
