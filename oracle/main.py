from datetime import datetime, timezone, timedelta
from .config import UNIVERSE
from .news import collect_news
from .market import fetch_quotes
from .analysis import build_signal, score_news
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
    """Scan all markets every invocation; calendar/news enrich context, never gate analysis."""
    started = datetime.now(timezone.utc)
    errors = []
    print(f"STELLA ROSSA scan started={started.isoformat()} universe={len(UNIVERSE)}")

    last_news_scan = get_scheduler_state("last_news_scan")
    news_due = True
    if last_news_scan:
        try:
            previous = datetime.fromisoformat(last_news_scan)
            if previous.tzinfo is None:
                previous = previous.replace(tzinfo=timezone.utc)
            news_due = started - previous >= timedelta(minutes=NEWS_SCAN_MINUTES)
        except (TypeError, ValueError):
            news_due = True

    cutoff = started - timedelta(hours=NEWS_CACHE_HOURS)
    cached_news = []
    for row in get_scheduler_state("cached_news", []):
        try:
            item = _dict_to_news(row)
            if item.published >= cutoff:
                cached_news.append(item)
        except (KeyError, TypeError, ValueError):
            continue

    news = cached_news
    if news_due:
        try:
            fresh_news = collect_news()
            merged = {item.url: item for item in cached_news if item.url}
            merged.update({item.url: item for item in fresh_news if item.url})
            news = sorted(merged.values(), key=lambda item: item.published, reverse=True)
            save_scheduler_state("cached_news", [_news_to_dict(item) for item in news])
            save_scheduler_state("last_news_scan", started.isoformat())
            print(f"[NEWS] refreshed fresh={len(fresh_news)} retained={len(news)}")
        except Exception as exc:
            errors.append(f"news:{type(exc).__name__}")
            print(f"[NEWS] refresh failed: {type(exc).__name__}; using cached news={len(news)}")
    else:
        print(f"[NEWS] refresh not due; using cached news={len(news)}")

    # Refresh the official calendar on the five-minute cadence and reuse the
    # last successful copy if a publisher is temporarily unavailable.
    calendar_events = get_scheduler_state("cached_calendar", [])
    last_calendar_scan = get_scheduler_state("last_calendar_scan")
    calendar_due = True
    if last_calendar_scan:
        try:
            previous = datetime.fromisoformat(last_calendar_scan)
            if previous.tzinfo is None:
                previous = previous.replace(tzinfo=timezone.utc)
            calendar_due = started - previous >= timedelta(minutes=NEWS_SCAN_MINUTES)
        except (TypeError, ValueError):
            calendar_due = True
    if calendar_due:
        try:
            fresh_calendar = fetch_economic_calendar(days=45)
            if fresh_calendar:
                calendar_events = fresh_calendar
                save_calendar_events(calendar_events)
                save_scheduler_state("cached_calendar", calendar_events)
            save_scheduler_state("last_calendar_scan", started.isoformat())
            print(f"[CALENDAR] refreshed events={len(fresh_calendar)} cached={len(calendar_events)}")
        except Exception as exc:
            errors.append(f"calendar:{type(exc).__name__}")
            print(f"[CALENDAR] refresh failed: {type(exc).__name__}; using cached events={len(calendar_events)}")
    else:
        print(f"[CALENDAR] refresh not due; using cached events={len(calendar_events)}")

    symbols = [instrument.symbol for instrument in UNIVERSE]
    try:
        quotes = fetch_quotes(symbols)
        save_quotes(quotes)
    except Exception as exc:
        errors.append(f"quotes:{type(exc).__name__}")
        quotes = {}
        print(f"[MARKET] batch quote fetch failed: {type(exc).__name__}")

    directional = 0
    checked = 0
    for instrument in UNIVERSE:
        quote = quotes.get(instrument.symbol)
        if quote is None:
            print(f"[MARKET] {instrument.name}: quote unavailable/stale; no signal")
            continue
        checked += 1
        try:
            news_score, matched = score_news(instrument, news)
            event_context = relevant_events(instrument, calendar_events, now=started)\n            signal, status = build_signal(instrument, quote, news, calendar_context=event_context)
            if signal:
                signal.news_score = news_score
                signal.news_urls = [item.url for item in matched[:5]]
                is_new = save_result(signal, instrument.name, instrument.symbol, status)
                directional += 1
                print(f"[SIGNAL] {signal.instrument} {signal.direction} status={status} "
                      f"news_score={news_score:+d} calendar_events={len(event_context)} "
                      f"confidence={signal.confidence} new={is_new}")
                if is_new and not send_telegram(signal):
                    delete_signal(signal)
            else:
                print(f"[WAIT] {instrument.name}: {status} news_score={news_score:+d} "
                      f"calendar_events={len(event_context)}")
        except Exception as exc:
            errors.append(f"{instrument.symbol}:{type(exc).__name__}")
            print(f"[ANALYSIS] {instrument.name} failed: {type(exc).__name__}")

    save_scan_meta(started, len(news), checked)
    print(f"[DONE] markets={len(UNIVERSE)} quotes={len(quotes)} "
          f"analysed={checked} directional={directional} errors={len(errors)} "
          f"telegram_alerts_only=enabled")


if __name__ == "__main__":
    main()
