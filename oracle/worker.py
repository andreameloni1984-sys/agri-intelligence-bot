"""Persistent event scheduler."""
from datetime import datetime, timezone
import logging
import time

from .main import main


def run_forever():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.info("STELLA ROSSA — calendario USA, PAPER ONLY")
    while True:
        try:
            started = datetime.now(timezone.utc)
            delay = main(now=started)
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            time.sleep(max(1, delay - elapsed))
        except Exception:
            logging.exception("Errore del pianificatore, nuovo tentativo tra 30 secondi")
            time.sleep(30)


if __name__ == "__main__":
    run_forever()
