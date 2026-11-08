import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Instrument:
    name: str
    symbol: str
    catalyst_tags: tuple[str, ...]

UNIVERSE = (
    Instrument("Gold", "GC=F", ("gold", "precious metals", "safe haven", "central bank", "real yields", "dollar")),
    Instrument("Copper", "HG=F", ("copper", "industrial metals", "china", "manufacturing", "construction")),
    Instrument("Platinum", "PL=F", ("platinum", "precious metals", "auto", "catalyst")),
    Instrument("Palladium", "PA=F", ("palladium", "auto", "catalyst", "supply")),
    Instrument("WTI", "CL=F", ("oil", "crude", "opec", "energy", "sanctions", "middle east")),
    Instrument("Brent", "BZ=F", ("brent", "oil", "crude", "opec", "energy", "shipping")),
    Instrument("Wheat", "ZW=F", ("wheat", "grain", "agriculture", "harvest", "drought", "export")),
    Instrument("Corn", "ZC=F", ("corn", "maize", "agriculture", "ethanol", "harvest", "drought")),
    Instrument("Soybeans", "ZS=F", ("soybean", "soya", "agriculture", "china", "export", "harvest")),
)

def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}

DEFAULT_RSS_URLS = [
    "https://www.whitehouse.gov/feed/",
    "https://www.federalreserve.gov/feeds/press_all.xml",
    "https://www.bls.gov/feed/bls_latest.rss",
    "https://www.eia.gov/rss/press_rss.xml",
    "http://www.nass.usda.gov/rss/news.xml",
]
RSS_URLS = [x.strip() for x in (os.getenv("NEWS_RSS_URLS") or ",".join(DEFAULT_RSS_URLS)).split(",") if x.strip()]
GDELT_ENABLED = env_bool("GDELT_ENABLED", True)
MAX_QUOTE_AGE_MINUTES = int(os.getenv("MAX_QUOTE_AGE_MINUTES", "45"))
NEWS_LOOKBACK_HOURS = int(os.getenv("NEWS_LOOKBACK_HOURS", "12"))
MIN_ABS_NEWS_SCORE = int(os.getenv("MIN_ABS_NEWS_SCORE", "2"))
MIN_CONFIDENCE = int(os.getenv("MIN_CONFIDENCE", "60"))
DB_PATH = os.getenv("DB_PATH", "data/oracle.sqlite3")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
