"""Send one message clearly marked TEST, built from the verified 19/11/2026 claims replay."""
from .analysis import interpret
from .models import Context, Release
from .notify import format_message, send_telegram

EVENT = {"id": "TEST", "event": "Unemployment Insurance Weekly Claims",
         "date_utc": "2026-11-19T13:30:00+00:00", "url": "https://www.dol.gov/ui/data.pdf"}


def main():
    release = Release({"claims": 203000}, EVENT["url"], {"claims": 200000}, {"claims": 202000})
    analysis = interpret("claims", release, Context(consensus={"claims": 198000}))
    result = send_telegram(format_message(EVENT, analysis, release.url, test=True))
    print(f"[TEST] telegram_delivery={result}")
    if result != "delivered":
        raise SystemExit(f"Telegram non consegnato: {result}")


if __name__ == "__main__":
    main()
