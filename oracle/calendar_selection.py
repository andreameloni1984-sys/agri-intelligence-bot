"""Two calendar-selected assets; macro interpretation, no technical indicators."""
from datetime import datetime, timezone
import re
from .calendar import EVENT_ASSETS
from .config import UNIVERSE
from .market import fetch_quotes
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
CREDIT_STRESS = ("mortgage delinquencies", "loan delinquencies", "mortgage defaults")
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
        if any(x in title for x in CREDIT_STRESS):
            direction = ("LONG" if surprise > 0 else "SHORT") if asset.name == "Gold" else ("SHORT" if surprise > 0 else "LONG")
            return (direction, "stress creditizio: dato vs atteso" if released else "stress creditizio: previsione vs precedente", released)
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
    # A separate geopolitical headline must not be attributed to a Fed speech
    # or economic release merely because it scores for the selected commodity.
    # Without a numeric release surprise, leave direction to observed price,
    # clearly labelled as price-only rather than caused by this event.
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
        if -120 <= delta <= 30:
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
        # News -> selection -> market analysis -> direction; only selected quotes.
        try:
            quotes = fetch_quotes([asset.symbol for asset in assets])
        except Exception as exc:
            print(f"[CALENDAR MARKET] quote fetch failed: {type(exc).__name__}")
            quotes = {}
        assessed = []
        for asset, (direction, why, verified) in zip(assets, directions):
            quote = quotes.get(asset.symbol)
            if quote and quote.last > 0 and quote.previous_close > 0:
                change = 100 * (quote.last / quote.previous_close - 1)
                price_direction = "LONG" if change > 0 else "SHORT" if change < 0 else None
                if direction == "NON DETERMINABILE" and price_direction:
                    direction = price_direction
                    why = f"movimento osservato su candela 15m ({change:+.3f}%), causalita non verificata"
                else:
                    why += f"; prezzo 15m {change:+.3f}%"
                    if price_direction and direction != price_direction:
                        why += " (prezzo contrario allo scenario)"
            assessed.append((direction, why, verified))
        directions = assessed
        # Never send an alert without a substantiated directional hypothesis.
        if not all(direction in ("LONG", "SHORT") for direction, _, _ in directions):
            print(f"[CALENDAR SILENT] {event['id']} no directional evidence")
            continue
        # Do not resend every five minutes solely because the quote percentage changed.
        signature = phase + "|" + "|".join(
            a.name + ":" + d[0] + ":" + str(d[2]) for a, d in zip(assets, directions)
        )
        if isinstance(old, dict) and old.get("signature") == signature:
            continue
        rows = []
        for index, (asset, (direction, why, verified)) in enumerate(zip(assets, directions), 1):
            qualification = "dato pubblicato" if verified else "ipotesi preliminare"
            if direction == "NON DETERMINABILE":
                instruction = "NON ENTRARE: mancano dati sufficienti per una direzione."
            elif phase == "PRIMA":
                instruction = "ATTENDERE la pubblicazione; osservare il prezzo senza anticipare un ingresso."
            elif "prezzo contrario" in why:
                instruction = "NON ENTRARE: il prezzo contraddice lo scenario; attendere conferma."
            else:
                instruction = "Verificare conferma del prezzo e rischio prima di qualsiasi ingresso manuale."
            rows.append(
                f"{index}. {asset.name} — {direction} ({qualification})\n"
                f"Analisi: {why}.\n"
                f"Istruzioni: {instruction}"
            )
        source = str(event.get("source") or "Calendario pubblico")
        message = (
            "🔴 STELLA ROSSA — CALENDARIO USA\n"
            f"Evento: {event.get('event')} | {phase} pubblicazione\n\n"
            + "\n\n".join(rows)
            + f"\n\nFonte: {source} — {event.get('url', '')}"
            + "\nPAPER ONLY — nessun ordine automatico."
        )
        if send_telegram_status(message):
            save_scheduler_state(key, {"assets":[a.name for a in assets],"signature":signature})
            print(f"[CALENDAR PAIR] {event['id']} {signature}")
