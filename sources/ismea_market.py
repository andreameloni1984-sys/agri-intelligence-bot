import re
import requests
from bs4 import BeautifulSoup
import urllib3
# Alcuni runner possono avere problemi con la catena
# dei certificati SSL di ISMEA.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
URL_OVICAPRINI = (
    "https://www.ismeamercati.it/"
    "flex/cm/pages/ServeBLOB.php/L/IT/IDPagina/817"
)
URL_LATTIERO = (
    "https://www.ismeamercati.it/"
    "flex/cm/pages/ServeBLOB.php/L/IT/IDPagina/3068"
)
def _num(value):
    if value is None:
        return None
    s = str(value)
    s = s.replace("â‚¬", "")
    s = s.replace("€", "")
    s = s.replace("EUR", "")
    s = s.replace("%", "")
    s = s.replace(".", "")
    s = s.replace(",", ".")
    match = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(match.group()) if match else None
def fetch_table(url):
    response = requests.get(
        url,
        timeout=30,
        verify=False,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(compatible; AgriIntelligenceBot/1.0)"
            )
        },
    )
    response.raise_for_status()
    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )
    rows = []
    for tr in soup.select("table tr"):
        cells = [
            cell.get_text(" ", strip=True)
            for cell in tr.select("th, td")
        ]
        if len(cells) >= 5:
            first = cells[0].lower()
            if first not in ("piazza", "market"):
                rows.append(cells)
    return rows
def parse_ovicaprini():
    rows = fetch_table(URL_OVICAPRINI)
    results = []
    for cells in rows:
        price = _num(cells[3])
        change = _num(cells[4])
        if price is None:
            continue
        results.append(
            {
                "market": cells[0],
                "date": cells[1],
                "product": cells[2],
                "price": price,
                "unit": "€/kg",
                "weekly_change": change,
                "url": URL_OVICAPRINI,
            }
        )
    return results
def parse_lattiero_caseari():
    rows = fetch_table(URL_LATTIERO)
    results = []
    for cells in rows:
        price = _num(cells[3])
        change = _num(cells[4])
        if price is None:
            continue
        product = cells[2]
        if "latte di pecora" in product.lower():
            unit = "€/hl"
        else:
            unit = "€/kg"
        results.append(
            {
                "market": cells[0],
                "date": cells[1],
                "product": product,
                "price": price,
                "unit": unit,
                "weekly_change": change,
                "url": URL_LATTIERO,
            }
        )
    return results