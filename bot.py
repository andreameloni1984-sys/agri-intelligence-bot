from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from config import TELEGRAM_BOT_TOKEN
from database import init_db
from sources.ismea_market import parse_ovicaprini, parse_lattiero_caseari
from sources.sardegna_bandi import fetch_bandi
from engines.intelligence import report

def collect():
    prices = parse_ovicaprini() + parse_lattiero_caseari()
    grants = fetch_bandi()
    return prices, grants

async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        prices, grants = collect()
        await update.message.reply_text(report(prices, grants))
    except Exception as e:
        await update.message.reply_text(f"⚠️ Errore raccolta dati: {e}")

async def cmd_prezzi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        prices, _ = collect()
        lines = ["💰 PREZZI OVINO — ISMEA"]
        for x in prices[:15]:
            ch = x.get("weekly_change")
            chs = f"{ch:+.1f}%" if ch is not None else "n/d"
            lines.append(f"{x['market']} | {x['product'][:38]} | {x['price']:.2f} {x['unit']} | {chs}")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"⚠️ {e}")

async def cmd_bandi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        grants = fetch_bandi()
        lines = ["🏛️ BANDI SARDEGNA"]
        for x in grants[:15]:
            lines.append(f"• {x['title']}\n{x['url']}")
        await update.message.reply_text("\n".join(lines)[:3900])
    except Exception as e:
        await update.message.reply_text(f"⚠️ {e}")

def main():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN non configurato")
    init_db()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("prezzi", cmd_prezzi))
    app.add_handler(CommandHandler("bandi", cmd_bandi))
    app.run_polling()

if __name__ == "__main__":
    main()
