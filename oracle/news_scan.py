"""Independent, source-attributed commodity news discovery (no automatic trade signals)."""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
import logging
import feedparser
import requests

TOPICS = {
    "Gold": ("gold", "bullion", "fed", "treasury yields"),
    "Copper": ("copper", "industrial metals"),
    "Platinum": ("platinum",),
    "WTI": ("crude oil", "oil prices", "opec", "oil supply"),
    "Brent": ("crude oil", "oil prices", "opec", "oil supply"),
    "Wheat": ("wheat",),
    "Corn": ("corn", "maize"),
    "Soybeans": ("soybeans", "soybean"),
}
QUERY = '("gold" OR "crude oil" OR "copper" OR "platinum" OR "wheat" OR "corn" OR "soybeans") when:1d'
ALLOWED_SOURCES = ("reuters.com", "apnews.com")


def discover(now=None, limit=25):
    now = now or datetime.now(timezone.utc)
    params = urlencode({"q": QUERY, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    try:
        response = requests.get("https://news.google.com/rss/search?" + params, timeout=8)
        response.raise_for_status()
        entries = feedparser.parse(response.content).entries
    except (requests.RequestException, ValueError) as exc:
        logging.warning("[NEWS] source_error=%s", type(exc).__name__)
        return []
    result = []
    seen = set()
    for entry in entries:
        published = entry.get("published_parsed")
        if not published:
            continue
        stamp = datetime(*published[:6], tzinfo=timezone.utc)
        if not now - timedelta(hours=18) <= stamp <= now:
            continue
        source = entry.get("source", {})
        host = (source.get("href", "").split("/")[2].lower()
                if source.get("href", "").startswith("https://") else "")
        if not any(host == domain or host.endswith("." + domain) for domain in ALLOWED_SOURCES):
            continue
        title, url = entry.get("title", ""), entry.get("link", "")
        if not title or not url.startswith("https://") or url in seen:
            continue
        seen.add(url)
        title_lower = title.lower()
        markets = [asset for asset, terms in TOPICS.items() if any(term in title_lower for term in terms)]
        if markets:
            result.append({"title": title, "url": url, "published": stamp.isoformat(), "markets": markets})
        if len(result) >= limit:
            break
    logging.info("[NEWS] fetched=%d relevant=%d", len(entries), len(result))
    return result
