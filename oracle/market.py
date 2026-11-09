from datetime import datetime, timedelta, timezone
import pandas as pd
import yfinance as yf
from .config import UNIVERSE, MAX_QUOTE_AGE_MINUTES
from .models import Quote

def _symbol_history(data: pd.DataFrame, symbol: str):
    """Handle both ticker-first and field-first yfinance MultiIndex layouts."""
    if not isinstance(data.columns, pd.MultiIndex):
        return data.copy()
    if symbol in data.columns.get_level_values(0):
        return data[symbol].copy()
    if symbol in data.columns.get_level_values(1):
        return data.xs(symbol, axis=1, level=1).copy()
    return None

def fetch_quotes(symbols: list[str] | tuple[str, ...] | None = None) -> dict[str, Quote]:
    """Fetch only requested instruments; default remains the full universe for compatibility."""
    symbols = list(symbols) if symbols is not None else [item.symbol for item in UNIVERSE]
    symbols = list(dict.fromkeys(symbols))
    if not symbols:
        print("[MARKET] no active instruments; quote request skipped")
        return {}
    try:
        data = yf.download(tickers=" ".join(symbols), period="60d", interval="15m",
                           auto_adjust=False, group_by="ticker", progress=False, threads=False)
        if data is None or data.empty:
            print("[MARKET] batch download returned no candles")
            return {}
        out = {}
        for symbol in symbols:
            try:
                hist = _symbol_history(data, symbol)
                if hist is None:
                    print(f"[MARKET] symbol missing in batch: {symbol}")
                    continue
                hist = hist.dropna(subset=["Close", "High", "Low"])
                # Yahoo timestamps 15m bars at their opening time; ignore any still-open candle.
                now = datetime.now(timezone.utc)
                closed_before = now - timedelta(minutes=15)
                if hist.index.tz is None:
                    hist.index = hist.index.tz_localize("UTC")
                else:
                    hist.index = hist.index.tz_convert("UTC")
                hist = hist.loc[hist.index <= closed_before]
                if hist.empty:
                    print(f"[MARKET] no completed 15m candle for {symbol}")
                    continue
                # EMA200 needs a sufficiently long history; do not emit signals from a partial warm-up.
                if len(hist) < 220:
                    print(f"[MARKET] insufficient candles for {symbol}: {len(hist)} (need 220)")
                    continue
                last_row = hist.iloc[-1]
                close, previous = float(last_row["Close"]), float(hist.iloc[-2]["Close"])
                tr = pd.concat([hist["High"] - hist["Low"],
                    (hist["High"] - hist["Close"].shift()).abs(),
                    (hist["Low"] - hist["Close"].shift()).abs()], axis=1).max(axis=1)
                atr = float(tr.rolling(14, min_periods=14).mean().iloc[-1])
                # A 15m candle timestamp is its open time; freshness is measured from its close.
                timestamp = hist.index[-1].to_pydatetime() + timedelta(minutes=15)
                age_minutes = (now - timestamp).total_seconds() / 60
                if age_minutes < -1 or age_minutes > MAX_QUOTE_AGE_MINUTES:
                    print(f"[MARKET] stale completed candle {symbol}: age={int(age_minutes)}m; quote rejected")
                    continue
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                if close <= 0 or previous <= 0 or pd.isna(atr) or atr <= 0:
                    print(f"[MARKET] invalid candle values for {symbol}")
                    continue
                ema50 = float(hist["Close"].ewm(span=50, adjust=False).mean().iloc[-1])
                ema200 = float(hist["Close"].ewm(span=200, adjust=False).mean().iloc[-1])
                delta = hist["Close"].diff()
                gains = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
                losses = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
                rs = gains / losses.replace(0, float("nan"))
                rsi = float((100 - (100 / (1 + rs))).iloc[-1])
                if pd.isna(rsi):
                    rsi = 50.0 if float(gains.iloc[-1]) == 0 else 100.0
                structure = hist.iloc[-21:-1]
                structure_high = float(structure["High"].max())
                structure_low = float(structure["Low"].min())
                out[symbol] = Quote(symbol, close, previous, atr, timestamp.astimezone(timezone.utc),
                                    "Yahoo Finance", ema50, ema200, rsi, structure_high, structure_low)
            except Exception as exc:
                print(f"[MARKET] parse error {symbol}: {exc}")
        print(f"[MARKET] quotes_received={len(out)}/{len(symbols)}")
        return out
    except Exception as exc:
        print(f"[MARKET] batch provider error: {exc}")
        return {}

def fetch_quote(symbol: str) -> Quote | None:
    return fetch_quotes().get(symbol)
