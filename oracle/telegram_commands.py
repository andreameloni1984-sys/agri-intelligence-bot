"""Small Telegram polling interface for read-only ORACLE reports.

Commands are processed only from the configured TELEGRAM_CHAT_ID.
No order placement or account actions are exposed.
"""
import re
import requests
from .config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from .storage import get_status, get_latest_signals, get_latest_quotes, get_upcoming_events

API = "https://api.telegram.org"


def _send(chat_id, text):
    response = requests.post(
        f"{API}/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": chat_id, "text": text[:3900], "disable_web_page_preview": True},
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError("Telegram rejected sendMessage")
    return True


def _format_status():
    last, count = get_status()
    if not last:
        return "ORACLE: nessuna scansione registrata finora."
    return (
        "🛰️ ORACLE — STATO\n"
        f"Ultima scansione: {last['started_at']}\n"
        f"Notizie raccolte: {last['news_count']}\n"
        f"Strumenti controllati: {last['instruments_checked']}\n"
        f"Ipotesi direzionali registrate oggi: {count}\n"
        "Modalità ricerca/paper: nessun ordine eseguito."
    )


def _format_report():
    rows = get_latest_signals(5)
    if not rows:
        return "ORACLE — nessuna ipotesi direzionale registrata."
    lines = ["🛰️ ORACLE — ULTIME IPOTESI"]
    for row in rows:
        lines.append(
            f"{row['instrument']} {row['direction']} | confidenza euristica {row['confidence']}/100\n"
            f"Prezzo {row['reference_price']} | SL {row['stop_loss']} | "
            f"TP1 {row['target_1']} | TP2 {row['target_2']}\n{row['created_at']}"
        )
    lines.append("Ipotesi informative, non probabilità validate; nessun ordine eseguito.")
    return "\n\n".join(lines)


def _format_prices():
    rows = get_latest_quotes()
    if not rows:
        return "ORACLE — nessuna quotazione salvata."
    lines = ["📊 ORACLE — ULTIME QUOTAZIONI"]
    for row in rows:
        lines.append(f"{row['symbol']}: {row['last']} | dato {row['timestamp']}")
    lines.append("Fonte: Yahoo Finance; quotazioni indicative, non esecuzione broker.")
    return "\n".join(lines)


def _format_calendar():
    rows = get_upcoming_events(8)
    if not rows:
        return "ORACLE — nessun evento futuro salvato. Calendario: BLS, EIA e USDA/Fed quando disponibili."
    lines = ["📅 ORACLE — PROSSIMI EVENTI"]
    for row in rows:
        lines.append(f"{row['date_utc']} | {row['event']} ({row['source']})")
    return "\n".join(lines)


def handle_command(command):
    command = re.split(r"\s+", command.strip(), maxsplit=1)[0].split("@", 1)[0].lower()
    if command in ("/start", "/help"):
        return (
            "🛰️ ORACLE — COMANDI\n"
            "/status — stato ultima scansione\n"
            "/report — ultime ipotesi direzionali\n"
            "/prezzi — ultime quotazioni salvate\n"
            "/calendario — prossimi eventi economici\n"
            "Scansione automatica ogni 5 minuti quando GitHub Actions è attivo."
        )
    if command == "/status":
        return _format_status()
    if command == "/report":
        return _format_report()
    if command in ("/prezzi", "/prices"):
        return _format_prices()
    if command in ("/calendario", "/calendar"):
        return _format_calendar()
    return "Comando non riconosciuto. Scrivi /help."


def poll_telegram_commands():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[TELEGRAM] command polling skipped: credentials missing")
        return 0
    try:
        response = requests.get(
            f"{API}/bot{TELEGRAM_BOT_TOKEN}/getUpdates",
            params={"timeout": 0, "limit": 50, "allowed_updates": '["message"]'},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError("Telegram rejected getUpdates (check webhook/polling mode)")
        updates = payload.get("result", [])
        highest_id = None
        processed = 0
        for update in updates:
            highest_id = max(highest_id or 0, int(update.get("update_id", 0)))
            message = update.get("message") or {}
            chat = message.get("chat") or {}
            text = (message.get("text") or "").strip()
            if str(chat.get("id", "")) != str(TELEGRAM_CHAT_ID) or not text.startswith("/"):
                continue
            answer = handle_command(text)
            _send(chat.get("id"), answer)
            processed += 1
        # Confirm updates after replies were sent; a later scheduled run won't replay them.
        if highest_id is not None:
            confirm = requests.get(
                f"{API}/bot{TELEGRAM_BOT_TOKEN}/getUpdates",
                params={"offset": highest_id + 1, "timeout": 0, "limit": 1},
                timeout=10,
            )
            confirm.raise_for_status()
        print(f"[TELEGRAM] commands_processed={processed}")
        return processed
    except Exception as exc:
        print(f"[TELEGRAM] command polling error: {type(exc).__name__}")
        return 0
