from datetime import datetime
import logging
from zoneinfo import ZoneInfo

import requests

from .config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from .levels import MAX_MINUTES, lines as level_lines
from .models import EVENTS, event_kind

ROME = ZoneInfo("Europe/Rome")
MEDALS = ("🥇", "🥈")


def format_message(event, analysis, source, preliminary=False, test=False, levels=None):
    """Plain message; PREVISIONE (before the release) vs DATO PUBBLICATO (official figure)."""
    stamp = datetime.fromisoformat(event["date_utc"]).astimezone(ROME)
    status = ("PREVISIONE — dato non ancora pubblicato" if preliminary
              else "DATO PUBBLICATO — analisi del valore ufficiale")
    levels = levels or {}
    lines = []
    for medal, (asset, direction) in zip(MEDALS, analysis.directions.items()):
        lines.append(f"{medal} {asset.upper()} — {direction}")
        if asset in levels and direction in {"LONG", "SHORT"}:
            lines += level_lines(asset, direction, levels[asset])
    if levels:
        lines.append(f"⏱️ Se dopo {MAX_MINUTES} minuti non ha toccato né stop né take profit, chiudi la posizione.")
    return "\n".join([
        ("🧪 TEST — " if test else "") + "🔴 STELLA ROSSA",
        "",
        f"📅 Evento: {EVENTS[event_kind(event['event'])][1]}",
        f"🕒 Pubblicazione: {stamp:%H:%M} Italia ({stamp:%d/%m/%Y})",
        "",
        *(lines or ["⚪ Previsione non disponibile"]),
        "",
        f"📊 Motivo: {analysis.reason}",
        "",
        f"🎯 Stato: {status}",
        f"🔗 Fonte: {source}",
        "",
        "PAPER ONLY" + (" — MESSAGGIO DI TEST" if test else ""),
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
            # Wrong token/chat or malformed request: retrying every cycle would not help.
            logging.error("[TELEGRAM] rejected status=%s", response.status_code)
            return "rejected"
        if response.status_code >= 500:
            return "unknown"
        return "delivered" if response.json().get("ok") else "retry"
    except requests.ConnectTimeout:
        return "retry"
    except (requests.RequestException, ValueError):
        # A read timeout can occur after the API accepted the message.
        return "unknown"
