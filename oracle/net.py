"""Single HTTP entry point: identified User-Agent, shared connections, explicit timeouts."""
import logging

import requests

from .config import CONTACT_EMAIL

USER_AGENT = ("Stella-Rossa/1.0 (paper-only research bot; contact: %s)" % CONTACT_EMAIL
              if CONTACT_EMAIL else "Stella-Rossa/1.0 (paper-only research bot)")
if not CONTACT_EMAIL:
    logging.getLogger(__name__).warning(
        "STELLA_CONTACT_EMAIL non impostata: BLS rifiuta le richieste senza e-mail nello User-Agent")

_session = requests.Session()
_session.headers["User-Agent"] = USER_AGENT


def get(url, timeout=10, **kwargs):
    response = _session.get(url, timeout=timeout, **kwargs)
    response.raise_for_status()
    return response
