"""Multi-source public USD calendar; no API key or account."""
from datetime import datetime, timezone, timedelta
import requests

URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CALENDAR_PAGE = "https://www.forexfactory.com/calendar"
SECONDARY_URL = "https://showmytrades.com/api/public/calendar/v1"
SECONDARY_PAGE = "https://showmytrades.com/tools/economic-calendar"

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
            "actual": str(row.get("actual") or ""),
            "forecast": str(row.get("forecast") or ""),
            "previous": str(row.get("previous") or ""),
        })
    return sorted({event["id"]: event for event in events}.values(), key=lambda e: e["date_utc"])

def _secondary_calendar(days=7, now=None):
    now = now or datetime.now(timezone.utc)
    response = requests.get(
        SECONDARY_URL,
        params={"currency": "USD", "impact": "all", "days": max(1, min(days, 30))},
        timeout=12,
        headers={"User-Agent": "StellaRossaCalendar/1.1"},
    )
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("events", [])
    if not isinstance(rows, list):
        raise ValueError("Secondary calendar events must be a list")
    events = []
    for row in rows:
        if not isinstance(row, dict) or row.get("currency") != "USD":
            continue
        try:
            stamp = datetime.fromisoformat(str(row["time"]).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                continue
            stamp = stamp.astimezone(timezone.utc)
            if not now - timedelta(hours=6) <= stamp <= now + timedelta(days=days):
                continue
            title = str(row.get("title") or "").strip()
            if not title:
                continue
        except (TypeError, ValueError, KeyError):
            continue
        events.append({
            "id": "SMT:" + str(row.get("id") or f"{stamp.isoformat()}:{title}"),
            "date_utc": stamp.isoformat(), "event": title,
            "country": "US", "source": "ShowMyTrades",
            "importance": str(row.get("impact") or "UNKNOWN").upper(),
            "url": SECONDARY_PAGE,
            "actual": str(row.get("actual") or ""),
            "forecast": str(row.get("forecast") or ""),
            "previous": str(row.get("previous") or ""),
        })
    return events


def _deduplicate(events):
    # Merge overlapping providers by normalized title and UTC time (within 10m).
    # Prefer the record with the most populated economic values.
    unique = {}
    for event in events:
        title = " ".join(event["event"].lower().split())
        stamp = datetime.fromisoformat(event["date_utc"])
        key = next((key for key, existing in unique.items()
                    if key[0] == title and abs((stamp - datetime.fromisoformat(existing["date_utc"])).total_seconds()) <= 600), None)
        if key is None:
            unique[(title, event["date_utc"])] = event
        else:
            current = unique[key]
            filled = lambda e: sum(bool(e.get(field)) for field in ("actual", "forecast", "previous"))
            if filled(event) > filled(current):
                unique[key] = event
    return sorted(unique.values(), key=lambda e: e["date_utc"])


def fetch_calendar(days=7):
    sources = []
    try:
        response = requests.get(URL, timeout=12, headers={"User-Agent": "StellaRossaCalendar/1.1"})
        response.raise_for_status()
        primary = parse_calendar(response.json())
        sources.extend(primary)
        print(f"[CALENDAR] Forex Factory events={len(primary)}")
    except (requests.RequestException, ValueError, TypeError) as exc:
        print(f"[CALENDAR ERROR] Forex Factory: {type(exc).__name__}")
    try:
        secondary = _secondary_calendar(days=days)
        sources.extend(secondary)
        print(f"[CALENDAR] ShowMyTrades events={len(secondary)}")
    except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
        print(f"[CALENDAR ERROR] ShowMyTrades: {type(exc).__name__}")
    merged = _deduplicate(sources)
    print(f"[CALENDAR] merged USD events={len(merged)} raw={len(sources)}")
    return merged
