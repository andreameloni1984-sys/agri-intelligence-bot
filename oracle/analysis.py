from datetime import datetime, timezone
from .config import MAX_QUOTE_AGE_MINUTES
from .models import NewsItem, Quote, Signal

ASSET_EFFECTS = {
    "Gold": {"central bank buying": 2, "geopolitical escalation": 2, "safe haven demand": 2, "real yields rise": -2, "dollar strengthens": -2, "rate cut": 1, "rate hike": -1},
    "Copper": {"china stimulus": 2, "manufacturing expansion": 2, "mine disruption": 2, "china slowdown": -2, "manufacturing contraction": -2, "mine restart": -1},
    "Platinum": {"mine disruption": 2, "supply disruption": 2, "auto demand recovery": 1, "auto demand slump": -2, "production increase": -1},
    "Palladium": {"mine disruption": 2, "supply disruption": 2, "auto demand recovery": 1, "auto demand slump": -2, "production increase": -1},
    "WTI": {"opec production cut": 2, "supply disruption": 2, "sanctions on oil": 1, "inventory build": -2, "production increase": -2, "demand slump": -2},
    "Brent": {"opec production cut": 2, "shipping disruption": 2, "supply disruption": 2, "sanctions on oil": 1, "inventory build": -1, "production increase": -2, "demand slump": -2},
    "Wheat": {"wheat export ban": 2, "drought": 2, "crop damage": 2, "harvest forecast increase": -2, "export resumption": -1},
    "Corn": {"corn export ban": 2, "drought": 2, "crop damage": 2, "ethanol demand increase": 1, "harvest forecast increase": -2},
    "Soybeans": {"soybean export ban": 2, "drought": 2, "crop damage": 2, "china import demand": 2, "harvest forecast increase": -2, "china import decline": -2},
}

def score_news(instrument, news: list[NewsItem]):
    effects, total, matched = ASSET_EFFECTS.get(instrument.name, {}), 0, []
    for item in news:
        text = f"{item.title} {item.summary}".lower()
        item_score = sum(weight for phrase, weight in effects.items() if phrase in text)
        item_score = max(-2, min(2, item_score))
        if item_score:
            total += item_score
            matched.append(item)
    return max(-6, min(6, total)), matched

def technical_reading(quote: Quote):
    """Return a transparent directional score from trend, momentum and structure."""
    long_score = short_score = 0
    notes = []
    if quote.ema50 is None or quote.ema200 is None or quote.rsi14 is None:
        return 0, ["indicator set incomplete"]
    if quote.ema50 > quote.ema200:
        long_score += 2
        notes.append("EMA50 above EMA200")
    elif quote.ema50 < quote.ema200:
        short_score += 2
        notes.append("EMA50 below EMA200")
    if quote.last > quote.ema50:
        long_score += 1
        notes.append("price above EMA50")
    elif quote.last < quote.ema50:
        short_score += 1
        notes.append("price below EMA50")
    if 52 <= quote.rsi14 <= 68:
        long_score += 1
        notes.append(f"RSI14={quote.rsi14:.1f} bullish")
    elif 32 <= quote.rsi14 <= 48:
        short_score += 1
        notes.append(f"RSI14={quote.rsi14:.1f} bearish")
    elif quote.rsi14 > 75:
        long_score -= 1
        notes.append(f"RSI14={quote.rsi14:.1f} overbought")
    elif quote.rsi14 < 25:
        short_score -= 1
        notes.append(f"RSI14={quote.rsi14:.1f} oversold")
    if quote.structure_high is not None and quote.last > quote.structure_high:
        long_score += 2
        notes.append("20-candle high breakout")
    if quote.structure_low is not None and quote.last < quote.structure_low:
        short_score += 2
        notes.append("20-candle low breakdown")
    if quote.last > quote.previous_close:
        long_score += 1
        notes.append("latest candle positive")
    elif quote.last < quote.previous_close:
        short_score += 1
        notes.append("latest candle negative")
    if long_score >= 3 and long_score > short_score:
        return long_score, notes
    if short_score >= 3 and short_score > long_score:
        return -short_score, notes
    return 0, notes

def build_signal(instrument, quote: Quote | None, news: list[NewsItem]):
    now = datetime.now(timezone.utc)
    if quote is None:
        return None, "NO_QUOTE"
    age = (now - quote.timestamp).total_seconds() / 60
    if age < -5 or age > MAX_QUOTE_AGE_MINUTES:
        return None, f"STALE_QUOTE_{int(age)}m"
    if quote.atr <= 0 or quote.last <= 0 or quote.previous_close <= 0:
        return None, "INVALID_MARKET_DATA"
    technical_score, technical_notes = technical_reading(quote)
    if technical_score == 0:
        return None, "TECHNICAL_SETUP_NOT_CONFIRMED"
    direction = "LONG" if technical_score > 0 else "SHORT"
    news_score, matched = score_news(instrument, news)
    # News is contextual confirmation/contradiction, never a prerequisite for a technical setup.
    if (direction == "LONG" and news_score <= -2) or (direction == "SHORT" and news_score >= 2):
        return None, "NEWS_CONTRADICTS_TECHNICAL"
    move_pct = ((quote.last / quote.previous_close) - 1) * 100
    confidence = min(85, max(50, 50 + min(24, abs(technical_score) * 6) +
                             min(8, abs(move_pct) * 2) + (4 if news_score and news_score * technical_score > 0 else 0)))
    risk = 1.5 * quote.atr
    if direction == "LONG":
        sl, tp1, tp2 = quote.last - risk, quote.last + risk * 1.5, quote.last + risk * 2.5
    else:
        sl, tp1, tp2 = quote.last + risk, quote.last - risk * 1.5, quote.last - risk * 2.5
    news_note = f"news score {news_score:+d}" if matched else "no matching asset-specific news"
    rationale = (f"Technical score {technical_score:+d}; {', '.join(technical_notes)}; "
                 f"15m price change {move_pct:+.3f}%; quote age {int(age)}m; {news_note}. "
                 "Confidence is a heuristic score, not a probability. SL/TP are ATR-based research levels.")
    return Signal(instrument.name, instrument.symbol, direction, int(confidence), news_score,
                  move_pct, quote.last, sl, tp1, tp2, rationale, [x.url for x in matched[:5]], now), "SIGNAL"
