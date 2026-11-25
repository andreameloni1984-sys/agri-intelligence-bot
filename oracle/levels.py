"""Stop loss, take profit and euro amounts for Stella Rossa signals.

* Stop loss: 1.5 times the average 1-hour range (ATR 14 on hourly futures bars).
* Take profit: twice the stop distance (risk 1 to gain 2).
* Exit after 60 minutes anyway: the signal measures the reaction to the release.

The bot's prices are 10-15 minutes late and move fast after a release, so the message
gives DISTANCES from the price the user actually enters at, not fixed levels.
Euro amounts: ACCOUNT_SIZE (default 200 EUR) and RISK_PCT (default 2%) per signal.
"""
from datetime import timedelta
import logging
import os

from . import net
from .prices import CHART_URL, SYMBOLS

STOP_ATR = 1.5
TARGET_R = 2.0
MAX_MINUTES = 60
DEFAULT_ACCOUNT = 200.0
DEFAULT_RISK_PCT = 2.0
# ESMA leverage for retail CFDs: gold 20, other commodities 10.
LEVERAGE = {"Gold": 20}
# Grain futures are quoted in US cents per bushel.
CENTS = {"Wheat", "Corn", "Soybeans"}


def _num(name, default):
    try:
        value = float(os.getenv(name, "").replace(",", ".") or default)
    except ValueError:
        return default
    return value if value > 0 else default


def account():
    return _num("ACCOUNT_SIZE", DEFAULT_ACCOUNT), _num("RISK_PCT", DEFAULT_RISK_PCT)


def hourly_bars(symbol):
    chart = net.get(CHART_URL.format(symbol=symbol), timeout=10,
                    params={"interval": "1h", "range": "10d"}).json()["chart"]
    quote = chart["result"][0]["indicators"]["quote"][0]
    return [(h, l, c) for h, l, c in zip(quote["high"], quote["low"], quote["close"])
            if None not in (h, l, c) and c > 0]


def atr(bars, period=14):
    if len(bars) <= period:
        return None
    ranges = [max(h, prev_c) - min(l, prev_c) for (h, l, _), (_, _, prev_c) in zip(bars[1:], bars)]
    return sum(ranges[-period:]) / period


def eurusd():
    try:
        quote = net.get(CHART_URL.format(symbol="EURUSD=X"), timeout=10,
                        params={"interval": "1d", "range": "5d"}).json()["chart"]["result"][0]
        return float(quote["meta"]["regularMarketPrice"])
    except Exception as exc:
        logging.warning("[LEVELS] EURUSD error=%s", type(exc).__name__)
        return None


def plan_asset(asset, bars, fx, account_eur, risk_pct):
    value = atr(bars)
    if not value:
        return None
    price = bars[-1][2]
    stop = STOP_ATR * value
    level = {"stop_dist": stop, "target_dist": TARGET_R * stop, "price": price}
    if fx and asset not in CENTS:
        risk_eur = account_eur * risk_pct / 100
        units = risk_eur / (stop / fx)
        notional = units * price / fx
        level.update({"risk_eur": risk_eur, "gain_eur": risk_eur * TARGET_R, "units": units,
                      "notional_eur": notional, "margin_eur": notional / LEVERAGE.get(asset, 10),
                      "risk_pct": risk_pct})
    return level


def plan(directions, fetch=hourly_bars, fx=None):
    """{asset: levels} for the LONG/SHORT assets; assets without prices are left out."""
    wanted = [a for a, d in directions.items() if d in {"LONG", "SHORT"} and a in SYMBOLS]
    if not wanted:
        return {}
    account_eur, risk_pct = account()
    fx = fx if fx is not None else eurusd()
    out = {}
    for asset in wanted:
        try:
            level = plan_asset(asset, fetch(SYMBOLS[asset]), fx, account_eur, risk_pct)
        except Exception as exc:
            logging.warning("[LEVELS] asset=%s error=%s", asset, type(exc).__name__)
            level = None
        if level:
            out[asset] = {k: round(v, 4) for k, v in level.items()}
    return out


def _it(x, d=2):
    return f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _dist(asset, x):
    if asset in CENTS:
        return f"{_it(x, 1)} centesimi"
    return f"{_it(x, 3 if x < 1 else 2)} $"


def lines(asset, direction, level):
    below, above = ("sotto", "sopra") if direction == "LONG" else ("sopra", "sotto")
    out = [f"   🛑 Stop loss: {_dist(asset, level['stop_dist'])} {below} il tuo prezzo di entrata",
           f"   🎯 Take profit: {_dist(asset, level['target_dist'])} {above} il tuo prezzo di entrata"]
    if level.get("risk_eur"):
        out += [f"   💶 Posizione da circa {_it(level['notional_eur'])} € "
                f"(margine circa {_it(level['margin_eur'])} €)",
                f"   ❌ Se scatta lo stop perdi circa {_it(level['risk_eur'])} € "
                f"· ✅ al take profit guadagni circa {_it(level['gain_eur'])} €",
                f"   🔢 Quantità: {_it(level['units'], 4)}"]
    return out


def outcome(direction, level, bars, signal_at):
    """Which came first in the 60 minutes after the signal: TP, SL or neither (exit at 60 min).

    `bars` are 1-minute closes [(unix, close)]. Entry is the price at the signal.
    Result in R (multiples of the risk) and euro when the risk is known.
    """
    start, end = signal_at.timestamp(), (signal_at + timedelta(minutes=MAX_MINUTES)).timestamp()
    prior = [c for t, c in bars if t <= start and start - t <= 600]
    path = [c for t, c in bars if start < t <= end]
    if not prior or not path:
        return None
    entry, sign, stop = prior[-1], (1 if direction == "LONG" else -1), level["stop_dist"]
    result, exit_price = None, path[-1]
    for close in path:
        move = sign * (close - entry)
        if move <= -stop:
            result, exit_price = "SL", entry - sign * stop
            break
        if move >= level["target_dist"]:
            result, exit_price = "TP", entry + sign * level["target_dist"]
            break
    r = sign * (exit_price - entry) / stop
    row = {"exit": result or "60 MIN", "entry": entry, "exit_price": round(exit_price, 4), "r": round(r, 2)}
    if level.get("risk_eur"):
        row["eur"] = round(r * level["risk_eur"], 2)
    return row
