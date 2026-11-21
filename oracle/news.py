"""Pre-release context: consensus, previous value and an independent estimate."""
import logging
import math
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse

from . import net
from .config import EVENT_CONTEXT_URL
from .consensus import ff_context, forexfactory_week, nowcast_context
from .models import Context, event_kind

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
    """Optional user feed (EVENT_CONTEXT_URL); see README for the format."""
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
    if context.scenario:
        context.scenario_source = urlparse(payload["source_url"]).hostname
    periods = payload.get("periods")
    if kind == "wasde" and isinstance(periods, dict):
        context.periods = {key: value for key, value in periods.items()
                           if key in METRICS[kind] and isinstance(value, str) and re.fullmatch(r"\d{4}/\d{2}", value)}
    return context


def fetch_context(event, now):
    kind = event_kind(event["event"])
    stamp = datetime.fromisoformat(event["date_utc"])
    context = Context()
    if EVENT_CONTEXT_URL:
        try:
            context = parse_context(
                net.get(EVENT_CONTEXT_URL, timeout=6, params={"event_id": event["id"]}).json(), event, now)
        except Exception as exc:
            logging.info("Feed contesto %s: %s", event["id"], type(exc).__name__)
    market = ff_context(forexfactory_week(now), kind, stamp)
    context.consensus = {**market.consensus, **context.consensus}
    context.previous = {**market.previous, **context.previous}
    context.urls += market.urls
    if not context.scenario and now < stamp:
        estimate = nowcast_context(event)
        context.scenario, context.scenario_source = estimate.scenario, estimate.scenario_source
        context.urls += estimate.urls
    return context
