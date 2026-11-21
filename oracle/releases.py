"""Read event-dated values from the issuing agencies."""
import csv
import io
import logging
import re
from datetime import date, datetime, timedelta
from fractions import Fraction
from xml.etree import ElementTree

from pypdf import PdfReader

from . import net
from .calendar import ET, _html_text
from .models import Release, event_kind

BLS_SERIES = {"cpi": "cpi", "ppi": "ppi", "nfp": "empsit"}
EIA_TABLE = "https://ir.eia.gov/wpsr/table4.csv"
DOL_PDF = "https://www.dol.gov/ui/data.pdf"
FRED_TARGET = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFEDTARU"
WASDE_URL = "https://www.usda.gov/oce/commodity/wasde/wasde{edition}.xml"
MONTH = r"[A-Z][a-z]+"
MOVE = r"(increased|rose|rising|up|decreased|declined|fell|falling|down)"
NUMBER = r"([+-]?\d[\d,]*(?:\.\d+)?)"


def download(url):
    return net.get(url, timeout=10)


def _number(text):
    return float(text.replace(",", ""))


def _signed(verb, value):
    return (-1 if verb in {"decreased", "declined", "fell", "falling", "down"} else 1) * abs(_number(value))


def _dated(text, day):
    return bool(re.search(rf"\(ET\)|\(Eastern\)", text[:10000], re.I) and re.search(
        rf"{day:%B}\s+0?{day.day},\s+{day.year}", text[:10000], re.I))


def parse_bls(html, kind, url, day):
    # BLS puts the embargo, headline and text in the first PRE block.
    pre = re.search(r"<pre\b[^>]*>(.*?)</pre>", html, re.I | re.S)
    text = _html_text(pre.group(1) if pre else html)
    if not _dated(text, day):
        return None
    if kind == "nfp":
        move = re.search(rf"Total nonfarm payroll employment {MOVE} (?:by )?{NUMBER} in {MONTH}", text, re.I)
        if move is None:
            move = re.search(
                rf"Total nonfarm payroll employment changed little \(({NUMBER[1:-1]})\) in {MONTH}", text, re.I
            )
            if move is None:
                return None
            payrolls = _number(move[1])
        else:
            payrolls = _signed(move[1].lower(), move[2])
        previous, revised = {}, {}
        updates = re.findall(rf"change (?:in total nonfarm payroll employment )?for ({MONTH}) was revised (?:up|down) by [\d,]+, from {NUMBER} to {NUMBER}", text)
        if updates:
            month, old, new = updates[-1]
            previous["payrolls"], revised["payrolls"] = _number(old), _number(new)
            for older_month, older_old, older_new in updates[:-1]:
                key = f"payrolls_{older_month.lower()}"
                previous[key], revised[key] = _number(older_old), _number(older_new)
        actual = {"payrolls": payrolls}
        unemployment = re.search(r"the unemployment rate\b[^.%]{0,60}?\b(\d+\.\d) percent", text, re.I)
        if unemployment:
            actual["unemployment_pct"] = _number(unemployment[1])
        return Release(actual, url, previous, revised)

    prefix = (r"Consumer Price Index for All Urban Consumers \(CPI-U\)" if kind == "cpi"
              else r"Producer Price Index for final demand")
    match = re.search(rf"{prefix} {MOVE} {NUMBER} percent", text, re.I)
    zero = re.search(rf"{prefix} (?:was unchanged|was flat|held steady)", text, re.I)
    if not match and not zero:
        return None
    end = (match or zero).end()
    previous = re.search(rf"after {MOVE} {NUMBER} percent", text[end:end + 110])
    values = {"headline_mom_pct": _signed(match[1].lower(), match[2]) if match else 0.0}
    core_prefix = "index for all items less food and energy" if kind == "cpi" else "index for final demand less foods, energy, and trade services"
    core = re.search(rf"{core_prefix} {MOVE} {NUMBER} percent in {MONTH}", text[:4200], re.I)
    if core:
        values["core_mom_pct"] = _signed(core[1].lower(), core[2])
    prior = {"headline_mom_pct": _signed(previous[1], previous[2])} if previous else {}
    return Release(values, url, prior)


def parse_eia_table(content, period):
    rows = csv.reader(io.StringIO(content))
    header = next(rows, [])
    if len(header) < 4 or header[0] != "STUB_1" or header[3] != "Difference":
        return {}
    if datetime.strptime(header[1], "%m/%d/%y").date() != period:
        return {}
    keys = {"Commercial (Excluding SPR)": "crude_mb", "Total Motor Gasoline": "gasoline_mb",
            "Distillate Fuel Oil": "distillates_mb"}
    return {keys[row[0]]: _number(row[3]) for row in rows
            if len(row) >= 4 and row[0] in keys and re.fullmatch(r"[+-]?\d+(?:\.\d+)?", row[3])}


def _eia(event, day, preliminary):
    """Table 4 of the WPSR is published at release time and carries the weekly change."""
    if preliminary:
        return None
    actual = parse_eia_table(download(EIA_TABLE).text, date.fromisoformat(event["period"]))
    return Release(actual, EIA_TABLE) if actual else None


def parse_claims(text, day):
    text = " ".join(text.split())
    if not _dated(text, day):
        return None
    section = text.split("The 4-week moving average", 1)[0]
    actual = re.search(rf"seasonally adjusted initial claims was {NUMBER}", section)
    if not actual:
        return None
    revision = re.search(rf"previous week's level was revised (?:up|down) by [\d,]+ from {NUMBER} to {NUMBER}", section)
    previous, revised = {}, {}
    if revision:
        previous["claims"], revised["claims"] = _number(revision[1]), _number(revision[2])
    else:
        change = re.search(rf"an? (increase|decrease) of {NUMBER} from the previous week's (?:unrevised )?level", section)
        if change:
            previous["claims"] = _number(actual[1]) - (-1 if change[1] == "decrease" else 1) * _number(change[2])
        elif "unchanged from the previous week's" in section:
            previous["claims"] = _number(actual[1])
    return Release({"claims": _number(actual[1])}, DOL_PDF, previous, revised)


def _rate(text):
    whole, separator, fraction = text.partition("-")
    return float(Fraction(whole) + (Fraction(fraction) if separator else 0))


def parse_fomc(html, url):
    text = _html_text(html)
    rate = r"(\d+(?:-\d+/\d+|\.\d+|/\d+)?)"
    match = re.search(
        rf"target range for the federal funds rate (?:by {rate} percentage point[s]? )?(?:at|to) {rate} to {rate} percent",
        text, re.I,
    )
    if not match:
        return None
    previous = {"upper_pct": _rate(match[3])} if re.search(
        r"maintain the target range for the federal funds rate", text, re.I) else {}
    return Release({"upper_pct": _rate(match[3]), "lower_pct": _rate(match[2])}, url, previous,
                   notes=text[text.find("The Committee decided"):][:900])


def _fed_prior(day):
    csv = download(f"{FRED_TARGET}&cosd={day - timedelta(days=7)}&coed={day - timedelta(days=1)}").text
    rows = [row.split(",") for row in csv.splitlines()[1:]]
    for stamp, value in reversed(rows):
        if value not in {"", "."} and date.fromisoformat(stamp) < day:
            return {"upper_pct": _number(value)}
    return {}


def parse_wasde(content, day, url):
    root = ElementTree.fromstring(content)
    keys = {
        "U.S. Wheat Supply and Use": ("Wheat", 1),
        "U.S. Feed Grain and Corn Supply and Use": ("Corn", 2),
        "U.S. Soybeans and Products Supply and Use": ("Soybeans", 4),
    }
    actual, previous, periods = {}, {}, {}
    prior_period = (day.replace(day=1) - timedelta(days=1)).strftime("%b").lower()
    for report in root.iter("Report"):
        title = report.get("sub_report_title", "")
        if report.get("Report_Month") != day.strftime("%B %Y"):
            continue
        for label, (asset, number) in keys.items():
            if not title.startswith(label):
                continue
            for row in report.iter(f"attribute{number}"):
                if row.get(f"attribute{number}", "").lower() != "ending stocks":
                    continue
                by_period = {}
                for year in row.iter():
                    period = year.get(f"market_year{number}", "")
                    if "Proj." not in period:
                        continue
                    values = by_period.setdefault(period, {})
                    for month in year:
                        for group in month:
                            name = group.get(f"forecast_month{number}", "")[:3].lower()
                            cell = group.find("Cell")
                            value = cell.get(f"cell_value{number}", "") if cell is not None else ""
                            if re.fullmatch(r"[\d,]+(?:\.\d+)?", value):
                                values[name] = _number(value)
                for period, values in by_period.items():
                    current = values.get(day.strftime("%b").lower())
                    if current is not None:
                        actual[asset] = current
                        periods[asset] = period.split()[0]
                        if prior_period in values:
                            previous[asset] = values[prior_period]
    return Release(actual, url, previous, periods=periods) if actual else None


def parse_pce(html, day, url):
    text = _html_text(html)
    if not re.search(rf"EMBARGOED UNTIL RELEASE AT [^,]+, \w+, {day:%B} 0?{day.day}, {day.year}", text):
        return None
    table = text.partition("[Percent change from preceding month]")[2][:900]
    headline = re.search(rf"PCE price index {NUMBER} {NUMBER} PCE price index excluding food and energy {NUMBER} {NUMBER}", table)
    if headline:
        previous = {"headline_mom_pct": _number(headline[1]), "core_mom_pct": _number(headline[3])}
        return Release({"headline_mom_pct": _number(headline[2]), "core_mom_pct": _number(headline[4])},
                       url, previous)
    return None


def fetch_release(event, preliminary=False):
    kind = event_kind(event["event"])
    day = datetime.fromisoformat(event["date_utc"]).astimezone(ET).date()
    try:
        if kind == "eia":
            return _eia(event, day, preliminary)
        if kind == "fomc":
            url = f"https://www.federalreserve.gov/newsevents/pressreleases/monetary{day:%Y%m%d}a.htm"
            if preliminary:
                return None
            release = parse_fomc(download(url).text, url)
            if release and not release.previous:
                try:
                    release.previous = _fed_prior(day)
                except Exception:
                    pass
            return release
        if preliminary:
            return None
        if kind == "pce":
            return parse_pce(download(event["url"]).text, day, event["url"])
        if kind in BLS_SERIES:
            series = BLS_SERIES[kind]
            url = f"https://www.bls.gov/news.release/{series}.nr0.htm"
            return parse_bls(download(url).text, kind, url, day)
        if kind == "claims":
            pdf = PdfReader(io.BytesIO(download(DOL_PDF).content))
            return parse_claims(pdf.pages[0].extract_text(), day) if pdf.pages else None
        if kind == "wasde":
            url = WASDE_URL.format(edition=day.strftime("%m%y"))
            return parse_wasde(download(url).content, day, url)
    except Exception as exc:  # HTTP, timeout, malformed document: the release is not usable yet
        logging.info("[RELEASE] id=%s waiting error=%s", event["id"], type(exc).__name__)
    return None
