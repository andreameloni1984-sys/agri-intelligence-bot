"""Calendar-first scheduler. Each invocation returns time until the next check."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging

from . import storage
from .analysis import UNKNOWN, interpret
from .calendar import fetch_economic_calendar
from .models import Context, Release, event_kind
from .news import fetch_context
from .notify import format_message, send_telegram
from .releases import fetch_release

PRE_WINDOW = timedelta(minutes=30)
POST_WINDOW = timedelta(hours=2)
LATER_RECHECK = timedelta(minutes=10)


def _calendar(now):
    cache = storage.load("official_calendar", {})
    events = cache.get("events", [])
    refresh = datetime.fromisoformat(cache["refresh"]) if "refresh" in cache else now
    if now < refresh:
        logging.info("[CALENDAR] cache_hit events=%d next_refresh=%s", len(events), refresh.isoformat())
        return events, refresh
    fresh = fetch_economic_calendar(now=now)
    # Preserve sources that are temporarily unavailable without keeping replaced
    # schedules from sources that did return events.
    sources = {item["source"] for item in fresh}
    events = fresh + [item for item in events if item["source"] not in sources
                      and datetime.fromisoformat(item["date_utc"]) >= now - POST_WINDOW]
    refresh = now + timedelta(hours=6 if len(sources) >= 6 else 1)
    storage.save("official_calendar", {"events": events, "refresh": refresh.isoformat()})
    logging.info("[CALENDAR] refreshed events=%d sources=%s next_refresh=%s", len(events), ",".join(sorted(sources)) or "none", refresh.isoformat())
    return events, refresh


def _merge_context(saved, fresh):
    return Context(
        consensus={**saved.consensus, **fresh.consensus},
        previous={**saved.previous, **fresh.previous},
        scenario={**saved.scenario, **fresh.scenario},
        periods={**saved.periods, **fresh.periods},
        urls=list(dict.fromkeys(fresh.urls + saved.urls))[:8],
        headlines=fresh.headlines,
    )


def _process(event, stamp, now, dry_run):
    event_id = event["id"]
    kind = event_kind(event["event"])
    preliminary = now < stamp
    phase = "preliminary" if preliminary else "published"
    state_key = f"check:{event_id}:{phase}"
    check = storage.load(state_key, {})
    last, delivery = storage.last_result(event_id, phase)
    due = datetime.fromisoformat(check["next"]) if "next" in check else now
    if now < due:
        logging.info("[EVENT] id=%s phase=%s skipped=not_due next=%s", event_id, phase, due.isoformat())
        return due

    context_key = f"context:{event_id}"
    cached = Context(**storage.load(context_key, {}))
    last_context_check = datetime.fromisoformat(check["context_checked_at"]) if "context_checked_at" in check else None
    context_due = (preliminary or last_context_check is None
                   or now - last_context_check >= timedelta(minutes=20))
    with ThreadPoolExecutor(max_workers=2) as pool:
        release_future = pool.submit(fetch_release, event, preliminary)
        context_future = None
        if context_due:
            context_future = pool.submit(fetch_context, event, now)
        release = release_future.result()
        context = _merge_context(cached, context_future.result()) if context_future else cached
    if context_future:
        storage.save(context_key, asdict(context))

    if preliminary:
        next_check = min(stamp, now + timedelta(minutes=10))
    elif release is None or not release.actual:
        next_check = now + (timedelta(seconds=30) if now - stamp < timedelta(minutes=10)
                            else timedelta(minutes=2))
    else:
        next_check = now + LATER_RECHECK
    check["next"] = next_check.isoformat()
    if context_future:
        check["context_checked_at"] = now.isoformat()
    storage.save(state_key, check)
    if not preliminary and (release is None or not release.actual):
        storage.save(f"availability:{event_id}", {"state": "waiting_for_release", "checked_at": now.isoformat()})
        logging.info("Comunicato %s non ancora disponibile", event_id)
        return next_check

    if not preliminary:
        storage.save(f"availability:{event_id}", {"state": "published", "checked_at": now.isoformat()})
    release = release or Release({}, event["url"])
    analysis = interpret(kind, release, context, preliminary)
    logging.info("[ANALYSIS] event=%s phase=%s directions=%s", event_id, phase, json.dumps(analysis.directions, sort_keys=True))
    directional = any(direction != UNKNOWN for direction in analysis.directions.values())
    payload = {"release": asdict(release), "context": asdict(context), "analysis": asdict(analysis)}
    material = [sorted(analysis.directions.items()), analysis.reason]
    fingerprint = hashlib.sha256(json.dumps(material, ensure_ascii=False).encode()).hexdigest()
    storage.save(f"outcome:{event_id}:{phase}", payload)
    if preliminary and (not directional or (last and delivery != "retry")):
        return next_check
    # Publish when the economic conclusion changes. A numeric correction with
    # the same conclusion is retained in the journal without another alert.
    if last and last["analysis"]["directions"] == analysis.directions and delivery != "retry":
        return next_check
    message = format_message(event, analysis, release.url, preliminary, update=bool(last and delivery != "retry"))
    if dry_run:
        logging.info("%s", message)
    elif storage.record(event_id, phase, fingerprint, now, payload):
        result = send_telegram(message)
        storage.finish(event_id, phase, fingerprint, result)
        logging.info("Evento %s %s: Telegram %s", event_id, phase, result)
    return next_check


def main(now=None, dry_run=False):
    now = now or datetime.now(timezone.utc)
    events, next_check = _calendar(now)
    # Calendar-only: Sputnik owns independent news scanning.
    eligible = 0
    active = 0
    for event in events:
        if not event_kind(event["event"]):
            continue
        eligible += 1
        stamp = datetime.fromisoformat(event["date_utc"])
        if now < stamp - PRE_WINDOW:
            next_check = min(next_check, stamp - PRE_WINDOW)
        elif now < stamp + POST_WINDOW:
            active += 1
            try:
                due = _process(event, stamp, now, dry_run)
                if due < stamp + POST_WINDOW:
                    next_check = min(next_check, due)
            except Exception:
                logging.exception("Elaborazione evento %s", event["id"])
                next_check = min(next_check, now + timedelta(seconds=30))
    logging.info("[DONE] calendar_events=%d eligible=%d active_windows=%d next_check=%s", len(events), eligible, active, next_check.isoformat())
    return max(1, (next_check - now).total_seconds())


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    main(dry_run=args.dry_run)
