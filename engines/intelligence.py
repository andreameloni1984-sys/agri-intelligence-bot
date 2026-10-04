from datetime import date

def market_signal(items):
    if not items: return '⚪ Nessun dato di mercato.'
    moves=[x['weekly_change'] for x in items if x.get('weekly_change') is not None]
    if not moves: return '⚪ Dati presenti, variazione non disponibile.'
    avg=sum(moves)/len(moves)
    if avg>=2: return f'🟢 Pressione rialzista media: {avg:+.1f}% settimanale'
    if avg<=-2: return f'🔴 Pressione ribassista media: {avg:+.1f}% settimanale'
    return f'🟡 Mercato relativamente stabile: {avg:+.1f}% settimanale'

def farm_snapshot():
    try:
        from database import connect
        con=connect(); cur=con.cursor(); today=date.today().isoformat()
        a=cur.execute("SELECT SUM(CASE WHEN status IN ('present','new_recruit') THEN 1 ELSE 0 END) present, SUM(CASE WHEN status='new_recruit' THEN 1 ELSE 0 END) recruit, SUM(CASE WHEN status='sold' THEN 1 ELSE 0 END) sold, SUM(CASE WHEN status IN ('dead','culled') THEN 1 ELSE 0 END) losses FROM animals").fetchone()
        m=cur.execute('SELECT COALESCE(SUM(liters),0) v FROM milk_production WHERE production_date=?',(today,)).fetchone()
        f=cur.execute('SELECT COALESCE(SUM(quantity_kg),0) v FROM feed_consumption WHERE consumption_date=?',(today,)).fetchone()
        fuel=cur.execute('SELECT COALESCE(SUM(liters),0) v FROM fuel_consumption WHERE consumption_date=?',(today,)).fetchone()
        h=cur.execute('SELECT COALESCE(SUM(hectares),0) v FROM fields').fetchone()
        inc=cur.execute("SELECT COALESCE(SUM(amount),0) v FROM financial_transactions WHERE transaction_type='income' AND transaction_date=?",(today,)).fetchone()
        exp=cur.execute("SELECT COALESCE(SUM(amount),0) v FROM financial_transactions WHERE transaction_type='expense' AND transaction_date=?",(today,)).fetchone()
        con.close(); return {'present':a['present'] or 0,'recruit':a['recruit'] or 0,'sold':a['sold'] or 0,'losses':a['losses'] or 0,'milk':m['v'] or 0,'feed':f['v'] or 0,'fuel':fuel['v'] or 0,'ha':h['v'] or 0,'income':inc['v'] or 0,'expense':exp['v'] or 0}
    except Exception as e:
        print(f'⚠️ Snapshot aziendale non disponibile: {e}')
        return dict(present=0,recruit=0,sold=0,losses=0,milk=0,feed=0,fuel=0,ha=0,income=0,expense=0)

def report(prices, grants):
    s=['🐑 AGRI INTELLIGENCE',date.today().strftime('%d/%m/%Y'),'━━━━━━━━━━━━━━━━━━━━','💰 MERCATO',market_signal(prices)]
    for x in prices[:8]:
        ch=x.get('weekly_change'); chs=f'{ch:+.1f}%' if ch is not None else 'n/d'
        s.append(f"• {x['market']} — {x['product'][:42]}: {x['price']:.2f} {x['unit']} ({chs})")
    q=farm_snapshot(); s += ['', '🐑 AZIENDA', f"• Animali presenti: {q['present']}", f"• Nuova leva: {q['recruit']}", f"• Venduti: {q['sold']}", f"• Morti/eliminati: {q['losses']}", f"• Latte oggi: {q['milk']:.1f} L", f"• Mangime/fieno oggi: {q['feed']:.1f} kg", f"• Gasolio oggi: {q['fuel']:.1f} L", f"• Terreni: {q['ha']:.2f} ha", '', '💶 CONTABILITÀ OGGI', f"• Ricavi: €{q['income']:.2f}", f"• Spese: €{q['expense']:.2f}", f"• Saldo gestionale: €{q['income']-q['expense']:.2f}', '', f'🏛️ BANDI: {len(grants)} opportunità/risultati rilevati', '🧠 Motore: allevamento → produzione → consumi → costi → ricavi']
    return '\n'.join(s)
