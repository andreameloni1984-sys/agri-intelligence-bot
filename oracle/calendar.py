"""Official US economic release calendar (BLS + EIA).

Times are parsed in America/New_York and normalized to UTC. If a source is
unavailable or its format changes, that source returns no events; no dates
are fabricated from news headlines.
"""
from datetime import date, datetime, time, timedelta, timezone
from html.parser import HTMLParser
from zoneinfo import ZoneInfo
import re
import requests

ET = ZoneInfo("America/New_York")
BLS_URL = "https://www.bls.gov/schedule/2026/"
EIA_URL = "https://www.eia.gov/petroleum/supply/weekly/schedule.php"
USER_AGENT = "ORACLE-research-bot/0.6 (+official-calendar-reader)"
BLS_IMPORTANT = (
    "Consumer Price Index", "Producer Price Index", "Employment Situation",
    "Job Openings and Labor Turnover", "Productivity and Costs",
    "Employment Cost Index", "U.S. Import and Export Price Indexes",
)
DATE_RE = re.compile(
    r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"(\d{1,2}),\s+(\d{4})\s+(\d{1,2}:\d{2})\s+(AM|PM)\s+"
    r"(.+?)(?=(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"\d{1,2},\s+\d{4}|NOTE: All times|$)",
    re.IGNORECASE,
)

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

def _to_utc(day: date, clock: str, ampm: str) -> datetime:
    parsed = datetime.strptime(f"{clock} {ampm.upper()}", "%I:%M %p").time()
    return datetime.combine(day, parsed, tzinfo=ET).astimezone(timezone.utc)

def parse_bls_calendar(html: str, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    text = _html_text(html)
    events = []
    for match in DATE_RE.finditer(text):
        weekday, month, day, year, clock, ampm, title = match.groups()
        title = title.strip(" .;")
        if not any(label.lower() in title.lower() for label in BLS_IMPORTANT):
            continue
        try:
            event_day = datetime.strptime(f"{month} {day} {year}", "%B %d %Y").date()
            published_at = _to_utc(event_day, clock, ampm)
        except ValueError:
            continue
        if published_at >= now - timedelta(hours=2):
            events.append({
                "id": f"BLS:{event_day.isoformat()}:{title}",
                "date_utc": published_at.isoformat(),
                "event": title,
                "country": "US",
                "source": "BLS",
                "importance": "HIGH",
                "url": BLS_URL,
            })
    return sorted(events, key=lambda item: item["date_utc"])

def _eia_exceptions(html: str) -> dict[date, date]:
    """Map the normal Wednesday date to the official holiday-adjusted date."""
    text = _html_text(html)
    pattern = re.compile(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
        r"(\d{1,2}),\s+(\d{4})\s+"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
        r"(\d{1,2}),\s+(\d{4})\s+"
        r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+"
        r"(\d{1,2}:\d{2})\s+(a\.m\.|p\.m\.)",
        re.IGNORECASE,
    )
    result = {}
    for m in pattern.finditer(text):
        try:
            week_end = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y").date()
            alternate = datetime.strptime(f"{m.group(4)} {m.group(5)} {m.group(6)}", "%B %d %Y").date()
            normal = week_end + timedelta(days=5)
            result[normal] = alternate
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
        if day.weekday() == 2:  # standard Wednesday release
            event_day = exceptions.get(day, day)
            event_time = time(10, 30) if event_day == day else time(12, 0)
            # The official holiday table provides the actual alternate time.
            # For listed exceptions the published standard time is not assumed.
            if event_day != day:
                raw = _html_text(html)
                time_match = re.search(
                    rf"{event_day.strftime('%B')}\s+{event_day.day},\s+{event_day.year}.*?"
                    rf"(?:Wednesday|Thursday|Monday|Tuesday|Friday|Saturday|Sunday)\s+"
                    rf"(\d{{1,2}}:\d{{2}})\s+(a\.m\.|p\.m\.)",
                    raw, re.IGNORECASE)
                if time_match:
                    parsed = datetime.strptime(time_match.group(1) + " " + time_match.group(2).replace(".", "").upper(), "%I:%M %p").time()
                    event_time = parsed
                else:
                    event_time = time(12, 0)
            stamp = datetime.combine(event_day, event_time, tzinfo=ET).astimezone(timezone.utc)
            if now - timedelta(hours=2) <= stamp:
                events.append({
                    "id": f"EIA:WPSR:{event_day.isoformat()}",
                    "date_utc": stamp.isoformat(),
                    "event": "Weekly Petroleum Status Report",
                    "country": "US",
                    "source": "EIA",
                    "importance": "HIGH",
                    "url": EIA_URL,
                })
        day += timedelta(days=1)
    return sorted(events, key=lambda item: item["date_utc"])

def fetch_economic_calendar(days: int = 45) -> list[dict]:
    """Fetch official BLS and EIA schedules. Fail independently per source."""
    events = []
    current_year = datetime.now(timezone.utc).year
    sources = (
        (f"https://www.bls.gov/schedule/{current_year}/", parse_bls_calendar),
        (EIA_URL, lambda html, now=None: parse_eia_schedule(html, now=now, days=days)),
    )
    for url, parser in sources:
        try:
            response = requests.get(url, timeout=15, headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
            events.extend(parser(response.text))
        except Exception as exc:
            print(f"[CALENDAR] source unavailable {url}: {exc}")
    unique = {item["id"]: item for item in events}
    return sorted(unique.values(), key=lambda item: item["date_utc"])
