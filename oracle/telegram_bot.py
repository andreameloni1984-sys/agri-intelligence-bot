"""Persistent Telegram polling service for ORACLE.

Run as a long-lived process: python -m oracle.telegram_bot
Do not run this together with another getUpdates poller for the same bot token.
"""
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from .config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from .storage import get_status, get_latest_signals, get_latest_quotes, get_upcoming_events

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("oracle.telegram")


def _authorized(update: Update) -> bool:
    chat = update.effective_chat
    return bool(chat and TELEGRAM_CHAT_ID and str(chat.id) == str(TELEGRAM_CHAT_ID))


async def _reply(update: Update, text: str):
    if not update.effective_message:
        return
    if not _authorized(update):
        log.warning("Ignored Telegram command from unauthorized chat")
        return
    await update.effective_message.reply_text(text[:3900], disable_web_page_preview=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _reply(update,
        "🛰️ ORACLE — INTELLIGENCE\n\n"
        "/status — stato ultima scansione\n"
        "/report — ultime ipotesi direzionali\n"
        "/prezzi — ultime quotazioni\n"
        "/calendario — prossimi eventi economici\n"
        "/help — guida comandi\n\n"
        "Analisi informativa, paper only: nessun ordine viene eseguito.")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    last, count = get_status()
    if not last:
        await _reply(update, "ORACLE: nessuna scansione registrata.")
        return
    await _reply(update,
        "🛰️ ORACLE — STATO\n"
        f"Ultima scansione: {last['started_at']}\n"
        f"Notizie: {last['news_count']}\n"
        f"Strumenti controllati: {last['instruments_checked']}\n"
        f"Ipotesi direzionali oggi: {count}\n"
        "Modalità ricerca/paper — nessun ordine.")


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = get_latest_signals(5)
    if not rows:
        await _reply(update, "ORACLE — nessuna ipotesi direzionale registrata.")
        return
    lines = ["🛰️ ORACLE — ULTIME IPOTESI"]
    for row in rows:
        lines.append(
            f"{row['instrument']} {row['direction']} | confidenza euristica {row['confidence']}/100\n"
            f"Prezzo {row['reference_price']} | SL {row['stop_loss']} | "
            f"TP1 {row['target_1']} | TP2 {row['target_2']}\n{row['created_at']}"
        )
    lines.append("Confidenza euristica, non probabilità validata. Nessun ordine eseguito.")
    await _reply(update, "\n\n".join(lines))


async def prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = get_latest_quotes()
    if not rows:
        await _reply(update, "ORACLE — nessuna quotazione salvata.")
        return
    lines = ["📊 ORACLE — ULTIME QUOTAZIONI"]
    lines.extend(f"{x['symbol']}: {x['last']} | {x['timestamp']}" for x in rows)
    lines.append("Fonte Yahoo Finance; dati indicativi, non broker.")
    await _reply(update, "\n".join(lines))


async def calendar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = get_upcoming_events(8)
    if not rows:
        await _reply(update, "ORACLE — nessun evento futuro salvato.")
        return
    lines = ["📅 ORACLE — CALENDARIO"]
    lines.extend(f"{x['date_utc']} | {x['event']} ({x['source']})" for x in rows)
    await _reply(update, "\n".join(lines))


def build_application():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN non configurato")
    if not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_CHAT_ID non configurato: serve per autorizzare la chat")
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(CommandHandler(["prezzi", "prices"], prices))
    app.add_handler(CommandHandler(["calendario", "calendar"], calendar))
    return app


def main():
    log.info("Starting persistent ORACLE Telegram polling service")
    build_application().run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
        close_loop=True,
    )


if __name__ == "__main__":
    main()
