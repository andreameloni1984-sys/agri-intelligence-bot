"""Persistent Render worker: execute one ORACLE scan every five minutes."""
import logging
import time
from datetime import datetime, timezone

from .main import main

INTERVAL_SECONDS = 300


def run_forever():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.info("STELLA ROSSA worker starting; interval=%ss", INTERVAL_SECONDS)
    while True:
        started = time.monotonic()
        stamp = datetime.now(timezone.utc).isoformat()
        try:
            logging.info("scan cycle started at %s", stamp)
            main()
            logging.info("scan cycle completed")
        except Exception:
            logging.exception("scan cycle crashed; worker will retry next cycle")
        elapsed = time.monotonic() - started
        delay = max(0, INTERVAL_SECONDS - elapsed)
        logging.info("next scan in %.1f seconds", delay)
        time.sleep(delay)


if __name__ == "__main__":
    run_forever()
