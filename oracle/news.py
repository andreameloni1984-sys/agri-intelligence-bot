from datetime import datetime, timezone, timedelta
import calendar
import requests
import feedparser
from .config import RSS_URLS, GDELT_ENABLED, NEWS_LOOKBACK_HOURS
from .models import NewsItem

USER_AGENT = "ORACLE-research-bot/0.5.1 (+public-feed-reader)"

def _parse_date(entry):
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
    return None

def _fetch_feed(url: str):
    response = requests.get(url, timeout=12, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    return feedparser.parse(response.content)

def fetch_rss() -> list[NewsItem]:
    items = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=NEWS_LOOKBACK_HOURS)
    for url in RSS_URLS:
        try:
            feed = _fetch_feed(url)
            if getattr(feed, "bozo", False):
                print(f"[NEWS] RSS parse warning {url}: {getattr(feed, 'bozo_exception', 'unknown')}")
            source = feed.feed.get("title", url)
            for entry in feed.entries:
                published = _parse_date(entry)
                if not published or published < cutoff:
                    continue
                title, link = entry.get("title", "").strip(), entry.get("link", url)
                if title and link:
                    items.append(NewsItem(title, link, published, source, entry.get("summary", "")[:2000]))
        except Exception as exc:
            print(f"[NEWS] RSS error {url}: {exc}")
    return items

def fetch_gdelt() -> list[NewsItem]:
    if not GDELT_ENABLED:
        return []
    endpoint = "https://api.gdeltproject.org/api/v2/doc/doc"
    params = {"query": '(Trump OR "White House" OR "Federal Reserve" OR OPEC OR oil OR gold OR wheat OR copper)',
              "mode": "ArtList", "format": "json", "sort": "DateDesc", "maxrecords": 50}
    try:
        response = requests.get(endpoint, params=params, timeout=15, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        data, out = response.json(), []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=NEWS_LOOKBACK_HOURS)
        for row in data.get("articles", []):
            try:
                published = datetime.strptime(row.get("seendate", ""), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue
            if published >= cutoff and row.get("url") and row.get("title"):
                out.append(NewsItem(row["title"], row["url"], published,
                                    row.get("domain", "GDELT"), row.get("sourcecountry", "")))
        return out
    except Exception as exc:
        print(f"[NEWS] GDELT error: {exc}")
        return []

def collect_news() -> list[NewsItem]:
    unique = {item.url: item for item in fetch_rss() + fetch_gdelt() if item.url}
    return sorted(unique.values(), key=lambda x: x.published, reverse=True)
