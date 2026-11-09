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


def _candidate_to_dict(candidate):
    return {
        "symbol": candidate["instrument"].symbol,
        "direction": candidate["direction"],
        "news_score": candidate["news_score"],
        "matched": [_news_to_dict(item) for item in candidate["matched"]],
    }


def _dict_to_candidate(row):
    if not row:
        return None
    instrument = next((item for item in UNIVERSE if item.symbol == row.get("symbol")), None)
    if instrument is None:
        return None
    matched = [_dict_to_news(item) for item in row.get("matched", [])]
    if not matched:
        return None
    return {"instrument": instrument, "direction": row["direction"],
            "news_score": int(row["news_score"]), "matched": matched}


def _choose_one(ranked):
    """Concentrate the monitoring cycle on the single strongest news candidate."""
    return ranked[0] if ranked else None


def _should_run_cycle(news_scan_due, candidate):
    """Run when a news refresh is due or a single candidate is active."""
    return bool(news_scan_due or candidate is not None)


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
    cutoff = started - timedelta(hours=NEWS_CACHE_HOURS)
    cached_news = []
    for row in cached_rows:
        try:
            item = _dict_to_news(row)
            if item.published >= cutoff:
                cached_news.append(item)
        except (KeyError, TypeError, ValueError):
            continue

    if due:
        mode = "NEWS_SELECTION"
        try:
            fresh_news = collect_news()
            merged = {item.url: item for item in cached_news}
            merged.update({item.url: item for item in fresh_news if item.url})
            news = sorted(merged.values(), key=lambda x: x.published, reverse=True)
            ranked = rank_news_opportunities(UNIVERSE, news, MIN_ABS_NEWS_SCORE)
            candidate = _choose_one(ranked)
            save_scheduler_state("cached_news", [_news_to_dict(x) for x in news])
            save_scheduler_state("active_candidate", _candidate_to_dict(candidate) if candidate else None)
            save_scheduler_state("last_news_scan", started.isoformat())
            print(f"[NEWS] refreshed fresh={len(fresh_news)} candidates={len(ranked)}")
        except Exception as exc:
            errors.append(f"news:{type(exc).__name__}")
            news = cached_news
            candidate = _dict_to_candidate(get_scheduler_state("active_candidate"))
            mode = "NEWS_REFRESH_FAILED_KEEP_ACTIVE"
            print(f"[NEWS] refresh failed: {type(exc).__name__}; retaining active candidate")
    else:
        mode = "SINGLE_ASSET_MONITOR"
        news = cached_news
        candidate = _dict_to_candidate(get_scheduler_state("active_candidate"))
        print("[NEWS] refresh skipped; monitoring persisted single candidate")

    if not _should_run_cycle(due, candidate):
        print("[IDLE] no active candidate and news refresh not due; no quote, calendar or Telegram calls")
        return

    if due and mode == "NEWS_SELECTION":
        try:
            calendar = fetch_economic_calendar(days=45)
            save_calendar_events(calendar)
            print(f"[CALENDAR] refreshed events={len(calendar)}")
        except Exception as exc:
            errors.append(f"calendar:{type(exc).__name__}")
            print(f"[CALENDAR] refresh failed: {type(exc).__name__}")

    quotes = {}
    instrument = candidate["instrument"] if candidate else None
    if instrument:
        try:
            quotes = fetch_quotes([instrument.symbol])
            save_quotes(quotes)
        except Exception as exc:
            errors.append(f"quotes:{type(exc).__name__}")
            print(f"[MARKET] quote fetch failed: {type(exc).__name__}")
    else:
        print("[MARKET] no single news-backed candidate; no market quote request")

    directional = 0
    status = "NO_NEWS_CANDIDATE"
    if candidate and instrument:
        signal, status = build_news_led_signal(
            instrument, quotes.get(instrument.symbol),
            candidate["news_score"], candidate["matched"]
        )
        is_new = save_result(signal, instrument.name, instrument.symbol, status)
        if signal:
            directional = 1
            print(f"[SIGNAL] {signal.instrument} {signal.direction} "
                  f"news_score={signal.news_score:+d} confidence={signal.confidence} new={is_new}")
            if is_new and not send_telegram(signal):
                delete_signal(signal)
        else:
            print(f"[SELECTED / WAIT] {instrument.name} {candidate['direction']}: {status}")

    save_scan_meta(started, len(news), len(quotes))
    selected_label = (f"{instrument.name} {candidate['direction']} "
                      f"(news {candidate['news_score']:+d})") if candidate else "nessuna"
    outcome = f"SEGNALE {directional}" if directional else status
    heartbeat = (
        f"🛰️ STELLA ROSSA — CONTROLLO SCANSIONE\n"
        f"🕒 {started.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        f"Modalità: {mode} (notizie ogni {NEWS_SCAN_MINUTES} min)\n"
        f"Unica materia seguita: {selected_label}\n"
        f"Quotazioni valide: {len(quotes)}/{1 if candidate else 0}\n"
        f"Esito: {outcome}\n"
        f"Errori: {', '.join(errors) if errors else 'nessuno'}\n"
        f"Paper only — nessun ordine reale."
    )
    heartbeat_sent = send_telegram_status(heartbeat)
    print(f"[DONE] mode={mode} active={instrument.symbol if instrument else 'none'} "
          f"quotes={len(quotes)} directional={directional} heartbeat_sent={heartbeat_sent}")


if __name__ == "__main__":
    main()
