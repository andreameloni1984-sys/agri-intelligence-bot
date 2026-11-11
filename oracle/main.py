from datetime import datetime, timezone, timedelta
from .config import UNIVERSE
from .news import collect_news
from .market import fetch_quotes
from .analysis import build_signal, score_news, build_pre_news_scenario
from .calendar import fetch_economic_calendar, relevant_events
from .storage import (
    save_result, save_scan_meta, save_quotes, save_calendar_events,
    get_scheduler_state, save_scheduler_state, delete_signal,
)
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

    # Official schedules change infrequently: refresh every six hours, not every
    # five-minute wake-up. Retain the last successful schedule on source failure.
    calendar_events = get_scheduler_state("cached_calendar", [])
    last_calendar_scan = get_scheduler_state("last_calendar_scan")
    calendar_due = True
    if last_calendar_scan:
        try:
            previous = datetime.fromisoformat(last_calendar_scan)
            if previous.tzinfo is None:
                previous = previous.replace(tzinfo=timezone.utc)
            calendar_due = started - previous >= timedelta(hours=6)
        except (TypeError, ValueError):
            calendar_due = True

    if calendar_due:
        try:
            fresh_calendar = fetch_economic_calendar(days=45)
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

    # GitHub Actions has a static cron, so it wakes every five minutes only to
    # evaluate the cached official schedule. Market/news downloads begin only
    # 30 minutes before a mapped release, and continue for 120 minutes after it.
    # Outside those windows this exits before news, quotes, technical analysis or alerts.
    active = {}
    for instrument in UNIVERSE:
        context = relevant_events(instrument, calendar_events, now=started)
        context = [
            item for item in context
            if item["phase"] == "APPENA PUBBLICATO"
            or (item["phase"] == "IN ARRIVO" and item["minutes_to_event"] <= 30)
        ]
        if context:
            active[instrument] = context

    if not active:
        print("[IDLE] no relevant release within 30m or in the 120m post-release window; market scan skipped")
        save_scan_meta(started, 0, 0)
        return

    print("[EVENT WINDOW] " + ", ".join(
        f"{instrument.name}({len(context)})" for instrument, context in active.items()
    ))

    # Headlines are collected only when a mapped event activates the relevant markets.
    try:
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
                is_new = save_result(signal, instrument.name, instrument.symbol, status)
                directional += 1
                print(
                    f"[SIGNAL] {signal.instrument} {signal.direction} status={status} "
                    f"news_score={news_score:+d} calendar_events={len(event_context)} "
                    f"confidence={signal.confidence} new={is_new}"
                )
                if is_new and not send_telegram(signal):
                    delete_signal(signal)
            else:
                print(
                    f"[WAIT] {instrument.name}: {status} news_score={news_score:+d} "
                    f"calendar_events={len(event_context)}"
                )
        except Exception as exc:
            errors.append(f"{instrument.symbol}:{type(exc).__name__}")
            print(f"[ANALYSIS] {instrument.name} failed: {type(exc).__name__}")

    save_scan_meta(started, len(news), checked)
    print(
        f"[DONE] event_driven=true active_markets={len(active)} "
        f"quotes={len(quotes)} analysed={checked} directional={directional} "
        f"errors={len(errors)} telegram_alerts_only=enabled"
    )


if __name__ == "__main__":
    main()
