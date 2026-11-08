# ORACLE — market intelligence bot

Independent PAPER/research-only Python project. It does not reuse GAGARIN or SPUTNIK code, connect to Trading 212, or place orders.

## What ORACLE does

1. Scans a fixed nine-market futures research universe: Gold, Copper, Platinum, Palladium, WTI, Brent, Wheat, Corn and Soybeans. Silver is excluded.
2. Collects timestamped public RSS news from the White House, Federal Reserve, BLS, EIA and USDA NASS, plus optional GDELT news.
3. Downloads free Yahoo Finance continuous-futures candles in a batch and rejects missing, invalid or stale quotes.
4. Reads official US schedules from BLS (major inflation/employment releases), EIA (weekly petroleum report), Federal Reserve (FOMC meetings) and USDA (WASDE).
5. Matches asset-specific catalyst phrases, checks whether price direction confirms the news, and blocks a directional hypothesis if evidence conflicts.
6. Calculates illustrative ATR-based stop-loss and two targets. The confidence score is a rule-based heuristic, not a statistically validated probability.
7. Records scan results, latest quotes and upcoming calendar events in SQLite.
8. Sends Telegram alerts for newly detected, deduplicated directional hypotheses and supports read-only Telegram commands.

## Markets and data symbols

| Market | Yahoo Finance symbol |
|---|---|
| Gold | GC=F |
| Copper | HG=F |
| Platinum | PL=F |
| Palladium | PA=F |
| WTI | CL=F |
| Brent | BZ=F |
| Wheat | ZW=F |
| Corn | ZC=F |
| Soybeans | ZS=F |

These are Yahoo Finance continuous futures symbols, not broker-specific CFDs or exchange-expiry contracts. Yahoo data is unofficial and may be delayed, unavailable or mapped differently. No broker feed is connected.

## Telegram

Add the following as **GitHub repository → Settings → Secrets and variables → Actions → New repository secret**:

- `TELEGRAM_BOT_TOKEN`: token from BotFather.
- `TELEGRAM_CHAT_ID`: the private chat or group ID authorized to receive alerts and issue commands.

Never paste tokens into source code or chat. ORACLE only processes commands from the configured chat ID.

Commands:
- `/start` or `/help` — command guide.
- `/status` — last scan time, number of news items and markets checked.
- `/report` — latest directional hypotheses with reference, stop and targets.
- `/prezzi` — latest saved quotes and timestamps.
- `/calendario` — next scheduled economic events.\n\nStart the persistent Telegram service with `python -m oracle.telegram_bot`.

Telegram commands run through a separate persistent polling process (`python -m oracle.telegram_bot`), using the same BotFather token and configured chat ID as the former AGRI bot. This restores the always-listening Telegram model instead of polling only during five-minute GitHub Actions jobs. Run exactly one polling process per bot token; do not run the old `getUpdates` poller at the same time. If a webhook was configured, remove it before starting polling. The GitHub Actions market scanner remains separate and only sends alerts. The Telegram process must be hosted continuously (for example, on an existing always-on server); GitHub Actions scheduled jobs are not a persistent host.

## Economic calendar coverage

- **BLS:** selected CPI, PPI, Employment Situation, JOLTS, Productivity, Employment Cost Index and import/export price releases.
- **EIA:** Weekly Petroleum Status Report; the parser reads the official schedule and attempts to apply published holiday adjustments.
- **Federal Reserve:** scheduled FOMC meeting decision day, using the official meeting calendar. The second meeting day is represented at the usual 2:00 p.m. Eastern statement time.
- **USDA:** monthly WASDE report release dates from the official World Agricultural Outlook Board page.

This is a release schedule, not a full global calendar. It does not currently provide market consensus, forecast, previous or actual values; it does not cover every NASS/ERS/FAS release, central bank, or economic indicator. Failed or unparseable sources are logged and omitted rather than fabricated.

Official sources:
- BLS: https://www.bls.gov/schedule/
- EIA: https://www.eia.gov/petroleum/supply/weekly/schedule.php
- Federal Reserve: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
- USDA WASDE: https://usda.azureedge.us/about-usda/general-information/staff-offices/office-chief-economist/commodity-markets/wasde-report

## Automation and journal

GitHub Actions runs the research scan every five minutes and can also be started manually from the Actions tab. The scan stores SQLite results and uploads a run artifact for 30 days. GitHub-hosted runners are temporary and the previous artifact is not automatically restored into the next run: Telegram read commands therefore show the latest scan's data, not a complete multi-day history. A durable shared journal/database is not yet configured.

The repository also includes Python test/quality checks, CodeQL, dependency review, pip-audit and Dependabot workflows. Repository-level security settings (such as secret scanning and Dependabot alerts) must be checked separately in GitHub Settings.

## Install and run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m oracle.main
```

## Limitations and safety

- PAPER/research only: no broker integration, order placement, position sizing or execution.
- News scoring is a transparent phrase-based heuristic, not a validated predictive model.
- Stop and target levels are illustrative ATR calculations, not guaranteed outcomes.
- Yahoo Finance is not an official exchange feed and can be delayed or unavailable.
- A successful Telegram API response confirms API acceptance, not that a person read the message.
- No paid data services are required.

## Tests

`python -m unittest discover -s tests -v`
