"""Single-source FRED economic calendar.

FRED's release-dates API supplies *dates*, not publication times. Never
fabricate an intraday trigger from a date-only release. Only releases with a
documented stable scheduled time are eligible; all others are skipped.
"""
from datetime import datetime, date, time, timedelta, timezone
from zoneinfo import ZoneInfo
import os
import requests

ET = ZoneInfo("America/New_York")
URL = "https://api.stlouisfed.org/fred/releases/dates"
CALENDAR_URL = "https://fred.stlouisfed.org/releases/calendar"

# Exact release-name matches: no fuzzy guesses and no implied direction.
# US scheduled publication clocks; special holiday shifts must be checked
# before any live trading use.
RELEASE_CLOCKS = {
    "Consumer Price Index": time(8, 30),
    "Producer Price Index": time(8, 30),
    "Employment Situation": time(8, 30),
    "Job Openings and Labor Turnover Survey": time(10, 0),
    "Advance Monthly Sales for Retail and Food Services": time(8, 30),
    "Gross Domestic Product": time(8, 30),
    "Personal Income and Outlays": time(8, 30),
    "Durable Goods Manufacturers' Shipments, Inventories and Orders": time(8, 30),
    "New Residential Construction": time(8, 30),
    "Industrial Production and Capacity Utilization": time(9, 15),
    "Manufacturing Business Outlook Survey": time(8, 30),
    "Unemployment Insurance Weekly Claims Report": time(8, 30),
}
# Some FRED releases share names or are published at variable times.
# Those not listed above must not silently trigger a market scan.


def parse_fred_releases(payload, now=None, days=7):
    now = now or datetime.now(timezone.utc)
    end = now + timedelta(days=days)
    events = []
    for row in payload.get("release_dates", []):
        title = str(row.get("release_name", "")).strip()
        clock = RELEASE_CLOCKS.get(title)
        if clock is None:
            continue
        try:
            day = date.fromisoformat(row["date"])
            release_id = int(row["release_id"])
            stamp = datetime.combine(day, clock, tzinfo=ET).astimezone(timezone.utc)
        except (KeyError, ValueError, TypeError):
            continue
        if now - timedelta(hours=2) <= stamp <= end:
            events.append({
                "id": f"FRED:{release_id}:{day.isoformat()}",
                "date_utc": stamp.isoformat(),
                "event": title,
                "country": "US",
                "source": "FRED",
                "importance": "HIGH",
                "url": f"https://fred.stlouisfed.org/release?rid={release_id}",
            })
    return sorted({item["id"]: item for item in events}.values(), key=lambda item: item["date_utc"])


def fetch_fred_calendar(days=7):
    key = os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        print("[CALENDAR ERROR] FRED_API_KEY missing; no fabricated events")
        return []
    today = datetime.now(ET).date()
    end = today + timedelta(days=days)
    all_rows = []
    offset = 0
    try:
        while True:
            response = requests.get(URL, params={
                "api_key": key, "file_type": "json",
                "include_release_dates_with_no_data": "true",
                "order_by": "release_date", "sort_order": "desc",
                "limit": 1000, "offset": offset,
            }, timeout=15)
            response.raise_for_status()
            data = response.json()
            rows = data.get("release_dates", [])
            all_rows.extend(rows)
            offset += len(rows)
            # Descending releases: once past today, later pages are older.
            if (not rows or offset >= int(data.get("count", 0))
                    or any(str(row.get("date", "")) < today.isoformat() for row in rows)
                    or offset >= 5000):
                break
        events = parse_fred_releases({"release_dates": all_rows}, days=days)
        print(f"[CALENDAR] FRED rows={len(all_rows)} eligible={len(events)}")
        return events
    except (requests.RequestException, ValueError, TypeError) as exc:
        print(f"[CALENDAR ERROR] FRED unavailable: {type(exc).__name__}")
        return []
