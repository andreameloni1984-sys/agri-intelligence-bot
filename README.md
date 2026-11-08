# ORACLE — market intelligence bot

Independent PAPER/research-only Python project. It does not reuse GAGARIN or SPUTNIK code, connect to Trading 212, or place orders.

## Pipeline
1. Collect timestamped public RSS news and optional GDELT reporting.
2. Fetch free Yahoo Finance continuous-futures candles for the fixed universe.
3. Load the official US economic release calendar (BLS macro releases + EIA weekly petroleum report).
4. Score only explicit asset-specific catalyst phrases and require price confirmation.
5. Block missing, stale, invalid, or contradictory market data.
6. Calculate illustrative ATR-based SL/targets and record each scan in SQLite.
7. Send Telegram alerts only for newly deduplicated directional hypotheses.

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

## Economic calendar
ORACLE reads the published BLS annual release schedule and the EIA Weekly Petroleum Status Report schedule. Event timestamps are normalized from US Eastern Time to UTC; the event record retains its official source URL. BLS is filtered to major inflation, employment, productivity and wage releases. EIA's normal weekly petroleum report is Wednesday 10:30 a.m. Eastern; official holiday adjustments are read from its schedule where present. This is a schedule feed, not a consensus/forecast calendar, and the sources can change their schedules. A failed source is logged independently and does not fabricate events.

Official sources:
- BLS: https://www.bls.gov/schedule/
- EIA: https://www.eia.gov/petroleum/supply/weekly/schedule.php

## GitHub automation and security
The repository is public. The following GitHub-native checks have been added to the ORACLE branch:

- **Python Quality:** unit tests and compilation on Python 3.11, 3.12, and 3.13 for pushes and pull requests.
- **CodeQL:** scheduled and pull-request static analysis for Python.
- **Dependency Review:** checks dependency changes in pull requests and fails on high-severity findings.
- **pip-audit:** weekly and pull-request audit of declared Python dependencies against known vulnerability advisories.
- **Dependabot:** weekly update proposals for Python packages and GitHub Actions.

These workflows use standard GitHub-hosted runners and read-only permissions wherever possible. GitHub documents standard Actions usage as free for public repositories. The connected repository API does not expose the account's billing plan or remaining usage, so I cannot verify whether this personal account has GitHub Pro.

**Repository settings still need an owner-side check:** enable Dependabot alerts/security updates and secret scanning/push protection where GitHub offers them for this public repository. Workflow files do not switch those repository-level settings on. Never add credentials to the repository or commit `.env`.

The existing five-minute ORACLE scan remains a separate workflow. Add Telegram credentials as repository Actions secrets only if you explicitly want Telegram delivery. Each scan currently uploads its SQLite journal as a run artifact; ephemeral runners mean this is not a durable shared database.

## Limitations
- No live economic consensus, previous/actual values, or non-US central-bank calendar is included.
- Yahoo Finance data is unofficial and may be delayed, unavailable, or differently mapped.
- Keyword scoring is a transparent heuristic, not a validated probability or backtest.
- Telegram API acceptance is not proof that a person received/read an alert.
- No broker integration, live execution, position sizing, or paid data services.

## Tests
`python -m unittest discover -s tests -v`
