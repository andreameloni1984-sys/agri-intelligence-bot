"""Official US economic release calendar (BLS, EIA, Fed and USDA WASDE).

Times are normalized from America/New_York to UTC. If an official source is
unavailable or its format changes, that source returns no events; dates are
never inferred from news headlines.
"""
from datetime import date, datetime, time, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from zoneinfo import ZoneInfo
import re
import requests

ET = ZoneInfo("America/New_York")
EIA_URL = "https://www.eia.gov/petroleum/supply/weekly/schedule.php"
FED_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
USDA_URL = "https://usda.azureedge.us/about-usda/general-information/staff-offices/office-chief-economist/commodity-markets/wasde-report"
USER_AGENT = "ORACLE-research-bot/0.7 (+official-calendar-reader)"
BLS_IMPORTANT = (
    "Consumer Price Index", "Producer Price Index", "Employment Situation",
    "Job Openings and Labor Turnover", "Productivity and Costs",
    "Employment Cost Index", "U.S. Import and Export Price Indexes",
)
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
        if not any(label.lower() in title.lower() for label in BLS_IMPORTANT):
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


def _eia_exceptions(html: str) -> dict[date, date]:
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
            result[week_end + timedelta(days=5)] = alternate
        except ValueError:
            continue
    return result


def parse_eia_schedule(html: str, now: datetime | None = None, days: int = 45) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    exceptions = _eia_exceptions(html)
    start = now.astimezone(ET).date()
    end = start + timedelta(days=days)
    events = []
    day = start
    while day <= end:
        if day.weekday() == 2:
            event_day = exceptions.get(day, day)
            event_time = time(10, 30) if event_day == day else time(12, 0)
            if event_day != day:
                raw = _html_text(html)
                time_match = re.search(
                    rf"{event_day.strftime('%B')}\s+{event_day.day},\s+{event_day.year}.*?"
                    rf"(?:Wednesday|Thursday|Monday|Tuesday|Friday|Saturday|Sunday)\s+"
                    rf"(\d{{1,2}}:\d{{2}})\s+(a\.m\.|p\.m\.)", raw, re.IGNORECASE)
                if time_match:
                    parsed = time_match.group(1) + " " + time_match.group(2).replace(".", "").upper()
                    event_time = datetime.strptime(parsed, "%I:%M %p").time()
            stamp = datetime.combine(event_day, event_time, tzinfo=ET).astimezone(timezone.utc)
            if now - timedelta(hours=2) <= stamp:
                events.append(_event(f"EIA:WPSR:{event_day.isoformat()}", stamp,
                                     "Weekly Petroleum Status Report", "EIA", EIA_URL))
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
            r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})\*?",
            section.group(1), re.IGNORECASE):
            month = MONTHS[match.group(1).lower()]
            final_day = int(match.group(3))
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


def fetch_economic_calendar(days: int = 45) -> list[dict]:
    """Fetch official schedules concurrently; a slow publisher cannot block the others."""
    current_year = datetime.now(timezone.utc).year
    sources = (
        (f"https://www.bls.gov/schedule/{current_year}/", parse_bls_calendar),
        (EIA_URL, lambda html: parse_eia_schedule(html, days=days)),
        (FED_URL, lambda html: parse_fomc_calendar(html, days=days)),
        (USDA_URL, lambda html: parse_wasde_calendar(html, days=days)),
    )

    def fetch_one(url, parser):
        try:
            response = requests.get(url, timeout=15, headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
            parsed = parser(response.text)
            print(f"[CALENDAR] source={url} events={len(parsed)}")
            return parsed
        except Exception as exc:
            print(f"[CALENDAR] source unavailable {url}: {type(exc).__name__}")
            return []

    events = []
    with ThreadPoolExecutor(max_workers=len(sources)) as pool:
        futures = [pool.submit(fetch_one, url, parser) for url, parser in sources]
        for future in as_completed(futures):
            events.extend(future.result())

    unique = {item["id"]: item for item in events}
    return sorted(unique.values(), key=lambda item: item["date_utc"])
