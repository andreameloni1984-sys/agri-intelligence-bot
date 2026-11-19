"""Two calendar-selected assets; macro interpretation, no technical indicators."""
from datetime import datetime, timezone
import re
from .calendar import EVENT_ASSETS
from .config import UNIVERSE
from .analysis import score_news
from .storage import get_scheduler_state, save_scheduler_state
from .notify import send_telegram_status
from .market import fetch_quotes

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
    baseline = forecast if released else None
    observed = actual if released else None
    if observed is not None and baseline is not None and observed != baseline:
        surprise = 1 if observed > baseline else -1
        if any(x in title for x in INVERSE):
            surprise *= -1
        if any(x in title for x in INVENTORY):
            surprise *= -1
            if asset.name in ("WTI", "Brent"):
                return ("LONG" if surprise > 0 else "SHORT",
                        "iscortas publicadas cunfrontadas cun sas previssiones" if released else "previssiones de sas iscortas", released)
        if any(x in title for x in GROWTH + INFLATION + INVERSE):
            if asset.name == "Gold":
                surprise *= -1
            return ("LONG" if surprise > 0 else "SHORT",
                    "dadu publicadu cunfrontadu cun sa previssione" if released else "previssione cunfrontada cun su dadu pretzedente", released)
    score, matched = score_news(asset, news)
    if score:
        return ("LONG" if score > 0 else "SHORT", "noas: " + matched[0].title[:90], False)
    return ("NON DETERMINABILE", "perunu dadu verificabile pro sa diretzione", False)

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
        if -120 <= delta <= 30:
            relevant.append((abs(delta), delta, event))
    for _, delta, event in sorted(relevant, key=lambda x:x[0]):
        assets = _assets(event)
        phase = "PRIMA" if delta >= 0 else "DOPO"
        key = "calendar_pair:" + event["id"]
        old = get_scheduler_state(key, {})
        selected = old.get("assets") if isinstance(old, dict) else None
        if selected:
            assets = [ASSETS[n] for n in selected if n in ASSETS]
        directions = [_bias(event, a, news) for a in assets]
        # Check market only for the selected assets and only with directional evidence.
        symbols = [a.symbol for a, d in zip(assets, directions) if d[0] in ("LONG", "SHORT") and d[2]]
        quotes = fetch_quotes(symbols) if symbols else {}
        print(f"[MARKET VALIDATION] event={event['id']} requested={len(symbols)} received={len(quotes)}")
        # Never notify Telegram for calendar events without a verified directional release.
        actionable = [(a, d) for a, d in zip(assets, directions) if d[0] in ("LONG", "SHORT") and d[2] and a.symbol in quotes and ((quotes[a.symbol].price > quotes[a.symbol].previous_close) if d[0] == "LONG" else (quotes[a.symbol].price < quotes[a.symbol].previous_close))]
        if not actionable:
            print(f"[SILENT] event={event['id']} no verified directional release")
            continue
        signature = "|".join(a.name + ":" + d[0] for a,d in actionable)
        if isinstance(old,dict) and old.get("signature") == signature:
            continue
        rows = []
        for asset, (direction, why, verified) in actionable:
            qualification = "dadu publicadu e cunfirmadu" if verified else "dadu non cunfirmadu"
            rows.append(f"{asset.name}: {direction} — {why} ({qualification})")
        message = ("🔴 ISTELLA ROSSA — CALENDÀRIU USA\n"
                   f"{event.get('event')} | {'INNANTI' if phase == 'PRIMA' else 'A PUSTIS'} de sa publicatzione\n"
                   + "\n".join(rows) +
                   "\nFonte: Forex Factory — " + event.get("url", "") +
                   "\nPetzi istùdiu/paper; perunu òrdine automàticu.")
        if send_telegram_status(message):
            save_scheduler_state(key, {"assets":[a.name for a, _ in actionable],"signature":signature})
            print(f"[CALENDAR PAIR] {event['id']} {signature}")
