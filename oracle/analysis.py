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

# Fast, local catalyst rules inspired by SPUTNIK's event-to-market pipeline.
# They run only on news already collected by the existing scan: no extra HTTP calls.
CATALYST_RULES = {
    "Gold": {
        2: ("geopolitical escalation", "military strike", "armed conflict", "safe haven demand",
            "central bank buying", "central banks buy", "gold purchases", "rate cut", "fed cuts rates",
            "real yields fall", "dollar weakens", "dollar falls", "sanctions escalation"),
        -2: ("real yields rise", "dollar strengthens", "dollar rises", "rate hike",
             "fed raises rates", "central bank selling", "gold sales"),
    },
    "Copper": {
        2: ("china stimulus", "china announces stimulus", "manufacturing expansion",
            "factory activity expands", "mine disruption", "copper mine strike",
            "copper supply disruption", "smelter outage", "china imports rise"),
        -2: ("china slowdown", "china manufacturing contracts", "manufacturing contraction",
             "factory activity contracts", "copper demand slump", "mine restart",
             "copper production increase", "trade war escalation"),
    },
    "Platinum": {
        2: ("platinum mine disruption", "mine disruption", "supply disruption",
            "mine strike", "auto demand recovery", "platinum demand increase"),
        -2: ("auto demand slump", "production increase", "platinum supply increase",
             "vehicle production falls", "auto sales decline"),
    },
    "Palladium": {
        2: ("palladium mine disruption", "mine disruption", "supply disruption",
            "mine strike", "auto demand recovery", "vehicle production rises"),
        -2: ("auto demand slump", "production increase", "palladium supply increase",
             "vehicle production falls", "auto sales decline", "electric vehicle share rises"),
    },
    "WTI": {
        2: ("opec production cut", "opec cuts output", "oil supply disruption",
            "crude supply disruption", "middle east escalation", "hormuz closure",
            "us crude inventory draw", "crude stocks fall", "oil exports halt"),
        -2: ("opec raises production", "oil production increase", "crude inventory build",
             "crude stocks rise", "us crude inventory build", "demand slump",
             "ceasefire", "shipping routes reopen"),
    },
    "Brent": {
        2: ("opec production cut", "opec cuts output", "oil supply disruption",
            "shipping disruption", "tanker attack", "hormuz closure",
            "middle east escalation", "oil exports halt"),
        -2: ("opec raises production", "oil production increase", "global demand slump",
             "ceasefire", "shipping routes reopen", "supply restored"),
    },
    "Wheat": {
        2: ("wheat export ban", "wheat export restriction", "drought", "crop damage",
            "wheat harvest downgrade", "wheat production forecast cut", "black sea disruption"),
        -2: ("wheat harvest forecast increase", "bumper wheat crop", "wheat production forecast raised",
             "wheat export resumption", "record wheat harvest"),
    },
    "Corn": {
        2: ("corn export ban", "corn export restriction", "drought", "crop damage",
            "corn harvest downgrade", "ethanol demand increase", "corn production forecast cut"),
        -2: ("corn harvest forecast increase", "bumper corn crop", "corn production forecast raised",
             "record corn harvest", "ethanol demand decline"),
    },
    "Soybeans": {
        2: ("soybean export ban", "soybean export restriction", "drought", "crop damage",
            "china import demand", "china buys soybeans", "soybean harvest downgrade",
            "soybean production forecast cut"),
        -2: ("china import decline", "china cancels soybean purchases",
             "soybean harvest forecast increase", "bumper soybean crop",
             "soybean production forecast raised", "record soybean harvest"),
    },
}

def _phrase_present(text: str, phrase: str) -> bool:
    """Ignore a catalyst phrase when it is explicitly negated nearby."""
    position = text.find(phrase)
    if position < 0:
        return False
    prefix = text[max(0, position - 35):position]
    return not any(token in prefix for token in (
        "no ", "not ", "without ", "deny ", "denies ", "denied ",
        "reject ", "rejects ", "rejected ", "unlikely to ",
    ))

def score_news(instrument, news: list[NewsItem]):
    """Score dated, already-fetched asset catalysts; no network or blocking work."""
    legacy = ASSET_EFFECTS.get(instrument.name, {})
    rules = CATALYST_RULES.get(instrument.name, {})
    total, matched = 0, []
    for item in news:
        text = f"{item.title} {item.summary}".lower()
        item_score = sum(weight for phrase, weight in legacy.items() if _phrase_present(text, phrase))
        for weight, phrases in rules.items():
            if any(_phrase_present(text, phrase) for phrase in phrases):
                item_score += weight
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
        notes.append(f"RSI14={quote.rsi14:.1f} strong bullish momentum (extended)")
    elif quote.rsi14 < 25:
        notes.append(f"RSI14={quote.rsi14:.1f} strong bearish momentum (extended)")
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
    if long_score >= 2 and long_score > short_score:
        return long_score, notes
    if short_score >= 2 and short_score > long_score:
        return -short_score, notes
    return 0, notes

def classify_market_state(quote: Quote):
    """Separate the EMA50/200 primary trend from the current 15m swing."""
    if quote.ema50 is None or quote.ema200 is None or quote.rsi14 is None:
        return "NON DISPONIBILE", "NON DISPONIBILE", "indicatori incompleti"
    if quote.ema50 > quote.ema200:
        trend = "RIALZISTA"
    elif quote.ema50 < quote.ema200:
        trend = "RIBASSISTA"
    else:
        trend = "NEUTRALE"
    if quote.last > quote.ema50 and quote.rsi14 >= 52:
        swing = "RIALZISTA"
    elif quote.last < quote.ema50 and quote.rsi14 <= 48:
        swing = "RIBASSISTA"
    else:
        swing = "MISTO"
    if trend == "RIBASSISTA" and swing == "RIALZISTA":
        interpretation = "rimbalzo rialzista contro trend"
    elif trend == "RIALZISTA" and swing == "RIBASSISTA":
        interpretation = "correzione ribassista contro trend"
    elif trend == swing and trend != "NEUTRALE":
        interpretation = "trend e movimento breve concordi"
    else:
        interpretation = "movimento breve non conferma il trend"
    return trend, swing, interpretation

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
    setup_type = "CONFIRMED" if abs(technical_score) >= 3 else "EARLY_SETUP"
    news_score, matched = score_news(instrument, news)
    # News is contextual confirmation/contradiction, never a prerequisite for a technical setup.
    if (direction == "LONG" and news_score <= -2) or (direction == "SHORT" and news_score >= 2):
        return None, "NEWS_CONTRADICTS_TECHNICAL"
    move_pct = ((quote.last / quote.previous_close) - 1) * 100
    confidence = min(85, max(50, 50 + min(24, abs(technical_score) * 6) +
                             min(8, abs(move_pct) * 2) + (4 if news_score and news_score * technical_score > 0 else 0)))
    if setup_type == "EARLY_SETUP":
        confidence = min(confidence, 59)
    risk = 1.5 * quote.atr
    if direction == "LONG":
        sl, tp1, tp2 = quote.last - risk, quote.last + risk * 1.5, quote.last + risk * 2.5
    else:
        sl, tp1, tp2 = quote.last + risk, quote.last - risk * 1.5, quote.last - risk * 2.5
    news_note = f"news score {news_score:+d}" if matched else "no matching asset-specific news"
    trend, swing, interpretation = classify_market_state(quote)
    rationale = (f"Primary trend {trend}; short-term move {swing} ({interpretation}); "
                 f"Technical score {technical_score:+d}; {', '.join(technical_notes)}; "
                 f"15m price change {move_pct:+.3f}%; quote age {int(age)}m; {news_note}. "
                 "Confidence is a heuristic score, not a probability. SL/TP are ATR-based research levels.")
    return Signal(instrument.name, instrument.symbol, direction, int(confidence), news_score,
                  move_pct, quote.last, sl, tp1, tp2, rationale, [x.url for x in matched[:5]], now,
                  setup_type), ("SIGNAL" if setup_type == "CONFIRMED" else "EARLY_SETUP")


def rank_news_opportunities(instruments, news: list[NewsItem], minimum_score: int = 2):
    """Rank all monitored commodities by asset-specific, dated news catalysts."""
    ranked = []
    for instrument in instruments:
        score, matched = score_news(instrument, news)
        if abs(score) < minimum_score or not matched:
            continue
        ranked.append({
            "instrument": instrument,
            "direction": "LONG" if score > 0 else "SHORT",
            "news_score": score,
            "matched": matched,
        })
    return sorted(ranked, key=lambda item: (abs(item["news_score"]), item["matched"][0].published), reverse=True)


def build_news_led_signal(instrument, quote: Quote | None, news_score: int, matched: list[NewsItem]):
    """Create a signal only when news selects the asset and technicals confirm its direction."""
    now = datetime.now(timezone.utc)
    if abs(news_score) < 2 or not matched:
        return None, "NEWS_NOT_SELECTED"
    if quote is None:
        return None, "NEWS_SELECTED_NO_QUOTE"
    age = (now - quote.timestamp).total_seconds() / 60
    if age < -5 or age > MAX_QUOTE_AGE_MINUTES:
        return None, f"STALE_QUOTE_{int(age)}m"
    if quote.atr <= 0 or quote.last <= 0 or quote.previous_close <= 0:
        return None, "INVALID_MARKET_DATA"

    direction = "LONG" if news_score > 0 else "SHORT"
    technical_score, technical_notes = technical_reading(quote)
    if technical_score == 0:
        return None, "WAIT_TECHNICAL_NOT_CONFIRMED"
    technical_direction = "LONG" if technical_score > 0 else "SHORT"
    if technical_direction != direction:
        return None, f"WAIT_TECHNICAL_CONFLICT_NEWS_{direction}_TECH_{technical_direction}"

    setup_type = "CONFIRMED" if abs(technical_score) >= 3 else "EARLY_SETUP"
    move_pct = ((quote.last / quote.previous_close) - 1) * 100
    confidence = min(85, 50 + min(20, abs(news_score) * 4) + min(15, abs(technical_score) * 3))
    if setup_type == "EARLY_SETUP":
        confidence = min(confidence, 59)
    risk = 1.5 * quote.atr
    if direction == "LONG":
        sl, tp1, tp2 = quote.last - risk, quote.last + risk * 1.5, quote.last + risk * 2.5
    else:
        sl, tp1, tp2 = quote.last + risk, quote.last - risk * 1.5, quote.last - risk * 2.5
    trend, swing, interpretation = classify_market_state(quote)
    evidence = "; ".join(f"{item.source}: {item.title}" for item in matched[:3])
    rationale = (
        f"News-led selection: catalyst score {news_score:+d}; evidence: {evidence}. "
        f"Technical confirmation {technical_direction} (score {technical_score:+d}); "
        f"primary trend {trend}; short-term move {swing} ({interpretation}); "
        f"15m price change {move_pct:+.3f}%; quote age {int(age)}m. "
        "Confidence is a heuristic score, not a probability. SL/TP are ATR-based research levels."
    )
    return Signal(instrument.name, instrument.symbol, direction, int(confidence), news_score,
                  move_pct, quote.last, sl, tp1, tp2, rationale,
                  [item.url for item in matched[:5]], now, setup_type), (
                      "SIGNAL" if setup_type == "CONFIRMED" else "EARLY_SETUP"
                  )
