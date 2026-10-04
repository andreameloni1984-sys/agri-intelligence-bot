from datetime import date, datetime
import re, requests
from bs4 import BeautifulSoup

AGRICULTURE_BANDI_URLS=[
 'https://www.regione.sardegna.it/atti-bandi-archivi/atti-amministrativi/bandi/178634727851228',
 'https://www.regione.sardegna.it/atti-bandi-archivi/atti-amministrativi/bandi/177884969569684',
]

def _parse_date(text):
    m=re.search(r'\d{2}/\d{2}/\d{4}',text or '')
    if not m: return None
    try: return datetime.strptime(m.group(),'%d/%m/%Y').date()
    except ValueError: return None

def _fetch_bando(url):
    r=requests.get(url,timeout=30,headers={'User-Agent':'AgriIntelligenceBot/1.0'}); r.raise_for_status()
    soup=BeautifulSoup(r.text,'html.parser'); h=soup.find('h1'); title=h.get_text(' ',strip=True) if h else ''
    text=soup.get_text(' ',strip=True); m=re.search(r'Data di scadenza\s+(\d{2}/\d{2}/\d{4})',text,re.I); deadline=_parse_date(m.group(1) if m else '')
    if not title or (deadline and deadline<date.today()): return None
    return {'title':title,'url':url,'deadline':deadline.isoformat() if deadline else None}

def fetch_bandi():
    out=[]
    for url in AGRICULTURE_BANDI_URLS:
        try:
            x=_fetch_bando(url)
            if x: out.append(x)
        except requests.RequestException as e: print(f'⚠️ Bando non leggibile: {url} — {e}')
    seen=set(); clean=[]
    for x in out:
        if x['url'] not in seen: seen.add(x['url']); clean.append(x)
    clean.sort(key=lambda x:x['deadline'] or '9999-12-31'); return clean
