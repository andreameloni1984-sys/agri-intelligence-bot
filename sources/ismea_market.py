import re
import requests
from bs4 import BeautifulSoup

URL_OVICAPRINI = "https://www.ismeamercati.it/flex/cm/pages/ServeBLOB.php/L/IT/IDPagina/817"
URL_LATTIERO = "https://www.ismeamercati.it/flex/cm/pages/ServeBLOB.php/L/IT/IDPagina/3068"


def _num(s):
    s = s.replace("â‚¬", "").replace("€", "")
    s = s.replace(".", "").replace(",", ".")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None


def fetch_table(url):
    r = requests.get(
        url,
        timeout=20,
        headers={"User-Agent": "AgriIntelligenceBot/1.0"},
    )
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    rows = []

    for tr in soup.select("table tr"):
        cells = [
            c.get_text(" ", strip=True)
            for c in tr.select("th,td")
        ]

        if len(cells) >= 5 and cells[0].lower() not in (
            "piazza",
            "market",
        ):
            rows.append(cells)

    return rows


def parse_ovicaprini():
    rows = fetch_table(URL_OVICAPRINI)
    out = []

    for c in rows:
        price = _num(c[3])
        change = _num(c[4])

        if price is not None:
            out.append(
                {
                    "market": c[0],
                    "date": c[1],
                    "product": c[2],
                    "price": price,
                    "unit": "€/kg",
                    "weekly_change": change,
                    "url": URL_OVICAPRINI,
                }
            )

    return out


def parse_lattiero_caseari():
    rows = fetch_table(URL_LATTIERO)
    out = []

    for c in rows:
        price = _num(c[3])
        change = _num(c[4])

        if price is not None:
            unit = (
                "€/hl"
                if "latte di pecora" in c[2].lower()
                else "€/kg"
            )

            out.append(
                {
                    "market": c[0],
                    "date": c[1],
                    "product": c[2],
                    "price": price,
                    "unit": unit,
                    "weekly_change": change,
                    "url": URL_LATTIERO,
                }
            )

    return out