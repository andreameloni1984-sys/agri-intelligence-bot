import requests
from bs4 import BeautifulSoup

SEARCH_URL = "https://www.regione.sardegna.it/atti-bandi-archivi/atti-amministrativi/bandi"

def fetch_bandi():
    r = requests.get(SEARCH_URL, timeout=20, headers={"User-Agent":"AgriIntelligenceBot/1.0"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for a in soup.select("a[href]"):
        title = a.get_text(" ", strip=True)
        href = a.get("href","")
        if not title or not href:
            continue
        text = title.lower()
        if any(k in text for k in ("agricolt", "ovino", "caprino", "sra", "srd", "pac", "sviluppo rurale", "argea")):
            if href.startswith("/"):
                href = "https://www.regione.sardegna.it" + href
            out.append({"title":title, "url":href})
    # deduplica
    seen=set(); clean=[]
    for x in out:
        if x["url"] not in seen:
            seen.add(x["url"]); clean.append(x)
    return clean[:100]
