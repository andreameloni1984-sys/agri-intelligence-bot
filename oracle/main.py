from datetime import datetime, timezone
from .config import UNIVERSE, MIN_ABS_NEWS_SCORE
from .news import collect_news
from .market import fetch_quotes
from .analysis import rank_news_opportunities, build_news_led_signal
from .calendar import fetch_economic_calendar
from .storage import save_result, save_scan_meta, save_quotes, save_calendar_events
from .notify import send_telegram


def main():
    started = datetime.now(timezone.utc)
    print(f"STELLA ROSSA scan started={started.isoformat()}")

    calendar = fetch_economic_calendar(days=45)
    save_calendar_events(calendar)
    print(f"[CALENDAR] upcoming_events={len(calendar)}")
    for event in calendar:
        print(f"[CALENDAR] {event['date_utc']} {event['country']} {event['event']} "
              f"importance={event['importance']} source={event['source']} url={event['url']}")

    # Intelligence selects the commodity first; price action never invents a news catalyst.
    news = collect_news()
    print(f"[NEWS] unique_recent_items={len(news)}")
    quotes = fetch_quotes()
    save_quotes(quotes)

    ranked = rank_news_opportunities(UNIVERSE, news, MIN_ABS_NEWS_SCORE)
    selected = {item["instrument"].symbol: item for item in ranked}
    print(f"[INTELLIGENCE] monitored={len(UNIVERSE)} news_selected={len(ranked)}")
    for rank, item in enumerate(ranked, 1):
        headlines = " | ".join(x.title for x in item["matched"][:2])
        print(f"[NEWS RANK {rank}] {item['instrument'].name} {item['direction']} "
              f"news_score={item['news_score']:+d} evidence={headlines}")

    directional = 0
    for instrument in UNIVERSE:
        opportunity = selected.get(instrument.symbol)
        if opportunity is None:
            signal, status = None, "NEWS_NOT_SELECTED"
        else:
            signal, status = build_news_led_signal(
                instrument, quotes.get(instrument.symbol),
                opportunity["news_score"], opportunity["matched"]
            )
        is_new = save_result(signal, instrument.name, instrument.symbol, status)
        if signal:
            directional += 1
            print(f"[SIGNAL] {signal.instrument} {signal.direction} "
                  f"news_score={signal.news_score:+d} confidence={signal.confidence} new={is_new}")
            if is_new:
                sent = send_telegram(signal)
                if not sent:
                    from .storage import delete_signal
                    delete_signal(signal)
        elif opportunity is not None:
            print(f"[SELECTED / WAIT] {instrument.name}: {status}")
        else:
            print(f"[MONITORED / NOT SELECTED] {instrument.name}: no qualifying news catalyst")

    save_scan_meta(started, len(news), len(UNIVERSE))
    print(f"[DONE] monitored={len(UNIVERSE)} news_selected={len(ranked)} "
          f"directional={directional}; research only.")


if __name__ == "__main__":
    main()
