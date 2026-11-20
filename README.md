# Stella Rossa

Stella Rossa segue le pubblicazioni economiche USA e formula ipotesi direzionali sulle materie prime. Il bot opera in **PAPER ONLY** e non ha integrazioni con intermediari finanziari.

## Come funziona

- Il calendario raccoglie CPI, PPI e occupazione (BLS), scorte petrolifere (EIA), decisioni FOMC (Federal Reserve), WASDE (USDA), PCE (BEA) e richieste di disoccupazione (DOL). Per il DOL usa la cadenza ufficiale del giovedì e omette le settimane a rischio di slittamento festivo, in attesa di un calendario verificabile. I calendari usano UTC internamente e Telegram mostra l'ora di Roma.
- Da 30 minuti prima, il bot cerca notizie Reuters pertinenti e aspettative attribuite. Invia una previsione preliminare quando uno scenario con fonte e orario differisce materialmente dal consenso. Il consenso da solo non costituisce uno scenario direzionale.
- All'orario previsto il worker cerca il dato ufficiale e riprova se il comunicato non è disponibile. La lettura confronta dato effettivo, consenso e revisioni disponibili. Per WASDE può usare la variazione della proiezione USDA dello stesso anno commerciale, esplicitando il confronto.
- La selezione tra Gold, Copper, Platinum, WTI, Brent, Wheat, Corn e Soybeans segue la trasmissione economica e, per WASDE, la dimensione degli scostamenti. Le evidenze contraddittorie o insufficienti producono una direzione non determinabile.
- Il worker ricontrolla il comunicato fino a due ore dopo l'evento. SQLite conserva dati, fonti e ultimo esito. Telegram avvisa in caso di variazione della conclusione. Un timeout dopo l'invio ha esito incerto, quindi il worker evita di ripetere quell'avviso.

## Configurazione

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m unittest discover -s tests -v
python -m oracle.main --dry-run
```

Usa un solo processo `python -m oracle.worker` con `DB_PATH` su disco persistente. Il Blueprint esistente configura il worker su Render. Imposta `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` come segreti del worker. Il workflow GitHub Actions è un'anteprima manuale senza invio Telegram.

Reuters viene consultata via ricerca RSS per evento. I sondaggi numerici sul greggio riconosciuti nel titolo possono fornire il consenso. Per una copertura più ampia configura facoltativamente `TRADING_ECONOMICS_API_KEY`, che richiede un accesso API valido, oppure un feed attendibile con `EVENT_CONTEXT_URL`. Il provider Trading Economics viene interrogato prima della pubblicazione e si accettano solo l'orario, l'evento USA e le unità corrispondenti. Il calendario e il dato effettivo restano quelli delle agenzie ufficiali.

Il feed opzionale riceve `GET ?event_id=<id>` e restituisce un oggetto JSON con `event_id`, `source_url` (HTTPS), `as_of` (ISO 8601 con offset e precedente alla pubblicazione) e mappe numeriche facoltative `consensus`, `previous` e `scenario`. Lo scenario rappresenta una stima indipendente e attribuita nella stessa unità del consenso. Per WASDE fornisci anche `periods` per identificare l'anno commerciale, per esempio `{"Corn": "2026/27"}`.

| Evento | Metriche del feed |
|---|---|
| CPI, PPI, PCE | `headline_mom_pct`, `core_mom_pct` in percentuale mensile. Per PPI, la misura core esclude alimentari, energia e servizi commerciali. |
| Occupazione | `payrolls` in posti di lavoro e `unemployment_pct` in percentuale. |
| Richieste di disoccupazione | `claims` in richieste. |
| EIA | `crude_mb`, `gasoline_mb`, `distillates_mb` come variazioni in milioni di barili. |
| FOMC | `upper_pct` come limite superiore dell'intervallo, in percentuale. |
| WASDE | `Wheat`, `Corn`, `Soybeans` come scorte finali USA in milioni di bushel. |

I test con comunicati storici verificano lettura e coerenza della logica economica. Non misurano le prestazioni previsionali.
