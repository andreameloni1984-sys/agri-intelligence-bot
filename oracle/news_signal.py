"""Conservative news + fresh 5-minute price confirmation; informational paper alerts only."""
import logging
from datetime import datetime, timezone
from urllib.parse import quote

import requests

SYMBOLS = {
    "Gold": "GC=F", "Copper": "HG=F", "Platinum": "PL=F",
    "WTI": "CL=F", "Brent": "BZ=F", "Wheat": "ZW=F",
    "Corn": "ZC=F", "Soybeans": "ZS=F",
}
UP = ("rises", "rallies", "gains", "surges", "climbs", "jumps", "rebounds")
DOWN = ("falls", "drops", "slides", "slide", "slumps", "declines", "sinks", "plunges", "weakens", "tumbles")


def headline_direction(title, asset):
    """Only accept explicit price-action verbs attached to the instrument."""
    lower = title.lower()
    subjects = {
        "Gold": ("gold", "bullion"),
        "Copper": ("copper",), "Platinum": ("platinum",),
        "WTI": ("oil", "crude", "wti"), "Brent": ("oil", "crude", "brent"),
        "Wheat": ("wheat",), "Corn": ("corn",), "Soybeans": ("soybeans", "soybean"),
    }[asset]
    import re
    # The instrument may precede or follow the verb; accept common inflections.
    for subject in subjects:
        for verb in UP + DOWN:
            pattern = r"\b" + re.escape(subject) + r"\b.{0,65}\b" + re.escape(verb) + r"\b"
            reverse = r"\b" + re.escape(verb) + r"\b.{0,65}\b" + re.escape(subject) + r"\b"
            if re.search(pattern, lower) or re.search(reverse, lower):
                return "LONG" if verb in UP else "SHORT"
    return None


def confirm(asset, direction, now):
    symbol = SYMBOLS[asset]
    url = "https://query1.finance.yahoo.com/v8/finance/chart/" + quote(symbol, safe="")
    try:
        response = requests.get(url, params={"interval": "5m", "range": "1d"}, timeout=7,
                                headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        chart = response.json()["chart"]
        if chart.get("error"):
            raise ValueError("provider_error")
        result = chart["result"][0]
        times = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
        bars = [(int(t), float(p)) for t, p in zip(times, closes) if p is not None and p > 0]
        if len(bars) < 4:
            return None, "insufficient_bars"
        last_time, last_price = bars[-1]
        if abs(now.timestamp() - last_time) > 900 or last_time > now.timestamp() + 120:
            return None, "stale_price"
        # Five-minute direction decides; 15/60-minute trends are context only.
        changes = []
        for seconds in (300, 900, 3600):
            prior = [price for stamp, price in bars if stamp <= last_time - seconds]
            changes.append((last_price / prior[-1] - 1) * 100 if prior else None)
        if (changes[0] is None or changes[0] <= 0) and direction == "LONG":
            return None, "momentum_not_aligned"
        if (changes[0] is None or changes[0] >= 0) and direction == "SHORT":
            return None, "momentum_not_aligned"
        return {"symbol": symbol, "price": last_price, "time": datetime.fromtimestamp(last_time, timezone.utc).isoformat(),
                "changes": changes}, "confirmed"
    except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
        logging.warning("[PRICE] asset=%s error=%s", asset, type(exc).__name__)
        return None, "provider_unavailable"
