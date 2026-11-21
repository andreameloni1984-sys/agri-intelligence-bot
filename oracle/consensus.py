"""Free pre-release inputs.

* Analyst consensus and previous value: ForexFactory weekly calendar feed (no key).
* Independent estimate for CPI/PCE: Federal Reserve Bank of Cleveland inflation
  nowcast. It is compared with the consensus at the same 0.1 precision used by
  BLS/BEA, so rounding noise is not mistaken for a forecast.

Neither source is used for the actual figure: published values come only from
the issuing agency.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
import logging
import re

from . import net, storage
from .models import Context, event_kind

FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
FF_SOURCE = "https://www.forexfactory.com/calendar"
FF_REFRESH = timedelta(hours=1)
FF_RETRY = timedelta(minutes=5)
FF_METRICS = {
    "cpi": {"CPI m/m": "headline_mom_pct", "Core CPI m/m": "core_mom_pct"},
    # BLS "core" PPI in the summary excludes trade services, ForexFactory's does
    # not: only the headline is comparable.
    "ppi": {"PPI m/m": "headline_mom_pct"},
    "pce": {"PCE Price Index m/m": "headline_mom_pct", "Core PCE Price Index m/m": "core_mom_pct"},
    "nfp": {"Non-Farm Employment Change": "payrolls", "Unemployment Rate": "unemployment_pct"},
    "claims": {"Unemployment Claims": "claims"},
    "eia": {"Crude Oil Inventories": "crude_mb"},
    "fomc": {"Federal Funds Rate": "upper_pct"},
}

NOWCAST_URL = "https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json"
NOWCAST_SOURCE = "https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting"
NOWCAST_SERIES = {
    "cpi": {"CPI Inflation": "headline_mom_pct", "Core CPI Inflation": "core_mom_pct"},
    "pce": {"PCE Inflation": "headline_mom_pct", "Core PCE Inflation": "core_mom_pct"},
}
MONTHS = ("January February March April May June July August September October "
          "November December").split()


def parse_ff_value(text):
    match = re.fullmatch(r"\s*([+-]?\d+(?:\.\d+)?)\s*([KM%]?)\s*", text or "")
    if not match:
        return None
    value = float(match[1])
    return value * 1000 if match[2] == "K" else value


def forexfactory_week(now):
    """USD rows of the current week, fetched at most once per hour."""
    cache = storage.load("ff_week", {})
    fetched = datetime.fromisoformat(cache["fetched"]) if "fetched" in cache else None
    failed = datetime.fromisoformat(cache["failed"]) if "failed" in cache else None
    if fetched and now - fetched < FF_REFRESH or failed and now - failed < FF_RETRY:
        return cache.get("rows", [])
    try:
        rows = [row for row in net.get(FF_URL, timeout=10).json()
                if isinstance(row, dict) and row.get("country") == "USD"]
        storage.save("ff_week", {"fetched": now.isoformat(), "rows": rows})
        return rows
    except Exception as exc:  # network, HTTP, JSON: keep the last good copy, retry later
        logging.warning("[CONSENSUS] forexfactory error=%s", type(exc).__name__)
        storage.save("ff_week", {**cache, "failed": now.isoformat()})
        return cache.get("rows", [])


def ff_context(rows, kind, stamp):
    context = Context()
    for row in rows:
        metric = FF_METRICS.get(kind, {}).get(row.get("title"))
        try:
            observed = datetime.fromisoformat(row["date"])
        except (KeyError, TypeError, ValueError):
            continue
        if metric is None or abs((observed - stamp).total_seconds()) > 60:
            continue
        for column, target in (("forecast", context.consensus), ("previous", context.previous)):
            value = parse_ff_value(row.get(column))
            if value is not None:
                target[metric] = value
    if context.consensus or context.previous:
        context.urls.append(FF_SOURCE)
    return context


def _round(value):
    return float(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def reference_month(title):
    match = re.search(rf"\b({'|'.join(MONTHS)}) (20\d\d)\b", title)
    return (int(match[2]), MONTHS.index(match[1]) + 1) if match else None


def parse_nowcast(charts, kind, month, before: date):
    """Latest nowcast for the reference month published strictly before `before`."""
    year, number = month
    chart = next((item for item in charts if isinstance(item, dict)
                  and item.get("chart", {}).get("subcaption") == f"{year}-{number}"), None)
    if chart is None:
        return {}
    labels = [item.get("label", "") for item in chart["categories"][0]["category"]]
    result = {}
    for series in chart.get("dataset", []):
        metric = NOWCAST_SERIES[kind].get(series.get("seriesname"))
        if metric is None:
            continue
        for label, point in zip(labels, series.get("data", [])):
            stamp = re.fullmatch(r"(\d\d)/(\d\d)", label)
            value = point.get("value", "")
            if not stamp or not value:
                continue
            label_month = int(stamp[1])
            observed = date(year + (label_month < number), label_month, int(stamp[2]))
            if observed < before:
                result[metric] = _round(float(value))
    return result


def nowcast_context(event):
    kind = event_kind(event["event"])
    month = reference_month(event["event"])
    if kind not in NOWCAST_SERIES or month is None:
        return Context()
    day = datetime.fromisoformat(event["date_utc"]).date()
    try:
        values = parse_nowcast(net.get(NOWCAST_URL, timeout=25).json(), kind, month, day)
    except Exception as exc:
        logging.warning("[CONSENSUS] nowcast error=%s", type(exc).__name__)
        return Context()
    if not values:
        return Context()
    return Context(scenario=values, urls=[NOWCAST_SOURCE], scenario_source="Nowcast Fed Cleveland")


def ff_claims_dates(rows):
    """Weekly-claims release times listed for the current week (used for holiday weeks)."""
    result = []
    for row in rows:
        if row.get("title") == "Unemployment Claims":
            try:
                result.append(datetime.fromisoformat(row["date"]).astimezone(timezone.utc))
            except (KeyError, TypeError, ValueError):
                continue
    return result
