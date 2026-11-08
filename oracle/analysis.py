from datetime import datetime, timezone
from .config import MAX_QUOTE_AGE_MINUTES, MIN_ABS_NEWS_SCORE, MIN_CONFIDENCE
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

def build_signal(instrument, quote: Quote | None, news: list[NewsItem]):
    now = datetime.now(timezone.utc)
    if quote is None:
        return None, "NO_QUOTE"
    age = (now - quote.timestamp).total_seconds() / 60
    if age < -5 or age > MAX_QUOTE_AGE_MINUTES:
        return None, f"STALE_QUOTE_{int(age)}m"
    news_score, matched = score_news(instrument, news)
    if abs(news_score) < MIN_ABS_NEWS_SCORE or not matched:
        return None, "NO_ASSET_SPECIFIC_CATALYST"
    move_pct = ((quote.last / quote.previous_close) - 1) * 100 if quote.previous_close else 0
    direction = "LONG" if news_score > 0 else "SHORT"
    aligned = (move_pct > 0 and direction == "LONG") or (move_pct < 0 and direction == "SHORT")
    if not aligned:
        return None, "PRICE_CONFIRMATION_MISSING"
    if quote.atr <= 0:
        return None, "INVALID_ATR"
    confidence = min(85, 50 + abs(news_score) * 5 + min(10, abs(move_pct) * 3))
    if confidence < MIN_CONFIDENCE:
        return None, "CONFIDENCE_FAIL"
    risk = 1.5 * quote.atr
    if direction == "LONG":
        sl, tp1, tp2 = quote.last - risk, quote.last + risk * 1.5, quote.last + risk * 2.5
    else:
        sl, tp1, tp2 = quote.last + risk, quote.last - risk * 1.5, quote.last - risk * 2.5
    rationale = (f"Asset-specific news score {news_score:+d}; 15m price change {move_pct:+.3f}%; "
                 f"quote age {int(age)}m. Rule-based hypothesis, not a validated probability.")
    return Signal(instrument.name, instrument.symbol, direction, int(confidence), news_score,
                  move_pct, quote.last, sl, tp1, tp2, rationale, [x.url for x in matched[:5]], now), "SIGNAL"
