from datetime import datetime, timezone, timedelta
from .config import UNIVERSE
from .news import collect_news
from .market import fetch_quotes
from .analysis import build_signal, score_news, build_pre_news_scenario
from .calendar import relevant_events
from .forexfactory_calendar import fetch_calendar
from .storage import (
    save_result, save_scan_meta, save_quotes, save_calendar_events,
    get_scheduler_state, save_scheduler_state, delete_signal,
)
from .calendar_selection import run_calendar_selection
from .notify import send_telegram

NEWS_SCAN_MINUTES = 5
NEWS_CACHE_HOURS = 12


def _news_to_dict(item):
    return {"title": item.title, "url": item.url, "published": item.published.isoformat(),
            "source": item.source, "summary": item.summary}


def _dict_to_news(row):
    from .models import NewsItem
    published = datetime.fromisoformat(row["published"])
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return NewsItem(row["title"], row["url"], published, row["source"], row.get("summary", ""))


def main():
    """Light calendar scheduler; fetch markets only from 30m before relevant releases."""
    started = datetime.now(timezone.utc)
    errors = []
    print(f"STELLA ROSSA calendar check started={started.isoformat()}")

    # Official schedules change infrequently: refresh every hour, not every
    # five-minute wake-up. Retain the last successful schedule on source failure.
    calendar_events = get_scheduler_state("cached_calendar", [])
    last_calendar_scan = get_scheduler_state("last_calendar_scan")
    calendar_due = True
    if last_calendar_scan:
        try:
            previous = datetime.fromisoformat(last_calendar_scan)
            if previous.tzinfo is None:
                previous = previous.replace(tzinfo=timezone.utc)
            calendar_due = started - previous >= timedelta(minutes=5)
        except (TypeError, ValueError):
            calendar_due = True

    if calendar_due:
        try:
            fresh_calendar = fetch_calendar(days=7)
            if fresh_calendar:
                calendar_events = fresh_calendar
                save_calendar_events(calendar_events)
                save_scheduler_state("cached_calendar", calendar_events)
            # If every official source returns no events, retry in one hour rather than six.
            # Keep the last successful calendar and do not trigger market scans.
            retry_reference = started - timedelta(hours=5) if not fresh_calendar else started
            save_scheduler_state("last_calendar_scan", retry_reference.isoformat())
            print(f"[CALENDAR] refreshed events={len(fresh_calendar)} cached={len(calendar_events)}")
        except Exception as exc:
            errors.append(f"calendar:{type(exc).__name__}")
            print(f"[CALENDAR] refresh failed: {type(exc).__name__}; cached events={len(calendar_events)}")
    else:
        print(f"[CALENDAR] using cached events={len(calendar_events)}")

    # Accept both supported public calendar providers; reject stale legacy events.
    # Discard old cached/manual events from earlier bot versions.
    official_sources = {"Forex Factory", "ShowMyTrades"}
    calendar_events = [
        event for event in calendar_events
        if event.get("source") in official_sources
        and event.get("id", "").split(":")[0] not in {"DOL"}
    ]
    print(f"[CALENDAR] official-source events={len(calendar_events)}")

    # Calendar-first mode: two assets per USD event; no technical scans or
    # directional-score threshold. Refresh results on each five-minute wake-up.
    try:
        news = collect_news()
    except Exception as exc:
        print(f"[NEWS] unavailable: {type(exc).__name__}")
        news = []
    run_calendar_selection(calendar_events, started, news)

    # Continue into the full event-driven market scan below.
    # Do not stop after calendar selection: the remaining pipeline fetches
    # quotes, evaluates signals, and records scan outcomes.

    # Audit the next 24h of mapped releases, including when no scan is due.
    upcoming = []
    for event in calendar_events:
        try:
            event_time = datetime.fromisoformat(event["date_utc"])
            if event_time.tzinfo is None:
                event_time = event_time.replace(tzinfo=timezone.utc)
            minutes = (event_time - started).total_seconds() / 60
            if 0 <= minutes <= 1440 and any(
                relevant_events(instrument, [event], now=started) for instrument in UNIVERSE
            ):
                upcoming.append((minutes, event))
        except (KeyError, ValueError, TypeError):
            continue
    upcoming.sort(key=lambda pair: pair[0])
    if upcoming:
        minutes, next_event = upcoming[0]
        print(f"[NEXT EVENT] in={minutes:.0f}m source={next_event.get('source')} "
              f"title={next_event.get('event')} at={next_event.get('date_utc')}")
    else:
        print("[CALENDAR WARNING] no mapped economic releases in next 24h; check source coverage")

    # GitHub Actions has a static cron, so it wakes every five minutes only to
    # evaluate the cached official schedule. Market/news downloads begin only
    # 15 minutes before a mapped release, and continue for 120 minutes after it.
    # Outside those windows this exits before news, quotes, technical analysis or alerts.
    active = {}
    for instrument in UNIVERSE:
        context = relevant_events(instrument, calendar_events, now=started)
        context = [
            item for item in context
            if item["phase"] == "APPENA PUBBLICATO"
            or (item["phase"] == "IN ARRIVO" and item["minutes_to_event"] <= 15)
        ]
        if context:
            active[instrument] = context

    # Outside calendar windows, check free news at most once per 30 minutes.
    # Only fresh, directionally mapped headlines activate a commodity quote scan.
    news = None
    if not active:
        last_news_scan = get_scheduler_state("last_news_scan")
        news_due = True
        if last_news_scan:
            try:
                previous_news = datetime.fromisoformat(last_news_scan)
                if previous_news.tzinfo is None:
                    previous_news = previous_news.replace(tzinfo=timezone.utc)
                news_due = started - previous_news >= timedelta(minutes=30)
            except (TypeError, ValueError):
                pass
        if news_due:
            try:
                news = collect_news()
                save_scheduler_state("cached_news", [_news_to_dict(item) for item in news])
                save_scheduler_state("last_news_scan", started.isoformat())
                fresh = [item for item in news if timedelta(0) <= started - item.published <= timedelta(minutes=35)]
                for instrument in UNIVERSE:
                    score, matched = score_news(instrument, fresh)
                    if abs(score) >= 2 and matched:
                        active[instrument] = []
                        print(f"[NEWS TRIGGER] {instrument.name} score={score:+d} headlines={len(matched)}")
                print(f"[NEWS] off-calendar items={len(news)} fresh={len(fresh)} active={len(active)}")
            except Exception as exc:
                errors.append(f"news:{type(exc).__name__}")
                print(f"[NEWS] off-calendar check failed: {type(exc).__name__}")
        if not active:
            print("[IDLE] no calendar window or fresh directional news; market scan skipped")
            save_scan_meta(started, 0, 0)
            return

    print("[EVENT WINDOW] " + ", ".join(
        f"{instrument.name}({len(context)})" for instrument, context in active.items()
    ))

    # Once a release has selected its commodities, subsequent five-minute scans
    # monitor only those symbols. The first pass may compare all mapped assets;
    # the persisted journal then keeps quote downloads focused on the winners.
    focused = {}
    for instrument, context in active.items():
        if not context:
            focused[instrument] = context
            continue
        nearest = context[0]
        event_key = nearest["source"] + "|" + nearest["event"] + "|" + nearest["date_utc"]
        chosen = get_scheduler_state("selected_event:" + event_key, [])
        if not isinstance(chosen, list) or not chosen or any(old == instrument.symbol or old.startswith(instrument.symbol + ":") for old in chosen):
            focused[instrument] = context
        else:
            print(f"[FOCUSED OUT] {instrument.name} event={event_key}")
    active = focused
    print(f"[FOCUSED MONITOR] active={len(active)}")

    # Headlines are collected only when a mapped event activates the relevant markets.
    try:
        if news is None:
            news = collect_news()
            save_scheduler_state("cached_news", [_news_to_dict(item) for item in news])
            save_scheduler_state("last_news_scan", started.isoformat())
        print(f"[NEWS] refreshed items={len(news)}")
    except Exception as exc:
        errors.append(f"news:{type(exc).__name__}")
        news = []
        print(f"[NEWS] refresh failed: {type(exc).__name__}; continuing with calendar and prices")

    # Pre-release view reuses the headlines already fetched for this event window.
    # It performs no additional network calls and never creates an order or alert.
    for instrument, event_context in active.items():
        preview = build_pre_news_scenario(instrument, news, event_context)
        if preview:
            evidence = " | ".join(preview["evidence"]) if preview["evidence"] else "nessuna notizia direzionale verificata"
            print(
                f"[PRE-NEWS] {instrument.name} {preview['direction']} "
                f"score={preview['score']:+d} confidence={preview['confidence']} "
                f"event={preview['event']} evidence={evidence}"
            )

    symbols = [instrument.symbol for instrument in active]
    try:
        quotes = fetch_quotes(symbols)
        save_quotes(quotes)
    except Exception as exc:
        errors.append(f"quotes:{type(exc).__name__}")
        quotes = {}
        print(f"[MARKET] active-symbol quote fetch failed: {type(exc).__name__}")

    directional = 0
    checked = 0
    candidates = []
    for instrument, event_context in active.items():
        quote = quotes.get(instrument.symbol)
        if quote is None:
            print(f"[MARKET] {instrument.name}: quote unavailable/stale; no signal")
            continue
        checked += 1
        try:
            news_score, matched = score_news(instrument, news)
            signal, status = build_signal(
                instrument, quote, news, calendar_context=event_context
            )
            if signal:
                signal.news_score = news_score
                signal.news_urls = [item.url for item in matched[:5]]
                directional += 1
                candidates.append((signal, instrument, status, event_context, news_score))
                print(
                    f"[CANDIDATE] {signal.instrument} {signal.direction} status={status} "
                    f"news_score={news_score:+d} calendar_events={len(event_context)} "
                    f"confidence={signal.confidence}"
                )
            else:
                print(
                    f"[WAIT] {instrument.name}: {status} news_score={news_score:+d} "
                    f"calendar_events={len(event_context)}"
                )
        except Exception as exc:
            errors.append(f"{instrument.symbol}:{type(exc).__name__}")
            print(f"[ANALYSIS] {instrument.name} failed: {type(exc).__name__}")

    # Calendar-driven selection: compare news-led candidates first, then alert at most
    # two distinct commodities per official release. Persist selections across
    # scheduled runs via the restored SQLite scheduler journal.
    calendar_groups = {}
    standalone = []
    for signal, instrument, status, context, news_score in candidates:
        if not context:
            standalone.append((signal, instrument, status))
            continue
        nearest = context[0]
        event_key = nearest["source"] + "|" + nearest["event"] + "|" + nearest["date_utc"]
        calendar_groups.setdefault(event_key, []).append(
            (signal, instrument, status, news_score, nearest)
        )

    # Calendar Telegram alerts are exclusively handled by run_calendar_selection:
    # one message with two assets, directions, analyses and instructions.
    # Legacy single-asset news-score alerts would duplicate the same release and
    # incorrectly label a news-only hypothesis as a confirmed signal.
    for event_key, options in calendar_groups.items():
        print(f"[CALENDAR LEGACY SUPPRESSED] event={event_key} candidates={len(options)}")

    # Preserve the existing independent news-led path outside calendar windows.
    for signal, instrument, status in standalone:
        is_new = save_result(signal, instrument.name, instrument.symbol, status)
        if is_new and not send_telegram(signal):
            delete_signal(signal)

    save_scan_meta(started, len(news), checked)
    print(
        f"[DONE] event_driven=true active_markets={len(active)} "
        f"quotes={len(quotes)} analysed={checked} directional={directional} "
        f"errors={len(errors)} telegram_alerts_only=enabled"
    )


if __name__ == "__main__":
    main()
