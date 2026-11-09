from datetime import datetime, timezone, timedelta
from .config import UNIVERSE, MIN_ABS_NEWS_SCORE
from .news import collect_news
from .market import fetch_quotes
from .analysis import rank_news_opportunities, build_news_led_signal
from .calendar import fetch_economic_calendar
from .storage import (
    save_result, save_scan_meta, save_quotes, save_calendar_events,
    get_scheduler_state, save_scheduler_state, delete_signal,
)
from .notify import send_telegram, send_telegram_status

NEWS_SCAN_MINUTES = 30
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
    started = datetime.now(timezone.utc)
    errors = []
    print(f"STELLA ROSSA scan started={started.isoformat()}")
    last_news_scan = get_scheduler_state("last_news_scan")
    due = True
    if last_news_scan:
        try:
            previous = datetime.fromisoformat(last_news_scan)
            if previous.tzinfo is None:
                previous = previous.replace(tzinfo=timezone.utc)
            due = started - previous >= timedelta(minutes=NEWS_SCAN_MINUTES)
        except (TypeError, ValueError):
            due = True

    cached_rows = get_scheduler_state("cached_news", [])
    cached_news = []
    cutoff = started - timedelta(hours=NEWS_CACHE_HOURS)
    for row in cached_rows:
        try:
            item = _dict_to_news(row)
            if item.published >= cutoff:
                cached_news.append(item)
        except (KeyError, TypeError, ValueError):
            continue

    if due:
        mode = "NEWS_REFRESH"
        try:
            fresh_news = collect_news()
            merged = {item.url: item for item in cached_news}
            merged.update({item.url: item for item in fresh_news if item.url})
            news = sorted(merged.values(), key=lambda x: x.published, reverse=True)
            save_scheduler_state("cached_news", [_news_to_dict(x) for x in news])
            save_scheduler_state("last_news_scan", started.isoformat())
            print(f"[NEWS] refreshed fresh={len(fresh_news)} retained={len(news)}")
        except Exception as exc:
            errors.append(f"news:{type(exc).__name__}")
            news = cached_news
            print(f"[NEWS] refresh failed: {type(exc).__name__}; using cached={len(news)}")
    else:
        mode = "ACTIVE_MONITOR"
        news = cached_news
        print(f"[NEWS] refresh skipped; cached={len(news)}")

    ranked = rank_news_opportunities(UNIVERSE, news, MIN_ABS_NEWS_SCORE)
    selected = {item["instrument"].symbol: item for item in ranked}
    symbols = [item.symbol for item in UNIVERSE if item.symbol in selected]
    names = [item["instrument"].name for item in ranked]
    print(f"[INTELLIGENCE] mode={mode} news_selected={len(ranked)} instruments={','.join(names) or 'none'}")

    if due:
        try:
            calendar = fetch_economic_calendar(days=45)
            save_calendar_events(calendar)
            print(f"[CALENDAR] refreshed events={len(calendar)}")
        except Exception as exc:
            errors.append(f"calendar:{type(exc).__name__}")
            print(f"[CALENDAR] refresh failed: {type(exc).__name__}")

    quotes = {}
    if symbols:
        try:
            quotes = fetch_quotes(symbols)
            save_quotes(quotes)
        except Exception as exc:
            errors.append(f"quotes:{type(exc).__name__}")
            print(f"[MARKET] quote fetch failed: {type(exc).__name__}")
    else:
        print("[MARKET] no news-selected commodity; quote request skipped")

    directional = 0
    for instrument in UNIVERSE:
        opportunity = selected.get(instrument.symbol)
        if opportunity is None:
            continue
        signal, status = build_news_led_signal(
            instrument, quotes.get(instrument.symbol),
            opportunity["news_score"], opportunity["matched"]
        )
        is_new = save_result(signal, instrument.name, instrument.symbol, status)
        if signal:
            directional += 1
            print(f"[SIGNAL] {signal.instrument} {signal.direction} "
                  f"news_score={signal.news_score:+d} confidence={signal.confidence} new={is_new}")
            if is_new and not send_telegram(signal):
                delete_signal(signal)
        else:
            print(f"[SELECTED / WAIT] {instrument.name}: {status}")

    save_scan_meta(started, len(news), len(quotes))
    outcome = f"SEGNALI: {directional}" if directional else "NESSUN SEGNALE"
    heartbeat = (
        f"🛰️ STELLA ROSSA — CONTROLLO SCANSIONE\n"
        f"🕒 {started.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        f"Modalità: {mode} (notizie ogni {NEWS_SCAN_MINUTES} min)\n"
        f"Notizie in archivio: {len(news)}\n"
        f"Materie selezionate: {', '.join(names) if names else 'nessuna'}\n"
        f"Quotazioni valide: {len(quotes)}/{len(symbols)} selezionate\n"
        f"Esito: {outcome}\n"
        f"Errori: {', '.join(errors) if errors else 'nessuno'}\n"
        f"Ricerca informativa / paper only — nessun ordine."
    )
    heartbeat_sent = send_telegram_status(heartbeat)
    print(f"[DONE] mode={mode} news={len(news)} selected={len(symbols)} "
          f"quotes={len(quotes)} directional={directional} heartbeat_sent={heartbeat_sent}")


if __name__ == "__main__":
    main()
