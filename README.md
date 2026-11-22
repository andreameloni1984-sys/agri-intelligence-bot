# Stella Rossa

Stella Rossa segue le pubblicazioni economiche USA e formula ipotesi direzionali sulle materie prime. Il bot opera in **PAPER ONLY** e non ha integrazioni con intermediari finanziari.

## Come funziona

- **Calendario ufficiale**: BLS (CPI, PPI, occupazione), BEA (PCE), DOL (richieste di disoccupazione, cadenza del giovedì; nelle settimane festive l'orario viene preso dal calendario settimanale ForexFactory), EIA (scorte petrolifere), Federal Reserve (FOMC) e USDA (WASDE). Gli orari sono convertiti da New York a UTC con `zoneinfo`; Telegram mostra l'ora italiana, quindi l'ora legale USA ed europea è gestita automaticamente. Se una fonte non risponde i suoi eventi non vengono inventati: restano quelli già in cache.
- **Scorte API del martedì sera** (`oracle/api_inventories.py`, workflow `stella-api.yml`): il sondaggio dell'American Petroleum Institute esce alle 22:30 italiane, circa 18 ore prima del dato EIA. La cifra viene letta dai titoli delle notizie (Google News, es. "crude stockpiles rose 5.3M barrels, API says") e confrontata con la previsione ForexFactory del dato EIA: scarto di almeno 1 milione di barili → WTI/Brent ⬆️ o ⬇️, altrimenti nessuna direzione. È una stima da fonte non ufficiale, inviata una sola volta a settimana; se i titoli si contraddicono non parte nulla.
- **T-30 minuti**: una sola previsione preliminare. Il consenso e il dato precedente vengono da ForexFactory (gratuito). Per CPI e PCE la stima indipendente è il nowcast della Fed di Cleveland, confrontato con il consenso alla stessa precisione di 0,1 punti. Se manca una stima verificabile il messaggio dice chiaramente "Previsione non disponibile".
- **Dalla pubblicazione**: il comunicato ufficiale viene interrogato ogni 15 secondi, poi ogni 30 secondi e poi ogni 2 minuti. Appena il dato è leggibile si confronta dato, consenso e revisioni, si inviano le due materie prime con direzione LONG/SHORT e ci si ferma. Nessuna soglia minima di sorpresa e nessuna conferma tecnica obbligatoria; dati mancanti o contraddittori producono "NON DETERMINABILE".
- **Diario** (`stella_journal` in SQLite): evento, orario, materie prime, direzioni, dati usati, ritardo della notifica e prezzi dei future (Yahoo, gratuito) al segnale e dopo 5, 15, 30 e 60 minuti. Esito CORRETTA solo se il prezzo è dalla parte prevista sia a 30 sia a 60 minuti; ERRATA se è dalla parte opposta in entrambi; altrimenti INCERTA. `python -m oracle.journal` mostra percentuale di direzioni corrette, copertura degli eventi e ritardo medio.
- **Telegram**: un messaggio per fase, con deduplicazione persistente. "PREVISIONE" significa prima del dato; "DATO PUBBLICATO" significa analisi del valore ufficiale. È un'ipotesi economica, non un movimento di prezzo già verificato. PAPER ONLY: nessun ordine.

## Esecuzione

```bash
pip install -r requirements.txt
cp .env.example .env            # imposta STELLA_CONTACT_EMAIL e i segreti Telegram
python -m unittest discover -s tests -v
python -m oracle.main --dry-run
```

**GitHub Actions** (`oracle.yml`): esegue ogni 10 minuti nei giorni feriali tra le 11:00 e le 21:59 UTC. Questa fascia contiene tutti gli eventi coperti, la previsione delle 08:00 di New York e il controllo dei prezzi a 60 minuti, sia in inverno sia in estate. Fuori dagli eventi la run legge solo il calendario in cache e termina. Se un controllo è previsto entro 45 minuti, la run resta attiva (`--loop-minutes 75`) e interroga la fonte ogni 15 secondi. Così i ritardi irregolari del cron di GitHub non ritardano la notifica. Lo stato (calendario, deduplicazione, diario) è conservato con `actions/cache`. Variabile del repository `STELLA_CONTACT_EMAIL`: l'e-mail di contatto viene inviata solo a BLS e DOL nello User-Agent; se manca non viene inviata nessuna e-mail. `stella-rossa-test.yml` esegue test, replay e calendario dal vivo; il messaggio Telegram marcato TEST viene inviato solo su richiesta.

**Host persistente** (alternativa gratuita, se servono notifiche ancora più rapide o se il cron di GitHub salta del tutto una fascia): `python -m oracle.worker` su una VM sempre accesa, per esempio Oracle Cloud Always Free, con `DB_PATH` su disco persistente. Disattiva lo schedule di `oracle.yml` per evitare doppioni.

Il feed opzionale `EVENT_CONTEXT_URL` riceve `GET ?event_id=<id>` e restituisce un oggetto JSON con `event_id`, `source_url` (HTTPS), `as_of` (ISO 8601 con offset e precedente alla pubblicazione) e mappe numeriche facoltative `consensus`, `previous` e `scenario`. Lo scenario rappresenta una stima indipendente e attribuita nella stessa unità del consenso. Per WASDE fornisci anche `periods` per identificare l'anno commerciale, per esempio `{"Corn": "2026/27"}`.

| Evento | Metriche del feed |
|---|---|
| CPI, PPI, PCE | `headline_mom_pct`, `core_mom_pct` in percentuale mensile. Per PPI, la misura core esclude alimentari, energia e servizi commerciali. |
| Occupazione | `payrolls` in posti di lavoro e `unemployment_pct` in percentuale. |
| Richieste di disoccupazione | `claims` in richieste. |
| EIA | `crude_mb`, `gasoline_mb`, `distillates_mb` come variazioni in milioni di barili. |
| FOMC | `upper_pct` come limite superiore dell'intervallo, in percentuale. |
| WASDE | `Wheat`, `Corn`, `Soybeans` come scorte finali USA in milioni di bushel. |

I test usano comunicati ufficiali reali (in `tests/fixtures`) e un replay completo degli eventi EIA del 18/11/2026 e DOL del 19/11/2026. Verificano lettura dei dati, logica e funzionamento; non misurano le prestazioni previsionali, che emergono dal diario.
