"""Single public weekly economic calendar; no API key or account."""
from datetime import datetime, timezone, timedelta
import requests

URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CALENDAR_PAGE = "https://www.forexfactory.com/calendar"

def parse_calendar(rows, now=None):
    now = now or datetime.now(timezone.utc)
    events = []
    if not isinstance(rows, list):
        raise ValueError("Expected calendar JSON array")
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("country") != "USD":
            continue
        try:
            stamp = datetime.fromisoformat(str(row["date"]).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                continue
            stamp = stamp.astimezone(timezone.utc)
            if not now - timedelta(hours=2) <= stamp <= now + timedelta(days=7):
                continue
            title = str(row["title"]).strip()
            if not title:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        events.append({
            "id": f"FF:{stamp.isoformat()}:{title}",
            "date_utc": stamp.isoformat(), "event": title,
            "country": "US", "source": "Forex Factory",
            "importance": str(row.get("impact") or "UNKNOWN").upper(), "url": CALENDAR_PAGE,
            "forecast": str(row.get("forecast") or ""),
            "previous": str(row.get("previous") or ""),
        })
    return sorted({event["id"]: event for event in events}.values(), key=lambda e: e["date_utc"])

def fetch_calendar(days=7):
    try:
        response = requests.get(URL, timeout=15, headers={"User-Agent": "StellaRossaCalendar/1.0"})
        response.raise_for_status()
        events = parse_calendar(response.json())
        print(f"[CALENDAR] Forex Factory all USD events={len(events)}")
        return events
    except (requests.RequestException, ValueError, TypeError) as exc:
        print(f"[CALENDAR ERROR] Forex Factory unavailable: {type(exc).__name__}")
        return []
