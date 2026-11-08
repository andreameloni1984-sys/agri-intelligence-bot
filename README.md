# ORACLE — market intelligence bot

Independent PAPER/research-only Python project. It does not reuse GAGARIN or SPUTNIK code, connect to Trading 212, or place orders.

## Pipeline
1. Collect timestamped public RSS news and optional GDELT reporting.
2. Fetch free Yahoo Finance continuous-futures candles for the fixed universe.
3. Score only explicit asset-specific catalyst phrases and require price confirmation.
4. Block missing, stale, invalid, or contradictory market data.
5. Calculate illustrative ATR-based SL/targets and record each scan in SQLite.
6. Send Telegram alerts only for newly deduplicated directional hypotheses.

## Universe
Gold GC=F; Copper HG=F; Platinum PL=F; Palladium PA=F; WTI CL=F; Brent BZ=F; Wheat ZW=F; Corn ZC=F; Soybeans ZS=F. Silver excluded.

These are Yahoo Finance continuous futures symbols, not broker-specific CFDs or exchange-expiry contracts. Confirm mappings and availability before relying on results.

## Run
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m oracle.main
```

## Configuration
Optional Telegram credentials: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID. Other settings are in .env.example. Quotes older than MAX_QUOTE_AGE_MINUTES are rejected.

## Actions
GitHub Actions runs every five minutes and can be manually dispatched. Add Telegram credentials as repository Actions secrets to enable delivery. Each run uploads its SQLite journal as an artifact; ephemeral runners mean this is not a durable shared database.

## Limitations
- No verified forward economic calendar is integrated yet. RSS publication feeds are not a calendar.
- Yahoo Finance data is unofficial and may be delayed, unavailable, or differently mapped.
- Keyword scoring is a transparent heuristic, not a validated probability or backtest.
- Telegram API acceptance is not proof that a person received/read an alert.
- No broker integration, live execution, position sizing, or paid data services.

## Tests
`python -m unittest discover -s tests -v`
