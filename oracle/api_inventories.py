"""API (American Petroleum Institute) weekly crude stocks: Tuesday-evening early warning.

The API publishes its survey on Tuesday at 16:30 New York time, about 18 hours before
the official EIA report. The figure is not free at the source, so it is read from news
headlines (Google News RSS), e.g. "U.S. crude stockpiles rose 5.3M barrels last week,
API says". It is compared with the analysts' forecast for Wednesday's EIA crude change
(ForexFactory). The message is an estimate, clearly marked as such: the API and the EIA
often disagree.

    python -m oracle.api_inventories            # send if the figure is out and not yet sent
    python -m oracle.api_inventories --dry-run  # print only
"""
import argparse
from datetime import datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
import logging
import re
from urllib.parse import quote_plus
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from . import net, storage
from .consensus import forexfactory_week, parse_ff_value
from .notify import send_telegram

NEW_YORK = ZoneInfo("America/New_York")
ROME = ZoneInfo("Europe/Rome")
API_TITLE = "API Weekly Statistical Bulletin"
EIA_TITLE = "Crude Oil Inventories"
RELEASE_TIME = time(16, 30)
# Headlines older than the release (last week's figure) or too late are ignored.
WINDOW = timedelta(hours=4)
# Below this gap from the forecast (million barrels) the surprise is noise.
THRESHOLD_MB = 1.0
QUERIES = ('"API says" crude stockpiles', "API crude inventories", "API crude stocks barrels")
NEWS_URL = "https://news.google.com/rss/search?q={q}+when:1d&hl=en-US&gl=US&ceid=US:en"

_NUM = r"(\d+(?:\.\d+)?)\s*(?:M\b|mln\b|million\b)"
UP_WORDS = r"rose|rise|rises|build|builds|increase|increased|increases|surge|surged|jump|jumped|up"
DOWN_WORDS = r"fell|fall|falls|draw|draws|drawdown|decline|declined|declines|drop|dropped|drops|down"
PATTERNS = (
    # "crude stockpiles rose 5.3M barrels", "inventories reportedly down 5.3M barrels"
    re.compile(rf"\b(?:crude|oil)\b[\w\s.-]{{0,30}}?\b(?:stockpiles|stocks|inventories|inventory)\b"
               rf"(?:\s+\w+){{0,2}}?\s+(?P<dir>{UP_WORDS}|{DOWN_WORDS})\s+(?:by\s+)?(?:of\s+)?{_NUM}", re.I),
    # "API inventory surge of 5.3 million barrels", "a draw of 4 million barrels"
    re.compile(rf"\b(?P<dir>{UP_WORDS}|{DOWN_WORDS})\s+(?:of|by)\s+{_NUM}\s+barrels", re.I),
    # "API crude +4.6M", "crude oil inventories -2.1 million"
    re.compile(rf"\b(?:crude|inventories|stocks)\b[^+\-\d]{{0,20}}(?P<sign>[+-])\s?{_NUM}", re.I),
)
# Words that make the headline about the official report, not the API survey.
EIA_WORDS = re.compile(r"\bEIA\b|Energy Information Administration|government data|official data", re.I)
API_WORDS = re.compile(r"\bAPI\b|American Petroleum Institute|reportedly|industry data|industry group", re.I)
# Headlines without a figure ("API Shows Sharp Build in US Crude Oil Inventories"): direction only.
_STOCKS = r"(?:stockpiles|stocks|inventories|inventory|supplies)"
DIRECTION_PATTERNS = (
    # "crude inventories rise", "oil stocks fell"
    re.compile(rf"\b(?:crude|oil)\b[\w\s.-]{{0,30}}?\b{_STOCKS}\b(?:\s+\w+){{0,2}}?\s+(?P<dir>{UP_WORDS}|{DOWN_WORDS})\b", re.I),
    # "build in US crude oil inventories", "draw in crude stocks"
    re.compile(rf"\b(?P<dir>{UP_WORDS}|{DOWN_WORDS})\s+in\s+(?:\w+\s+){{0,3}}?(?:crude|oil|{_STOCKS})\b", re.I),
    # "API reports crude draw", "surprise crude build"
    re.compile(r"\b(?:crude|oil)\s+(?:stock\s+|inventory\s+)?(?P<dir>build|builds|draw|draws|drawdown)\b", re.I),
)
# A figure-less headline is used only if no headline with a number shows up within this delay.
QUALITATIVE_AFTER = timedelta(minutes=45)


def release_time(rows, now):
    """This week's API release (ForexFactory moves it after holidays), else Tuesday 16:30 NY."""
    for row in rows:
        if row.get("title") == API_TITLE:
            try:
                return datetime.fromisoformat(row["date"]).astimezone(timezone.utc)
            except (KeyError, TypeError, ValueError):
                pass
    local = now.astimezone(NEW_YORK)
    tuesday = local.date() - timedelta(days=(local.weekday() - 1) % 7)
    return datetime.combine(tuesday, RELEASE_TIME, NEW_YORK).astimezone(timezone.utc)


def eia_forecast(rows, after):
    """Forecast and previous value (million barrels) of the next EIA crude change."""
    best = None
    for row in rows:
        if row.get("title") != EIA_TITLE:
            continue
        try:
            when = datetime.fromisoformat(row["date"]).astimezone(timezone.utc)
        except (KeyError, TypeError, ValueError):
            continue
        if when > after and (best is None or when < best[0]):
            best = (when, parse_ff_value(row.get("forecast")), parse_ff_value(row.get("previous")))
    return best or (None, None, None)


def parse_headline(title):
    """Change in million barrels announced by an API headline, or None."""
    if EIA_WORDS.search(title) or not API_WORDS.search(title):
        return None
    for pattern in PATTERNS:
        match = pattern.search(title)
        if not match:
            continue
        value = float(match[match.lastindex])
        groups = match.groupdict()
        if groups.get("sign"):
            return -value if groups["sign"] == "-" else value
        return -value if re.fullmatch(DOWN_WORDS, groups["dir"], re.I) else value
    return None


def parse_direction(title):
    """+1 (stocks up) or -1 (stocks down) from an API headline without a figure, or None."""
    if EIA_WORDS.search(title) or not API_WORDS.search(title):
        return None
    for pattern in DIRECTION_PATTERNS:
        match = pattern.search(title)
        if match:
            return -1 if re.fullmatch(DOWN_WORDS, match["dir"], re.I) else 1
    return None


def parse_feed(xml_text):
    items = []
    for item in ET.fromstring(xml_text).iter("item"):
        title = item.findtext("title") or ""
        try:
            published = parsedate_to_datetime(item.findtext("pubDate") or "").astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
        headline, _, publisher = title.rpartition(" - ")
        items.append({"title": headline or title, "publisher": publisher if headline else "",
                      "published": published})
    return items


def find_direction(items, release, now):
    """Direction (+1/-1) from figure-less API headlines, once QUALITATIVE_AFTER has passed."""
    if now - release < QUALITATIVE_AFTER:
        return None
    found = sorted(((item["published"], d, item) for item in items
                    if release <= item["published"] <= release + WINDOW
                    for d in [parse_direction(item["title"])] if d), key=lambda x: x[0])
    if not found or len({d for _, d, _ in found[:3]}) > 1:
        return None
    return found[0][1], found[0][2]


def find_figure(items, release):
    """Earliest API headline published inside the window after the release."""
    found = []
    for item in items:
        if not release <= item["published"] <= release + WINDOW:
            continue
        value = parse_headline(item["title"])
        if value is not None:
            found.append((item["published"], value, item))
    if not found:
        return None
    found.sort(key=lambda x: x[0])
    # Two outlets disagreeing on the sign means a misread headline: wait for more.
    first = found[0][1]
    if any((v > 0) != (first > 0) for _, v, _ in found[:3] if v):
        logging.warning("[API] headlines disagree: %s", [v for _, v, _ in found[:3]])
        return None
    return found[0][1], found[0][2]


def fetch_items():
    items = []
    for query in QUERIES:
        try:
            items += parse_feed(net.get(NEWS_URL.format(q=quote_plus(query)), timeout=15).text)
        except Exception as exc:  # network, HTTP, XML: try the other queries
            logging.warning("[API] news error=%s", type(exc).__name__)
    return items


def _mb(value):
    return f"{value:+.1f} milioni di barili"


def _direction_lines(direction, forecast, previous):
    """Figure-less headline: a direction only when it is opposite to the forecast."""
    word = "in aumento" if direction > 0 else "in calo"
    lines = [f"🛢️ API: scorte di greggio USA {word} (il titolo non riporta la cifra)"]
    if forecast is None:
        return lines + ["", "⚪ Previsione EIA non disponibile: nessuna direzione"]
    lines.append(f"📋 Previsione per il dato EIA: {_mb(forecast)}"
                 + (f" (settimana scorsa {_mb(previous)})" if previous is not None else ""))
    lines.append("")
    if direction > 0 and forecast <= 0:
        return lines + ["➡️ Le attese erano di un calo, l'API dice aumento: probabile EIA sopra le attese",
                        "🥇 WTI — ⬇️ SHORT", "🥈 BRENT — ⬇️ SHORT"]
    if direction < 0 and forecast >= 0:
        return lines + ["➡️ Le attese erano di un aumento, l'API dice calo: probabile EIA sotto le attese",
                        "🥇 WTI — ⬆️ LONG", "🥈 BRENT — ⬆️ LONG"]
    return lines + ["➡️ Stesso verso delle attese ma senza cifra non si sa se è più o meno: nessuna direzione"]


def format_message(value, forecast, previous, item, release, eia_time, exact=True):
    lines = ["🔴 STELLA ROSSA — SCORTE API (anticipo del dato EIA)", ""]
    if not exact:
        lines += _direction_lines(value, forecast, previous)
    elif forecast is not None:
        lines.append(f"🛢️ API: scorte di greggio USA {_mb(value)}")
        surprise = value - forecast
        lines.append(f"📋 Previsione per il dato EIA: {_mb(forecast)}"
                     + (f" (settimana scorsa {_mb(previous)})" if previous is not None else ""))
        lines.append("")
        if surprise <= -THRESHOLD_MB:
            lines += [f"➡️ Scorte sotto le attese di {abs(surprise):.1f} milioni: probabile EIA sotto le attese",
                      "🥇 WTI — ⬆️ LONG", "🥈 BRENT — ⬆️ LONG"]
        elif surprise >= THRESHOLD_MB:
            lines += [f"➡️ Scorte sopra le attese di {surprise:.1f} milioni: probabile EIA sopra le attese",
                      "🥇 WTI — ⬇️ SHORT", "🥈 BRENT — ⬇️ SHORT"]
        else:
            lines += ["➡️ In linea con le attese (scarto sotto 1 milione di barili): nessuna direzione"]
    else:
        lines += [f"🛢️ API: scorte di greggio USA {_mb(value)}", "",
                  "⚪ Previsione EIA non disponibile: nessuna direzione"]
    lines.append("")
    if eia_time:
        lines.append(f"🕒 Dato ufficiale EIA: {eia_time.astimezone(ROME):%A %d/%m %H:%M} Italia".replace(
            "Monday", "lunedì").replace("Tuesday", "martedì").replace("Wednesday", "mercoledì").replace(
            "Thursday", "giovedì").replace("Friday", "venerdì"))
    lines += [f"📰 Fonte: titolo di {item['publisher'] or 'notizia'} — «{item['title']}»",
              f"   (sondaggio API delle {release.astimezone(ROME):%H:%M} italiane)",
              "",
              "⚠️ STIMA: l'API è un sondaggio privato e a volte il dato EIA va nel verso opposto.",
              "PAPER ONLY"]
    return "\n".join(lines)


def run(now=None, rows=None, items=None, send=send_telegram, dry_run=False):
    now = now or datetime.now(timezone.utc)
    rows = forexfactory_week(now) if rows is None else rows
    release = release_time(rows, now)
    if not release <= now <= release + WINDOW:
        logging.info("[API] outside the window (release %s)", release.isoformat())
        return None
    key = f"api:{release.date().isoformat()}"
    sent = storage.load("api_inventories", {})
    if key in sent:
        logging.info("[API] already sent for %s", key)
        return None
    items = fetch_items() if items is None else items
    found, exact = find_figure(items, release), True
    if not found:
        found, exact = find_direction(items, release, now), False
    if not found:
        logging.info("[API] figure not in the news yet")
        return None
    value, item = found
    eia_time, forecast, previous = eia_forecast(rows, release)
    message = format_message(value, forecast, previous, item, release, eia_time, exact)
    if dry_run:
        print(message)
        return message
    delivery = send(message)
    logging.info("[API] value=%s forecast=%s delivery=%s", value, forecast, delivery)
    if delivery in ("delivered", "rejected", "unknown"):
        sent[key] = {"value": value, "exact": exact, "forecast": forecast, "at": now.isoformat(), "delivery": delivery}
        storage.save("api_inventories", dict(sorted(sent.items())[-30:]))
    return message


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
