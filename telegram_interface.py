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
    from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
    from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters
    import asyncio
    from config import TELEGRAM_BOT_TOKEN

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError('TELEGRAM_BOT_TOKEN non configurato')

    def menu():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton('🍼 Latte', callback_data='latte'),
             InlineKeyboardButton('🌾 Mangime/Fieno', callback_data='feed')],
            [InlineKeyboardButton('🐑 Animale', callback_data='animal'),
             InlineKeyboardButton('💰 Spesa/Ricavo', callback_data='money')],
            [InlineKeyboardButton('⛽ Gasolio', callback_data='fuel'),
             InlineKeyboardButton('📊 Oggi', callback_data='today')],
            [InlineKeyboardButton('📋 Aiuto', callback_data='help')]
        ])

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            '🐑 AGRI INTELLIGENCE\\n\\nCosa vuoi registrare?',
            reply_markup=menu()
        )

    async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
        q=update.callback_query
        await q.answer()
        prompts={
            'latte':'🍼 Scrivi quanti litri di latte hai prodotto.\\nEsempio: 126 litri',
            'feed':'🌾 Scrivi quanti kg di mangime/fieno hai usato.\\nEsempio: 90 kg fieno',
            'fuel':'⛽ Scrivi quanti litri di gasolio hai consumato.\\nEsempio: 30 litri',
            'animal':'🐑 Scrivi cosa è successo.\\nEsempio: nato 342\\nOppure: morto 342\\nOppure: venduto 342 250',
            'money':'💰 Scrivi spesa o ricavo.\\nEsempio: spesa mangime 85 fieno\\nOppure: ricavo latte 150',
            'today':'📊 Sto preparando il riepilogo...',
            'help':HELP
        }
        if q.data=='today':
            from engines.intelligence import farm_snapshot
            x=farm_snapshot()
            msg=(f"🐑 AZIENDA OGGI\\n• Animali: {x['present']}\\n• Latte: {x['milk']:.1f} L\\n• Mangime/fieno: {x['feed']:.1f} kg\\n• Gasolio: {x['fuel']:.1f} L\\n• Terreni: {x['ha']:.2f} ha\\n• Ricavi: €{x['income']:.2f}\\n• Spese: €{x['expense']:.2f}\\n• Saldo: €{x['income']-x['expense']:.2f}")
            await q.edit_message_text(msg, reply_markup=menu())
        else:
            context.user_data['waiting_for']=q.data
            await q.edit_message_text(prompts[q.data], reply_markup=menu())

    async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        text=update.message.text or ''
        waiting=context.user_data.get('waiting_for')
        if waiting=='latte' and not text.startswith('/'):
            reply=handle_command('/latte '+text)
        elif waiting=='feed' and not text.startswith('/'):
            reply=handle_command('/mangime '+text)
        elif waiting=='fuel' and not text.startswith('/'):
            reply=handle_command('/gasolio '+text)
        elif waiting=='animal' and not text.startswith('/'):
            t=text.lower()
            if t.startswith('nato '): reply=handle_command('/nato '+text[5:])
            elif t.startswith('morto '): reply=handle_command('/morto '+text[6:])
            elif t.startswith('venduto '): reply=handle_command('/venduto '+text[8:])
            else: reply='Scrivi: nato TAG, morto TAG oppure venduto TAG PREZZO.'
        elif waiting=='money' and not text.startswith('/'):
            reply=handle_command('/'+text)
        else:
            reply=handle_command(text)
        context.user_data.pop('waiting_for',None)
        await update.message.reply_text(reply, reply_markup=menu())

    async def main():
        app=Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        app.add_handler(CommandHandler('start', start))
        app.add_handler(CommandHandler(['aiuto','help','oggi','latte','mangime','gasolio','nato','venduto','morto','spesa','ricavo','animali'], lambda u,c: text_message(u,c)))
        app.add_handler(CallbackQueryHandler(button))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        await asyncio.Event().wait()

    asyncio.run(main())
