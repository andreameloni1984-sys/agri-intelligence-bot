from datetime import datetime, timezone
from .config import UNIVERSE
from .news import collect_news
from .market import fetch_quotes
from .analysis import build_signal
from .calendar import fetch_economic_calendar
from .storage import save_result, save_scan_meta, save_quotes, save_calendar_events
from .notify import send_telegram
from .telegram_commands import poll_telegram_commands


def main():
    started = datetime.now(timezone.utc)
    print(f"ORACLE scan started={started.isoformat()}")
    calendar = fetch_economic_calendar(days=45)
    save_calendar_events(calendar)
    print(f"[CALENDAR] upcoming_events={len(calendar)}")
    for event in calendar:
        print(f"[CALENDAR] {event['date_utc']} {event['country']} {event['event']} "
              f"importance={event['importance']} source={event['source']} url={event['url']}")
    news = collect_news()
    print(f"[NEWS] unique_recent_items={len(news)}")
    quotes = fetch_quotes()
    save_quotes(quotes)
    directional = 0
    for instrument in UNIVERSE:
        signal, status = build_signal(instrument, quotes.get(instrument.symbol), news)
        is_new = save_result(signal, instrument.name, instrument.symbol, status)
        if signal:
            directional += 1
            print(f"[SIGNAL] {signal.instrument} {signal.direction} confidence={signal.confidence} new={is_new}")
            if is_new:
                send_telegram(signal)
        else:
            print(f"[NO SIGNAL] {instrument.name}: {status}")
    save_scan_meta(started, len(news), len(UNIVERSE))
    print(f"[DONE] instruments={len(UNIVERSE)} quotes={len(quotes)} directional={directional}; research only.")
    poll_telegram_commands()


if __name__ == "__main__":
    main()
