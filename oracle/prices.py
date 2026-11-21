"""Futures prices around a signal, for the forecast journal (free Yahoo chart API).

A forecast is CORRETTA only when the price is on the predicted side both 30 and
60 minutes after the signal; a favourable move at 5 or 15 minutes alone does not
count. ERRATA when both are on the opposite side, otherwise INCERTA.
"""
from datetime import timedelta
import logging

from . import net

SYMBOLS = {"Gold": "GC=F", "Copper": "HG=F", "Platinum": "PL=F", "WTI": "CL=F", "Brent": "BZ=F",
           "Wheat": "ZW=F", "Corn": "ZC=F", "Soybeans": "ZS=F"}
HORIZONS = (5, 15, 30, 60)
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


def minute_bars(symbol, start, end):
    chart = net.get(CHART_URL.format(symbol=symbol), timeout=10, params={
        "interval": "1m", "period1": int(start.timestamp()), "period2": int(end.timestamp())}).json()["chart"]
    result = chart["result"][0]
    closes = result["indicators"]["quote"][0]["close"]
    return [(int(stamp), float(close)) for stamp, close in zip(result.get("timestamp") or [], closes)
            if close is not None and close > 0]


def price_at(bars, when, tolerance=180):
    """Last close at or before `when`, if it is no older than `tolerance` seconds."""
    target = when.timestamp()
    prior = [(stamp, close) for stamp, close in bars if stamp <= target]
    return prior[-1][1] if prior and target - prior[-1][0] <= tolerance else None


def outcome(direction, path):
    sign = 1 if direction == "LONG" else -1
    moves = [path.get(f"{minutes}m") for minutes in (30, 60)]
    if path.get("signal") is None or None in moves:
        return "PREZZI MANCANTI"
    if all(sign * (value - path["signal"]) > 0 for value in moves):
        return "CORRETTA"
    if all(sign * (value - path["signal"]) < 0 for value in moves):
        return "ERRATA"
    return "INCERTA"


def evaluate(directions, signal_at):
    result = {}
    for asset, direction in directions.items():
        if direction not in {"LONG", "SHORT"} or asset not in SYMBOLS:
            continue
        try:
            bars = minute_bars(SYMBOLS[asset], signal_at - timedelta(minutes=10),
                               signal_at + timedelta(minutes=max(HORIZONS) + 5))
        except Exception as exc:
            logging.warning("[PRICE] asset=%s error=%s", asset, type(exc).__name__)
            bars = []
        path = {"signal": price_at(bars, signal_at, tolerance=600)}
        for minutes in HORIZONS:
            path[f"{minutes}m"] = price_at(bars, signal_at + timedelta(minutes=minutes))
        result[asset] = {"direction": direction, "prices": path, "outcome": outcome(direction, path)}
    return result
