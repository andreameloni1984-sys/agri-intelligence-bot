"""Official US economic release calendar (BLS, EIA, Fed and USDA WASDE).

Times are normalized from America/New_York to UTC. If an official source is
unavailable or its format changes, that source returns no events; dates are
never inferred from news headlines.
"""
from datetime import date, datetime, time, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from zoneinfo import ZoneInfo
import re
import requests
import logging
from .models import event_kind

ET = ZoneInfo("America/New_York")
EIA_URL = "https://www.eia.gov/petroleum/supply/weekly/schedule.php"
BEA_URL = "https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics"
FED_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
USDA_URL = "https://www.usda.gov/about-usda/general-information/staff-offices/office-chief-economist/commodity-markets/wasde-report"
USER_AGENT = "Stella-Rossa/1.0 (+official-calendar-reader)"
MONTHS = {m.lower(): i for i, m in enumerate(
    ("January February March April May June July August September October November December").split(), 1)}
MONTH_ABBR = {m[:3].lower(): i for i, m in enumerate(
    ("January February March April May June July August September October November December").split(), 1)}
DATE_RE = re.compile(
    r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"(\d{1,2}),\s+(\d{4})\s+(\d{1,2}:\d{2})\s+(AM|PM)\s+"
    r"(.+?)(?=(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"\d{1,2},\s+\d{4}|NOTE: All times|$)", re.IGNORECASE)


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        if data.strip():
            self.parts.append(data.strip())


def _html_text(html: str) -> str:
    parser = _Text()
    parser.feed(html)
    return re.sub(r"\s+", " ", " ".join(parser.parts))


def _event(event_id, stamp, title, source, url):
    return {
        "id": event_id, "date_utc": stamp.isoformat(), "event": title,
        "country": "US", "source": source, "importance": "HIGH", "url": url,
    }


def _to_utc(day: date, clock: str, ampm: str) -> datetime:
    parsed = datetime.strptime(f"{clock} {ampm.upper()}", "%I:%M %p").time()
    return datetime.combine(day, parsed, tzinfo=ET).astimezone(timezone.utc)


def parse_bls_calendar(html: str, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    text = _html_text(html)
    events = []
    for match in DATE_RE.finditer(text):
        _, month, day, year, clock, ampm, title = match.groups()
        title = title.strip(" .;")
        if not event_kind(title):
            continue
        try:
            event_day = datetime.strptime(f"{month} {day} {year}", "%B %d %Y").date()
            published_at = _to_utc(event_day, clock, ampm)
        except ValueError:
            continue
        if published_at >= now - timedelta(hours=2):
            events.append(_event(f"BLS:{event_day.isoformat()}:{title}", published_at,
                                 title, "BLS", f"https://www.bls.gov/schedule/{event_day.year}/"))
    return sorted(events, key=lambda item: item["date_utc"])


def _eia_exceptions(html: str) -> dict[date, tuple[date, time]]:
    text = _html_text(html)
    pattern = re.compile(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
        r"(\d{1,2}),\s+(\d{4})\s+"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
        r"(\d{1,2}),\s+(\d{4})\s+"
        r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+"
        r"(\d{1,2}:\d{2})\s+(a\.m\.|p\.m\.)", re.IGNORECASE)
    result = {}
    for m in pattern.finditer(text):
        try:
            week_end = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y").date()
            alternate = datetime.strptime(f"{m.group(4)} {m.group(5)} {m.group(6)}", "%B %d %Y").date()
            result[week_end + timedelta(days=5)] = (alternate, _to_utc(alternate, m.group(8), m.group(9).replace(".", "")).astimezone(ET).time())
        except ValueError:
            continue
    return result


def parse_eia_schedule(html: str, now: datetime | None = None, days: int = 45) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    if "standard release time" not in _html_text(html).lower():
        return []
    exceptions = _eia_exceptions(html)
    start = now.astimezone(ET).date() - timedelta(days=7)
    end = now.astimezone(ET).date() + timedelta(days=days)
    events = []
    day = start
    while day <= end:
        if day.weekday() == 2:
            event_day, event_time = exceptions.get(day, (day, time(10, 30)))
            stamp = datetime.combine(event_day, event_time, tzinfo=ET).astimezone(timezone.utc)
            if now - timedelta(hours=2) <= stamp:
                event = _event(f"EIA:WPSR:{day.isoformat()}", stamp,
                               "Weekly Petroleum Status Report", "EIA", EIA_URL)
                event["period"] = (day - timedelta(days=5)).isoformat()
                events.append(event)
        day += timedelta(days=1)
    return sorted(events, key=lambda item: item["date_utc"])


def parse_fomc_calendar(html: str, now: datetime | None = None, days: int = 180) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    text = _html_text(html)
    current_year = now.astimezone(ET).year
    events = []
    for year in range(current_year, current_year + 2):
        section = re.search(rf"{year}\s+FOMC Meetings(.*?)(?=\d{{4}}\s+FOMC Meetings|$)", text, re.IGNORECASE)
        if not section:
            continue
        for match in re.finditer(
            r"\b(January|February|March|April|May|June|July|August|September|October|November|December)(?:/(January|February|March|April|May|June|July|August|September|October|November|December))?\s+(\d{1,2})\s*[-–]\s*(\d{1,2})\*?",
            section.group(1), re.IGNORECASE):
            month = MONTHS[(match.group(2) or match.group(1)).lower()]
            final_day = int(match.group(4))
            try:
                meeting_day = date(year, month, final_day)
            except ValueError:
                continue
            stamp = datetime.combine(meeting_day, time(14, 0), tzinfo=ET).astimezone(timezone.utc)
            if now - timedelta(hours=2) <= stamp <= now + timedelta(days=days):
                events.append(_event(f"FED:FOMC:{meeting_day.isoformat()}", stamp,
                                     "FOMC policy decision / statement (scheduled meeting day 2)",
                                     "Federal Reserve", FED_URL))
    return sorted(events, key=lambda item: item["date_utc"])


def parse_wasde_calendar(html: str, now: datetime | None = None, days: int = 180) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    text = _html_text(html)
    events = []
    for match in re.finditer(
        r"(20\d{2})\s+WASDE Release Dates\s*\(\s*12:00\s*pm\s*ET\s*\).*?"
        r"In\s+\1\s+the WASDE report will be released on\s+(.+?)(?=20\d{2}\s+WASDE Release Dates|$)",
        text, re.IGNORECASE):
        year = int(match.group(1))
        date_list = match.group(2)
        for item in re.finditer(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s*(\d{1,2})\b",
                                date_list, re.IGNORECASE):
            month = MONTH_ABBR[item.group(1).lower()]
            try:
                release_day = date(year, month, int(item.group(2)))
            except ValueError:
                continue
            stamp = datetime.combine(release_day, time(12, 0), tzinfo=ET).astimezone(timezone.utc)
            if now - timedelta(hours=2) <= stamp <= now + timedelta(days=days):
                events.append(_event(f"USDA:WASDE:{release_day.isoformat()}", stamp,
                                     "USDA WASDE supply and demand report", "USDA", USDA_URL))
    return sorted(events, key=lambda item: item["date_utc"])


def parse_bea_calendar(ics: str, now: datetime) -> list[dict]:
    events = []
    unfolded = re.sub(r"\r?\n[ \t]", "", ics)
    for block in unfolded.split("BEGIN:VEVENT")[1:]:
        title = re.search(r"^SUMMARY:Personal Income and Outlays\\, ([A-Z][a-z]+) (20\d{2})\s*$", block, re.M)
        date_match = re.search(r"^DTSTART(?:;[^:\r\n]+)?:(\d{8}T\d{6}Z)\s*$", block, re.M)
        if not title or not date_match:
            continue
        stamp = datetime.strptime(date_match[1], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        if stamp >= now - timedelta(hours=2):
            month, year = title.groups()
            url = f"https://www.bea.gov/news/{year}/personal-income-and-outlays-{month.lower()}-{year}"
            events.append(_event(f"BEA:PCE:{year}-{month.lower()}", stamp,
                                 f"Personal Income and Outlays, {month} {year}", "BEA", url))
    return events


DOL_URL = "https://www.dol.gov/newsroom/economicdata"


def scheduled_weekly_claims(now: datetime, days: int, holidays: set[date]) -> list[dict]:
    """Use the DOL regular cadence and omit federal-holiday weeks pending a verified schedule."""
    start = now.astimezone(ET).date()
    events = []
    for offset in range(days + 1):
        day = start + timedelta(days=offset)
        if day.weekday() != 3 or day in holidays or day - timedelta(days=1) in holidays:
            continue
        stamp = datetime.combine(day, time(8, 30), tzinfo=ET).astimezone(timezone.utc)
        if stamp >= now - timedelta(hours=2):
            event = _event(f"DOL:CLAIMS:{day.isoformat()}", stamp,
                           "Unemployment Insurance Weekly Claims", "DOL", DOL_URL)
            event["period"] = (day - timedelta(days=5)).isoformat()
            events.append(event)
    return events


def federal_holiday_conflicts(year: int) -> set[date]:
    # Of the US federal holidays only fixed-date holidays and Thanksgiving
    # can fall on a Wednesday or Thursday (including observed dates).
    holidays = set()
    for month, day in ((1, 1), (6, 19), (7, 4), (11, 11), (12, 25)):
        holiday = date(year, month, day)
        shift = {5: -1, 6: 1}.get(holiday.weekday(), 0)
        holidays.add(holiday + timedelta(days=shift))
    november = date(year, 11, 1)
    holidays.add(november + timedelta(days=(3 - november.weekday()) % 7 + 21))
    return holidays


def fetch_economic_calendar(days: int = 45, now: datetime | None = None) -> list[dict]:
    """Load official schedules concurrently and enforce the same horizon on each."""
    now = now or datetime.now(timezone.utc)
    year = now.astimezone(ET).year
    end = now + timedelta(days=days)
    years = range(year, end.astimezone(ET).year + 1)

    sources = [
        *( (f"https://www.bls.gov/schedule/{yr}/home.htm", lambda html: parse_bls_calendar(html, now))
           for yr in years),
        (EIA_URL, lambda html: parse_eia_schedule(html, now, days)),
        (FED_URL, lambda html: parse_fomc_calendar(html, now, days)),
        (USDA_URL, lambda html: parse_wasde_calendar(html, now, days)),
        (BEA_URL, lambda ics: parse_bea_calendar(ics, now)),
    ]

    def fetch_one(source):
        url, parser = source
        try:
            response = requests.get(url, timeout=8, headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
            return parser(response.text)
        except (requests.RequestException, ValueError) as exc:
            logging.warning("Calendario %s: %s", url, type(exc).__name__)
            return []

    with ThreadPoolExecutor(max_workers=len(sources)) as pool:
        unique = {event["id"]: event for batch in pool.map(fetch_one, sources) for event in batch
                  if datetime.fromisoformat(event["date_utc"]) <= end}
    holidays = set().union(*(federal_holiday_conflicts(yr) for yr in range(year - 1, year + 2 + days // 365)))
    unique.update((event["id"], event) for event in scheduled_weekly_claims(now, days, holidays)
                  if datetime.fromisoformat(event["date_utc"]) <= end)
    return sorted(unique.values(), key=lambda item: item["date_utc"])
