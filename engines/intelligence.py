from datetime import date


def market_signal(items):
    if not items:
        return "⚪ Nessun dato di mercato."

    moves = [
        x["weekly_change"]
        for x in items
        if x.get("weekly_change") is not None
    ]

    if not moves:
        return "⚪ Dati presenti, variazione non disponibile."

    avg = sum(moves) / len(moves)

    if avg >= 2:
        return f"🟢 Pressione rialzista media: {avg:+.1f}% settimanale"

    if avg <= -2:
        return f"🔴 Pressione ribassista media: {avg:+.1f}% settimanale"

    return f"🟡 Mercato relativamente stabile: {avg:+.1f}% settimanale"


def report(prices, grants):
    s = [
        "🐑 AGRI INTELLIGENCE",
        date.today().strftime("%d/%m/%Y"),
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    s.append("💰 MERCATO")
    s.append(market_signal(prices))

    for x in prices[:8]:
        ch = x.get("weekly_change")
        chs = f"{ch:+.1f}%" if ch is not None else "n/d"

        s.append(
            f"• {x['market']} — "
            f"{x['product'][:42]}: "
            f"{x['price']:.2f} {x['unit']} ({chs})"
        )

    s.append("")
    s.append(
        f"🏛️ BANDI: {len(grants)} "
        "opportunità/risultati rilevati"
    )

    s.append("🧠 Motore: dati → confronto → impatto → alert")

    return "\n".join(s)