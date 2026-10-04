from datetime import date
import re
from database import execute, today

HELP = """🐑 AGRI INTELLIGENCE — COMANDI

/oggi — riepilogo aziendale
/latte 120 — registra litri di latte
/mangime 80 — registra kg di mangime/fieno
/gasolio 30 — registra litri di gasolio
/nato TAG — registra un nuovo animale
/venduto TAG PREZZO — registra vendita
/morto TAG — registra morte
/spesa CATEGORIA IMPORTO DESCRIZIONE
/ricavo CATEGORIA IMPORTO DESCRIZIONE
/animali — numero animali presenti
/aiuto — mostra i comandi

Esempio:
/latte 125
/spesa mangime 85 acquisto fieno
"""

def _num(text):
    m=re.search(r'(-?\d+(?:[\.,]\d+)?)', text)
    return float(m.group(1).replace(',','.')) if m else None

def handle_command(text):
    parts=text.strip().split(maxsplit=3)
    if not parts: return HELP
    cmd=parts[0].lower().split('@')[0]
    args=parts[1:]
    if cmd in ('/start','/aiuto','/help'):
        return HELP
    if cmd=='/oggi':
        from engines.intelligence import farm_snapshot
        q=farm_snapshot()
        return (f"🐑 AZIENDA OGGI\n• Animali: {q['present']}\n• Nuova leva: {q['recruit']}\n• Latte: {q['milk']:.1f} L\n• Mangime/fieno: {q['feed']:.1f} kg\n• Gasolio: {q['fuel']:.1f} L\n• Terreni: {q['ha']:.2f} ha\n• Ricavi: €{q['income']:.2f}\n• Spese: €{q['expense']:.2f}\n• Saldo: €{q['income']-q['expense']:.2f}")
    if cmd=='/latte':
        n=_num(text)
        if n is None: return 'Uso: /latte 120'
        execute("INSERT INTO milk_production (production_date,liters) VALUES (?,?)",(today(),n))
        return f'🍼 Registrati {n:.1f} L di latte.'
    if cmd=='/mangime':
        n=_num(text)
        if n is None: return 'Uso: /mangime 80'
        execute("INSERT INTO feed_consumption (consumption_date,feed_type,quantity_kg) VALUES (?,?,?)",(today(),'mangime/fieno',n))
        return f'🌾 Registrati {n:.1f} kg di mangime/fieno.'
    if cmd=='/gasolio':
        n=_num(text)
        if n is None: return 'Uso: /gasolio 30'
        execute("INSERT INTO fuel_consumption (consumption_date,liters) VALUES (?,?)",(today(),n))
        return f'⛽ Registrati {n:.1f} L di gasolio.'
    if cmd=='/nato':
        if not args: return 'Uso: /nato TAG'
        tag=args[0]
        try:
            execute("INSERT INTO animals (tag,species,status,birth_date) VALUES (?,?,?,?)",(tag,'ovino','new_recruit',today()))
            return f'🐑 Nuovo animale registrato: {tag}.'
        except Exception: return f'⚠️ Il codice {tag} esiste già.'
    if cmd=='/venduto':
        if len(args)<2: return 'Uso: /venduto TAG PREZZO'
        tag=args[0]; price=_num(args[1])
        if price is None: return 'Uso: /venduto TAG PREZZO'
        con_id=execute("UPDATE animals SET status='sold',sale_date=?,sale_price=?,updated_at=CURRENT_TIMESTAMP WHERE tag=?",(today(),price,tag))
        if not con_id: return f'⚠️ Animale {tag} non trovato.'
        execute("INSERT INTO financial_transactions (transaction_date,transaction_type,category,description,amount) VALUES (?,?,?,?,?)",(today(),'income','vendita animale',tag,price))
        return f'💰 Vendita registrata: {tag} — €{price:.2f}.'
    if cmd=='/morto':
        if not args: return 'Uso: /morto TAG'
        tag=args[0]
        con_id=execute("UPDATE animals SET status='dead',death_date=?,updated_at=CURRENT_TIMESTAMP WHERE tag=?",(today(),tag))
        return f'☑️ Morte registrata: {tag}.' if con_id else f'⚠️ Animale {tag} non trovato.'
    if cmd in ('/spesa','/ricavo'):
        if len(args)<2: return f'Uso: {cmd} CATEGORIA IMPORTO DESCRIZIONE'
        category=args[0]; amount=_num(args[1])
        if amount is None: return f'Uso: {cmd} CATEGORIA IMPORTO DESCRIZIONE'
        desc=args[2] if len(args)>2 else ''
        typ='expense' if cmd=='/spesa' else 'income'
        execute("INSERT INTO financial_transactions (transaction_date,transaction_type,category,description,amount) VALUES (?,?,?,?,?)",(today(),typ,category,desc,amount))
        return f'{"💸 Spesa" if typ=="expense" else "💰 Ricavo"} registrato: €{amount:.2f}.'
    if cmd=='/animali':
        from database import connect
        con=connect(); n=con.execute("SELECT COUNT(*) FROM animals WHERE status IN ('present','new_recruit')").fetchone()[0]; con.close()
        return f'🐑 Animali presenti: {n}'
    return '❓ Comando non riconosciuto. Usa /aiuto.'

def run_bot():
    from telegram import Bot
    from telegram.ext import Application, CommandHandler, MessageHandler, filters
    import asyncio
    from config import TELEGRAM_BOT_TOKEN
    if not TELEGRAM_BOT_TOKEN: raise RuntimeError('TELEGRAM_BOT_TOKEN non configurato')
    async def reply(update, context):
        if not update.message: return
        await update.message.reply_text(handle_command(update.message.text or ''))
    async def main():
        app=Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        app.add_handler(CommandHandler(['start','aiuto','help','oggi','latte','mangime','gasolio','nato','venduto','morto','spesa','ricavo','animali'], reply))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply))
        await app.initialize(); await app.start(); await app.updater.start_polling()
        await asyncio.Event().wait()
    asyncio.run(main())
