"""Two calendar-selected assets; macro interpretation, no technical indicators."""
from datetime import datetime, timezone
import re
from .calendar import EVENT_ASSETS
from .config import UNIVERSE
from .analysis import score_news
from .storage import get_scheduler_state, save_scheduler_state
from .notify import send_telegram_status

ASSETS = {item.name: item for item in UNIVERSE}
# Priority resolves events affecting many assets; no importance filter.
PRIORITY = ("Gold", "Copper", "WTI", "Brent", "Platinum", "Wheat", "Corn", "Soybeans")
# For growth/jobs/inflation surprises, positive values generally favor growth
# assets and weigh on gold via rates. Inventory builds weigh on oil.
GROWTH = ("employment", "payroll", "manufacturing", "retail sales", "gdp",
          "industrial production", "durable goods", "consumer confidence", "sentiment")
INFLATION = ("cpi", "ppi", "inflation", "price index", "pce")
INVERSE = ("unemployment claims", "jobless claims", "unemployment rate")
INVENTORY = ("crude oil inventories", "oil inventories", "petroleum")
def _number(value):
    match = re.fullmatch(r"\s*([+-]?[\d,.]+)\s*([KMB%]?)\s*", str(value or ""), re.I)
    if not match:
        return None
    try:
        n = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    return n * {"K":1e3,"M":1e6,"B":1e9}.get(match.group(2).upper(), 1)

def _assets(event):
    title = event.get("event", "").lower()
    mapped = set()
    for keyword, names in EVENT_ASSETS.items():
        if keyword in title:
            mapped.update(names)
    if not mapped:
        # Generic USD calendar entries are still scanned; never silently skip.
        mapped = {"Gold", "Copper"}
    return [ASSETS[name] for name in PRIORITY if name in mapped and name in ASSETS][:2]

def _bias(event, asset, news):
    title = event.get("event", "").lower()
    actual = _number(event.get("actual"))
    forecast = _number(event.get("forecast"))
    previous = _number(event.get("previous"))
    released = actual is not None
    baseline = forecast if released else previous
    observed = actual if released else forecast
    if observed is not None and baseline is not None and observed != baseline:
        surprise = 1 if observed > baseline else -1
        if any(x in title for x in INVERSE):
            surprise *= -1
        if any(x in title for x in INVENTORY):
            surprise *= -1
            if asset.name in ("WTI", "Brent"):
                return ("LONG" if surprise > 0 else "SHORT",
                        "scorte effettive vs attese" if released else "scorte previste vs precedenti", released)
        if any(x in title for x in GROWTH + INFLATION + INVERSE):
            if asset.name == "Gold":
                surprise *= -1
            return ("LONG" if surprise > 0 else "SHORT",
                    "dato effettivo vs previsione" if released else "previsione vs precedente", released)
    score, matched = score_news(asset, news)
    if score:
        return ("LONG" if score > 0 else "SHORT", "notizie: " + matched[0].title[:90], False)
    return ("NON DETERMINABILE", "nessun dato direzionale verificabile", False)

def run_calendar_selection(events, now, news):
    """Select exactly two eligible instruments per event, notify once per phase/change."""
    relevant = []
    for event in events:
        try:
            stamp = datetime.fromisoformat(event["date_utc"])
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            delta = (stamp - now).total_seconds() / 60
        except (ValueError, TypeError, KeyError):
            continue
        if -120 <= delta <= 15:
            relevant.append((abs(delta), delta, event))
    for _, delta, event in sorted(relevant, key=lambda x:x[0]):
        assets = _assets(event)
        if len(assets) < 2:
            # Preserve two candidates even for a narrowly mapped event.
            assets += [ASSETS[n] for n in PRIORITY if n in ASSETS and ASSETS[n] not in assets][:2-len(assets)]
        phase = "PRIMA" if delta >= 0 else "DOPO"
        key = "calendar_pair:" + event["id"]
        old = get_scheduler_state(key, {})
        selected = old.get("assets") if isinstance(old, dict) else None
        if selected:
            assets = [ASSETS[n] for n in selected if n in ASSETS]
        directions = [_bias(event, a, news) for a in assets]
        # Never send an alert without a substantiated directional hypothesis.
        if not any(direction in ("LONG", "SHORT") for direction, _, _ in directions):
            print(f"[CALENDAR SILENT] {event['id']} no directional evidence")
            continue
        signature = phase + "|" + "|".join(a.name + ":" + d[0] for a,d in zip(assets,directions))
        if isinstance(old,dict) and old.get("signature") == signature:
            continue
        rows = []
        for asset, (direction, why, verified) in zip(assets,directions):
            qualification = "dato pubblicato" if verified else "ipotesi / dati insufficienti"
            rows.append(f"{asset.name}: {direction} — {why} ({qualification})")
        message = ("🔴 STELLA ROSSA — CALENDARIO USA\n"
                   f"{event.get('event')} | {phase} pubblicazione\n"
                   + "\n".join(rows) +
                   "\nFonte: Forex Factory — " + event.get("url", "") +
                   "\nSolo ricerca/paper; nessun ordine automatico.")
        if send_telegram_status(message):
            save_scheduler_state(key, {"assets":[a.name for a in assets],"signature":signature})
            print(f"[CALENDAR PAIR] {event['id']} {signature}")
