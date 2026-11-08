from datetime import timezone
import pandas as pd
import yfinance as yf
from .config import UNIVERSE
from .models import Quote

def fetch_quotes() -> dict[str, Quote]:
    """Fetch the whole universe in one provider request; missing symbols fail closed."""
    symbols = [item.symbol for item in UNIVERSE]
    try:
        data = yf.download(tickers=" ".join(symbols), period="5d", interval="15m",
                           auto_adjust=False, group_by="ticker", progress=False, threads=False)
        if data is None or data.empty:
            print("[MARKET] batch download returned no candles")
            return {}
        out = {}
        for symbol in symbols:
            try:
                if isinstance(data.columns, pd.MultiIndex):
                    if symbol not in data.columns.get_level_values(0):
                        print(f"[MARKET] symbol missing in batch: {symbol}")
                        continue
                    hist = data[symbol].copy()
                else:
                    hist = data.copy()
                hist = hist.dropna(subset=["Close", "High", "Low"])
                if len(hist) < 15:
                    print(f"[MARKET] insufficient candles for {symbol}: {len(hist)}")
                    continue
                last_row = hist.iloc[-1]
                close, previous = float(last_row["Close"]), float(hist.iloc[-2]["Close"])
                tr = pd.concat([hist["High"] - hist["Low"],
                    (hist["High"] - hist["Close"].shift()).abs(),
                    (hist["Low"] - hist["Close"].shift()).abs()], axis=1).max(axis=1)
                atr = float(tr.rolling(14, min_periods=14).mean().iloc[-1])
                timestamp = hist.index[-1].to_pydatetime()
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                if close <= 0 or previous <= 0 or pd.isna(atr) or atr <= 0:
                    print(f"[MARKET] invalid candle values for {symbol}")
                    continue
                out[symbol] = Quote(symbol, close, previous, atr, timestamp.astimezone(timezone.utc))
            except Exception as exc:
                print(f"[MARKET] parse error {symbol}: {exc}")
        print(f"[MARKET] quotes_received={len(out)}/{len(symbols)}")
        return out
    except Exception as exc:
        print(f"[MARKET] batch provider error: {exc}")
        return {}

def fetch_quote(symbol: str) -> Quote | None:
    return fetch_quotes().get(symbol)
