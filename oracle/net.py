"""Single HTTP entry point: identified User-Agent, shared connections, explicit timeouts.

The contact e-mail (STELLA_CONTACT_EMAIL) is sent only to the agencies that ask for
it in the User-Agent (BLS, DOL); every other site gets a User-Agent without it.
"""
import logging
from urllib.parse import urlparse

import requests

from .config import CONTACT_EMAIL

BASE_USER_AGENT = "Stella-Rossa/1.0 (paper-only research bot)"
CONTACT_HOSTS = ("bls.gov", "dol.gov")
CONTACT_USER_AGENT = (f"Stella-Rossa/1.0 (paper-only research bot; contact: {CONTACT_EMAIL})"
                      if CONTACT_EMAIL else BASE_USER_AGENT)
if not CONTACT_EMAIL:
    logging.getLogger(__name__).info(
        "STELLA_CONTACT_EMAIL non impostata: BLS/DOL ricevono uno User-Agent senza e-mail")

_session = requests.Session()
_session.headers["User-Agent"] = BASE_USER_AGENT


def user_agent_for(url):
    host = (urlparse(url).hostname or "").lower()
    if any(host == h or host.endswith("." + h) for h in CONTACT_HOSTS):
        return CONTACT_USER_AGENT
    return BASE_USER_AGENT


def get(url, timeout=10, **kwargs):
    headers = {"User-Agent": user_agent_for(url), **(kwargs.pop("headers", None) or {})}
    response = _session.get(url, timeout=timeout, headers=headers, **kwargs)
    response.raise_for_status()
    return response
