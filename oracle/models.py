from dataclasses import dataclass
from datetime import datetime

@dataclass
class NewsItem:
    title: str
    url: str
    published: datetime
    source: str
    summary: str = ""

@dataclass
class Quote:
    symbol: str
    last: float
    previous_close: float
    atr: float
    timestamp: datetime
    source: str = "Yahoo Finance"
    ema50: float | None = None
    ema200: float | None = None
    rsi14: float | None = None
    structure_high: float | None = None
    structure_low: float | None = None

@dataclass
class Signal:
    instrument: str
    symbol: str
    direction: str
    confidence: int
    news_score: int
    price_change_pct: float
    reference_price: float
    stop_loss: float | None
    target_1: float | None
    target_2: float | None
    rationale: str
    news_urls: list[str]
    created_at: datetime
