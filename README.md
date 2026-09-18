# 🐑 AGRI INTELLIGENCE BOT V1

Bot modulare per il monitoraggio di un'azienda agricola con allevamento ovino, con focus iniziale Sardegna.

## V1
- ISMEA: prezzi ovicaprini e lattiero-caseari
- Regione Sardegna: radar bandi
- storico locale SQLite
- motore trend/anomalie
- report Telegram on-demand
- GitHub Actions per esecuzione programmata

## Comandi Telegram
`/report` `/prezzi` `/bandi` `/costi` `/azienda` `/alert`

## Configurazione
Copia `.env.example` in `.env` e inserisci `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`.

Il parser delle pagine istituzionali è volutamente separato dai motori: se una fonte cambia struttura, si modifica solo il relativo modulo.
