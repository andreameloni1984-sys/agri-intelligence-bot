from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from .config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from .models import EVENTS, event_kind

ROME = ZoneInfo("Europe/Rome")
LABELS = {"LONG": "🟢 LONG", "SHORT": "🔴 SHORT", "NON DETERMINABILE": "⚪ NON DETERMINABILE"}


def format_message(event, analysis, source, preliminary=False, update=False):
    stamp = datetime.fromisoformat(event["date_utc"]).astimezone(ROME)
    phase = "PREVISIONE PRELIMINARE" if preliminary else "ANALISI DEL DATO PUBBLICATO"
    if update:
        phase += " — AGGIORNAMENTO"
    title = EVENTS[event_kind(event["event"])][1]
    directions = [f"{rank}. {asset.upper()} — {LABELS[direction]}"
                  for rank, (asset, direction) in enumerate(analysis.directions.items(), 1)]
    return "\n".join([
        "🔴 STELLA ROSSA — CALENDARIO USA",
        phase,
        "",
        f"📰 Evento: {title}",
        *(directions or ["⚪ Direzione non determinabile"]),
        "",
        f"📊 Motivo: {analysis.reason}",
        f"🕒 Orario: {stamp:%d/%m/%Y %H:%M %Z}",
        f"🔗 Fonte: {source}",
        "PAPER ONLY",
    ])


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return "unconfigured"
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message,
                  "link_preview_options": {"is_disabled": True}},
            timeout=10,
        )
        if response.status_code == 429:
            return "retry"
        if 400 <= response.status_code < 500:
            return "retry"
        if response.status_code >= 500:
            return "unknown"
        return "delivered" if response.json().get("ok") else "retry"
    except requests.ConnectTimeout:
        return "retry"
    except (requests.RequestException, ValueError):
        # A read timeout can occur after the API accepted the message.
        return "unknown"
