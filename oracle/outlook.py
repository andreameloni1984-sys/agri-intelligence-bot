"""Daily next-session market outlook: technical bias first, news/calendar context second."""
from datetime import datetime, timezone, timedelta
import requests

from .config import UNIVERSE, MAX_QUOTE_AGE_MINUTES, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from .market import fetch_quotes
from .news import collect_news
from .analysis import technical_reading, score_news, classify_market_state
from .calendar import fetch_economic_calendar

def build_outlook(quotes, news, events, now=None):
    now = now or datetime.now(timezone.utc)
    lines = [
        "☭ КРАСНАЯ ЗВЕЗДА — PROSPETTIVA MERCATI",
        f"Prossima seduta | {now.astimezone().strftime('%d/%m/%Y %H:%M %Z')}",
        "Direzione preliminare, non segnale operativo.",
        "━━━━━━━━━━━━━━━━━━",
    ]
    for instrument in UNIVERSE:
        quote = quotes.get(instrument.symbol)
        if quote is None:
            lines.append(f"• {instrument.name}: DATI NON DISPONIBILI — nessuna previsione")
            continue
        age = (now - quote.timestamp).total_seconds() / 60
        if age < -5 or age > MAX_QUOTE_AGE_MINUTES:
            lines.append(f"• {instrument.name}: DATI OBSOLETI ({int(age)} min) — nessuna previsione")
            continue
        score, notes = technical_reading(quote)
        news_score, matched = score_news(instrument, news)
        if score > 0:
            bias = "LONG"
        elif score < 0:
            bias = "SHORT"
        else:
            bias = "NEUTRAL / ATTESA"
        warning = ""
        if (bias == "LONG" and news_score <= -2) or (bias == "SHORT" and news_score >= 2):
            warning = " | NOTIZIE CONTRARIE"
        elif matched and news_score * score > 0:
            warning = " | notizie concordi"
        trend, swing, interpretation = classify_market_state(quote)
        detail = ", ".join(notes[:3]) if notes else "confluenza tecnica insufficiente"
        lines.append(f"• {instrument.name}: {bias}{warning} | score tecnico {score:+d} | news {news_score:+d}")
        lines.append(f"  Trend principale: {trend} | Breve periodo: {swing} — {interpretation}")
        lines.append(f"  {detail}; prezzo {quote.last:.4f}; aggiornamento {int(age)} min fa")
    upcoming = [e for e in events if now <= datetime.fromisoformat(e["date_utc"]) <= now + timedelta(hours=36)]
    lines.extend(["━━━━━━━━━━━━━━━━━━", "CALENDARIO — prossime 36 ore"])
    if upcoming:
        for event in upcoming[:6]:
            stamp = datetime.fromisoformat(event["date_utc"]).astimezone()
            lines.append(f"• {stamp.strftime('%d/%m %H:%M')} — {event['event']} ({event['source']})")
    else:
        lines.append("• Nessun evento ufficiale rilevato nelle prossime 36 ore.")
    lines.extend([
        "━━━━━━━━━━━━━━━━━━",
        "Trend principale: EMA50/EMA200. Breve periodo: prezzo vs EMA50 e RSI14.",
        "Lettura tecnica su candele 15m; notizie come contesto secondario.",
        "Prezzi Yahoo Finance: possibili ritardi. Nessun ordine eseguito.",
        "Confidenza non espressa: questa è una mappa direzionale, non una probabilità.",
    ])
    return "\n".join(lines)

def main():
    print("[OUTLOOK] collecting calendar, news and quotes")
    events = fetch_economic_calendar(days=3)
    news = collect_news()
    quotes = fetch_quotes()
    message = build_outlook(quotes, news, events)
    print(message)
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[OUTLOOK] Telegram credentials missing; report printed only")
        return
    response = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
        timeout=20,
    )
    response.raise_for_status()
    if not response.json().get("ok"):
        raise RuntimeError("Telegram did not accept the daily outlook")
    print("[OUTLOOK] Telegram accepted daily outlook")

if __name__ == "__main__":
    main()
