"""Event-scoped Reuters coverage and an optional, attributed consensus feed."""
import logging
import re
from datetime import datetime, timedelta, timezone
import math
from urllib.parse import urlencode, urlparse

import feedparser
import requests

from .calendar import ET
from .config import EVENT_CONTEXT_URL, TRADING_ECONOMICS_API_KEY
from .models import Context, event_kind

QUERIES = {
    "cpi": '"consumer price index" OR "US inflation"',
    "ppi": '"producer prices" OR "producer price index"',
    "pce": '"PCE price index" OR "core PCE"',
    "nfp": '"nonfarm payrolls" OR "US jobs report"',
    "claims": '"US jobless claims" OR "US unemployment claims"',
    "eia": '"EIA" "crude inventories"',
    "fomc": '"FOMC" OR "Fed rate decision"',
    "wasde": '"WASDE" OR "USDA supply and demand"',
}
METRICS = {
    "cpi": {"headline_mom_pct", "core_mom_pct"},
    "ppi": {"headline_mom_pct", "core_mom_pct"},
    "pce": {"headline_mom_pct", "core_mom_pct"},
    "nfp": {"payrolls", "unemployment_pct"},
    "claims": {"claims"},
    "eia": {"crude_mb", "gasoline_mb", "distillates_mb"},
    "fomc": {"upper_pct"},
    "wasde": {"Wheat", "Corn", "Soybeans"},
}


TE_EVENTS = {
    "cpi": {"inflation rate mom": ("headline_mom_pct", "%"),
            "core inflation rate mom": ("core_mom_pct", "%")},
    "ppi": {"ppi mom": ("headline_mom_pct", "%")},
    "pce": {"pce price index mom": ("headline_mom_pct", "%"),
            "core pce price index mom": ("core_mom_pct", "%")},
    "nfp": {"non farm payrolls": ("payrolls", "k"), "unemployment rate": ("unemployment_pct", "%")},
    "claims": {"initial jobless claims": ("claims", "k")},
    "eia": {"eia crude oil stocks change": ("crude_mb", "m"),
            "eia gasoline stocks change": ("gasoline_mb", "m"),
            "eia distillate stocks change": ("distillates_mb", "m")},
    "fomc": {"fed interest rate decision": ("upper_pct", "%")},
}
TE_SOURCE = "https://tradingeconomics.com/united-states/calendar"


def parse_te_consensus(rows, kind, stamp):
    context = Context()
    if not isinstance(rows, list):
        return context
    for row in rows:
        if not isinstance(row, dict) or row.get("Country") != "United States":
            continue
        stamp_text, label = row.get("Date", ""), row.get("Event", "")
        if not isinstance(stamp_text, str) or not isinstance(label, str):
            continue
        try:
            observed = datetime.fromisoformat(stamp_text)
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        metric = TE_EVENTS.get(kind, {}).get(label.lower())
        if observed != stamp or metric is None:
            continue
        name, unit = metric
        for column, target in (("Forecast", context.consensus), ("Previous", context.previous)):
            value = row.get(column)
            match = re.fullmatch(rf"([+-]?\d+(?:\.\d+)?)\s*{re.escape(unit)}", value.strip(), re.I) if isinstance(value, str) else None
            if match:
                target[name] = float(match[1]) * (1000 if unit == "k" else 1)
    if context.consensus or context.previous:
        context.urls.append(TE_SOURCE)
    return context


def _te_consensus(kind, stamp):
    if kind not in TE_EVENTS:
        return Context()
    day = stamp.astimezone(ET).date()
    response = requests.get(
        f"https://api.tradingeconomics.com/calendar/country/united%20states/{day}/{day}",
        params={"c": TRADING_ECONOMICS_API_KEY}, timeout=6,
    )
    response.raise_for_status()
    return parse_te_consensus(response.json(), kind, stamp)


def _attributed_url(url):
    return isinstance(url, str) and urlparse(url).scheme == "https" and bool(urlparse(url).hostname)


def _values(row, kind, key, output):
    values = row.get(key, {})
    if not isinstance(values, dict):
        return
    for metric, value in values.items():
        if (metric in METRICS[kind] and type(value) in {int, float}
                and abs(value) < 1e12 and math.isfinite(value)):
            output[metric] = value


def parse_context(payload, event, now):
    context = Context()
    kind = event_kind(event["event"])
    stamp = datetime.fromisoformat(event["date_utc"])
    if not isinstance(payload, dict) or payload.get("event_id") != event["id"]:
        return context
    if not _attributed_url(payload.get("source_url")):
        return context
    try:
        published = datetime.fromisoformat(payload["as_of"])
        if not stamp - timedelta(days=14) <= published <= now or published >= stamp:
            return context
    except (KeyError, TypeError, ValueError, OverflowError):
        return context
    context.urls.append(payload["source_url"])
    for name in ("consensus", "previous", "scenario"):
        _values(payload, kind, name, getattr(context, name))
    periods = payload.get("periods")
    if kind == "wasde" and isinstance(periods, dict):
        context.periods = {key: value for key, value in periods.items()
                           if key in METRICS[kind] and isinstance(value, str) and re.fullmatch(r"\d{4}/\d{2}", value)}
    return context


def _reuters(kind, now):
    query = urlencode({"q": f"site:reuters.com ({QUERIES[kind]}) when:1d",
                       "hl": "en-US", "gl": "US", "ceid": "US:en"})
    response = requests.get(f"https://news.google.com/rss/search?{query}", timeout=6)
    response.raise_for_status()
    for entry in feedparser.parse(response.content).entries:
        published = entry.get("published_parsed")
        if not published:
            continue
        stamp = datetime(*published[:6], tzinfo=timezone.utc)
        source = entry.get("source", {})
        host = urlparse(source.get("href", "")).hostname
        if host not in {"reuters.com", "www.reuters.com"} or not now - timedelta(hours=18) <= stamp <= now:
            continue
        title = entry.get("title", "")
        url = entry.get("link", "")
        if title and _attributed_url(url):
            yield title, url, stamp


def _reuters_crude_consensus(title):
    match = re.search(
        r"Reuters poll.{0,100}?U\.S\. crude (?:oil )?(?:stockpiles|stocks|inventories) (?:seen|expected) "
        r"(?:to )?(falling|fall|rising|rise|down|up)(?: by)? (\d+(?:\.\d+)?) million barrels", title, re.I)
    if match:
        return float(match[2]) * (-1 if match[1].lower() in {"falling", "fall", "down"} else 1)
    return None


def fetch_context(event, now):
    kind = event_kind(event["event"])
    stamp = datetime.fromisoformat(event["date_utc"])
    context = Context()
    if EVENT_CONTEXT_URL:
        try:
            response = requests.get(EVENT_CONTEXT_URL, params={"event_id": event["id"]}, timeout=6)
            response.raise_for_status()
            context = parse_context(response.json(), event, now)
        except (requests.RequestException, ValueError) as exc:
            logging.info("Consenso %s: %s", event["id"], type(exc).__name__)
    if TRADING_ECONOMICS_API_KEY and now < stamp:
        try:
            provider = _te_consensus(kind, stamp)
            context.consensus = {**provider.consensus, **context.consensus}
            context.previous = {**provider.previous, **context.previous}
            context.urls.extend(provider.urls)
        except (requests.RequestException, ValueError) as exc:
            logging.info("Trading Economics %s: %s", event["id"], type(exc).__name__)
    try:
        for index, (title, url, published) in enumerate(_reuters(kind, now)):
            if index >= 4:
                break
            if now < stamp or published >= stamp:
                context.headlines.append(title)
            context.urls.append(url)
            if kind == "eia" and "crude_mb" not in context.consensus and published < stamp:
                value = _reuters_crude_consensus(title)
                if value is not None:
                    context.consensus["crude_mb"] = value
    except (requests.RequestException, ValueError) as exc:
        logging.info("Reuters %s: %s", event["id"], type(exc).__name__)
    return context
