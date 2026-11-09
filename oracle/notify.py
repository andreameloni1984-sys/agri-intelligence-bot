import requests
from .config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from .models import Signal

def send_telegram(signal: Signal):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[TELEGRAM] credentials missing; alert not sent")
        return False
    label = "EARLY SETUP — da confermare" if signal.setup_type == "EARLY_SETUP" else "SEGNALE CONFERMATO"
    message = (f"🔴 STELLA ROSSA — {label} — {signal.direction}\n"
        f"Strumento: {signal.instrument} ({signal.symbol})\n"
        f"Confidenza euristica: {signal.confidence}/100\n"
        f"Prezzo riferimento: {signal.reference_price:.4f}\n"
        f"Stop: {signal.stop_loss:.4f}\nTP1: {signal.target_1:.4f}\nTP2: {signal.target_2:.4f}\n"
        f"{signal.rationale}\n" + "\n".join(signal.news_urls[:3]) +
        "\nRicerca/paper only — nessun ordine eseguito.")
    try:
        response = requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                                 json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=15)
        response.raise_for_status()
        accepted = bool(response.json().get("ok"))
        print(f"[TELEGRAM] API accepted={accepted}")
        return accepted
    except Exception as exc:
        print(f"[TELEGRAM] send error: {type(exc).__name__}")
        return False


def send_telegram_status(message: str) -> bool:
    """Send a scan heartbeat independently from trading-signal notifications."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[TELEGRAM] credentials missing; scan status not sent")
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
            timeout=15,
        )
        response.raise_for_status()
        accepted = bool(response.json().get("ok"))
        print(f"[TELEGRAM] scan status accepted={accepted}")
        return accepted
    except Exception as exc:
        print(f"[TELEGRAM] scan status error: {type(exc).__name__}")
        return False
