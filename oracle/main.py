"""Calendar-first scheduler.

Each call to main() does only the work that is due and returns the seconds until
the next useful check. Outside event windows nothing is fetched except the
cached official calendar.

Per event:
  * T-30 min: one preliminary message (direction or "previsione non disponibile").
  * From T: poll the issuing agency (15 s, then 30 s, then 2 min) until the figure
    is out, send one "dato pubblicato" message and stop.
  * T+61 min after each signal: record futures prices for the journal.
"""
from dataclasses import asdict, fields
from datetime import datetime, timedelta, timezone
import argparse
import hashlib
import json
import logging
import time

from . import storage
from .analysis import UNKNOWN, interpret
from .calendar import fetch_economic_calendar
from .models import EVENTS, Context, Release, event_kind
from .news import fetch_context
from .notify import format_message, send_telegram
from .prices import HORIZONS, evaluate
from .releases import fetch_release

PRE_WINDOW = timedelta(minutes=30)
POST_WINDOW = timedelta(hours=2)
PRICE_DELAY = timedelta(minutes=max(HORIZONS) + 1)
PRICE_EXPIRY = timedelta(days=6)  # Yahoo keeps 1-minute bars for about a week
STAY_ALIVE = timedelta(minutes=45)


def _calendar(now):
    cache = storage.load("official_calendar", {})
    events = cache.get("events", [])
    refresh = datetime.fromisoformat(cache["refresh"]) if "refresh" in cache else now
    if now < refresh:
        logging.info("[CALENDAR] cache_hit events=%d next_refresh=%s", len(events), refresh.isoformat())
        return events, refresh
    fresh = fetch_economic_calendar(now=now)
    # Keep events of a temporarily unavailable source, replace those of sources that answered.
    sources = {item["source"] for item in fresh}
    events = fresh + [item for item in events if item["source"] not in sources
                      and datetime.fromisoformat(item["date_utc"]) >= now - POST_WINDOW]
    refresh = now + timedelta(hours=6 if len(sources) >= 6 else 1)
    storage.save("official_calendar", {"events": events, "refresh": refresh.isoformat()})
    logging.info("[CALENDAR] refreshed events=%d sources=%s next_refresh=%s",
                 len(events), ",".join(sorted(sources)) or "none", refresh.isoformat())
    return events, refresh


def _context(event, now):
    """Fetch consensus/estimate once per phase and reuse it (no repeated requests)."""
    key = f"context:{event['id']}"
    phase = "preliminary" if now < datetime.fromisoformat(event["date_utc"]) else "published"
    saved = storage.load(key, {})
    names = {item.name for item in fields(Context)}
    if saved.get("_phase") in {phase, "preliminary"} and (saved.get("consensus") or phase == "preliminary"):
        return Context(**{name: value for name, value in saved.items() if name in names})
    context = fetch_context(event, now)
    storage.save(key, {**asdict(context), "_phase": phase})
    return context


def _poll_delay(now, stamp):
    late = now - stamp
    return timedelta(seconds=15 if late < timedelta(minutes=5) else 30 if late < timedelta(minutes=20) else 120)


def _deliver(event, phase, message, payload, now, dry_run):
    if dry_run:
        logging.info("[DRY-RUN]\n%s", message)
        return "dry_run"
    fingerprint = hashlib.sha256(f"{event['id']}:{phase}".encode()).hexdigest()
    if not storage.record(event["id"], phase, fingerprint, now, payload):
        return "duplicate"
    result = send_telegram(message)
    storage.finish(event["id"], phase, fingerprint, result)
    return result


def _process(event, stamp, now, dry_run):
    """Handle the current phase of one event; return when it needs another look (or None)."""
    event_id = event["id"]
    kind = event_kind(event["event"])
    preliminary = now < stamp
    phase = "preliminary" if preliminary else "published"
    done_key = f"done:{event_id}:{phase}"
    if storage.load(done_key):
        return None
    storage.journal_update(event_id, event["date_utc"], event=event["event"], label=EVENTS[kind][1],
                           source=event["url"], note=event.get("note", ""))

    context = _context(event, now)
    release = None if preliminary else fetch_release(event)
    if not preliminary and (release is None or not release.actual):
        logging.info("[EVENT] id=%s waiting_for_release", event_id)
        return now + _poll_delay(now, stamp)

    release = release or Release({}, event["url"])
    analysis = interpret(kind, release, context, preliminary)
    source = " | ".join(dict.fromkeys([event["url"], *context.urls])) if preliminary else release.url
    payload = {"release": asdict(release), "context": asdict(context), "analysis": asdict(analysis)}
    message = format_message(event, analysis, source, preliminary)
    delivery = _deliver(event, phase, message, payload, now, dry_run)
    logging.info("[EVENT] id=%s phase=%s directions=%s telegram=%s", event_id, phase,
                 json.dumps(analysis.directions, sort_keys=True), delivery)
    if delivery == "retry":
        return now + timedelta(seconds=30)
    storage.save(done_key, True)
    storage.journal_update(event_id, event["date_utc"], **{phase: {
        "sent_at": now.isoformat(), "delivery": delivery, "delay_s": round((now - stamp).total_seconds()),
        "directions": analysis.directions, "reason": analysis.reason, "source": source,
        "data": {"actual": release.actual, "previous": {**context.previous, **release.previous},
                 "revised": release.revised, "consensus": context.consensus,
                 "scenario": context.scenario, "scenario_source": context.scenario_source},
    }})
    return None


def _evaluate_prices(now):
    next_due = None
    for entry in storage.journal_entries():
        for phase in ("preliminary", "published"):
            item = entry.get(phase)
            if not item or "evaluation" in item:
                continue
            if not any(direction != UNKNOWN for direction in item["directions"].values()):
                continue
            sent = datetime.fromisoformat(item["sent_at"])
            if now < sent + PRICE_DELAY:
                next_due = min(filter(None, (next_due, sent + PRICE_DELAY)))
                continue
            item["evaluation"] = (evaluate(item["directions"], sent) if now - sent < PRICE_EXPIRY
                                  else {"error": "prezzi a 1 minuto non più disponibili"})
            storage.journal_update(entry["event_id"], entry["event_time"], **{phase: item})
            logging.info("[JOURNAL] id=%s phase=%s evaluation=%s", entry["event_id"], phase,
                         json.dumps(item["evaluation"], sort_keys=True))
    return next_due


def main(now=None, dry_run=False):
    now = now or datetime.now(timezone.utc)
    events, next_check = _calendar(now)
    active = 0
    for event in events:
        if not event_kind(event["event"]):
            continue
        stamp = datetime.fromisoformat(event["date_utc"])
        if now < stamp - PRE_WINDOW:
            next_check = min(next_check, stamp - PRE_WINDOW)
        elif now < stamp + POST_WINDOW:
            active += 1
            try:
                due = _process(event, stamp, now, dry_run)
            except Exception:
                logging.exception("[EVENT] id=%s error", event["id"])
                due = now + timedelta(seconds=30)
            if due is None and now < stamp:
                due = stamp  # preliminary done: next look at publication time
            if due is not None:
                next_check = min(next_check, due)
    try:
        price_due = _evaluate_prices(now)
    except Exception:
        logging.exception("[JOURNAL] price evaluation error")
        price_due = None
    if price_due:
        next_check = min(next_check, price_due)
    logging.info("[DONE] calendar_events=%d active_windows=%d next_check=%s",
                 len(events), active, next_check.isoformat())
    return max(1, (next_check - now).total_seconds())


def run(loop_minutes=0, dry_run=False, clock=lambda: datetime.now(timezone.utc), sleep=time.sleep):
    """One pass, or (GitHub Actions) stay alive while the next check is close.

    A scheduled run that starts up to 45 minutes before a check waits for it, so
    publication is followed within seconds even when cron starts late or irregularly.
    """
    deadline = clock() + timedelta(minutes=loop_minutes)
    while True:
        delay = main(now=clock(), dry_run=dry_run)
        wake = clock() + timedelta(seconds=delay)
        if not loop_minutes or wake > deadline or timedelta(seconds=delay) > STAY_ALIVE:
            return
        logging.info("[LOOP] sleeping %.0fs", delay)
        sleep(delay)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--loop-minutes", type=int, default=0,
                        help="keep running while the next check is within 45 minutes (max N minutes)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(args.loop_minutes, args.dry_run)
