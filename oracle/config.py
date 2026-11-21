import os
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "data/oracle.sqlite3")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
EVENT_CONTEXT_URL = os.getenv("EVENT_CONTEXT_URL", "")
# BLS (and DOL) reject automated requests whose User-Agent has no contact e-mail.
CONTACT_EMAIL = os.getenv("STELLA_CONTACT_EMAIL", "")
