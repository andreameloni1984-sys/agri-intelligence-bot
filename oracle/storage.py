"""SQLite journal shared by scheduler cycles on the worker's persistent disk."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .config import DB_PATH


def connect():
    path = Path(DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=25)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS stella_state (
            key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS stella_results (
            event_id TEXT NOT NULL, phase TEXT NOT NULL, fingerprint TEXT NOT NULL,
            observed_at TEXT NOT NULL, payload TEXT NOT NULL, delivery TEXT NOT NULL,
            PRIMARY KEY (event_id, phase, fingerprint));
    """)
    return db


def load(key, default=None):
    with closing(connect()) as db:
        row = db.execute("SELECT value FROM stella_state WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def save(key, value):
    with closing(connect()) as db, db:
        db.execute("INSERT OR REPLACE INTO stella_state VALUES (?,?)", (key, json.dumps(value)))


def last_result(event_id, phase):
    with closing(connect()) as db:
        row = db.execute("""SELECT payload, delivery FROM stella_results
            WHERE event_id=? AND phase=? ORDER BY rowid DESC LIMIT 1""", (event_id, phase)).fetchone()
    return (json.loads(row[0]), row[1]) if row else (None, None)


def record(event_id, phase, fingerprint, now, payload):
    """Claim delivery before calling Telegram, even across overlapping processes."""
    with closing(connect()) as db, db:
        cursor = db.execute("""INSERT OR IGNORE INTO stella_results VALUES (?,?,?,?,?,?)""",
                            (event_id, phase, fingerprint, now.isoformat(), json.dumps(payload), "pending"))
        if cursor.rowcount:
            return True
        cursor = db.execute("""UPDATE stella_results SET delivery='pending'
            WHERE event_id=? AND phase=? AND fingerprint=? AND delivery='retry'""",
            (event_id, phase, fingerprint))
        return bool(cursor.rowcount)


def finish(event_id, phase, fingerprint, delivery):
    with closing(connect()) as db, db:
        db.execute("""UPDATE stella_results SET delivery=?
            WHERE event_id=? AND phase=? AND fingerprint=? AND delivery='pending'""",
            (delivery, event_id, phase, fingerprint))
