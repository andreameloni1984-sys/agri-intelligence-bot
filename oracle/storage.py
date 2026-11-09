import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from .config import DB_PATH
from .models import Signal


def connect():
    path = Path(DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS runs (
        id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, instrument TEXT NOT NULL,
        symbol TEXT NOT NULL, status TEXT NOT NULL, direction TEXT, confidence INTEGER,
        reference_price REAL, stop_loss REAL, target_1 REAL, target_2 REAL,
        rationale TEXT, news_urls TEXT, signal_key TEXT UNIQUE)""")
    db.execute("""CREATE TABLE IF NOT EXISTS scan_meta (
        id INTEGER PRIMARY KEY, started_at TEXT NOT NULL,
        news_count INTEGER NOT NULL, instruments_checked INTEGER NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS quote_snapshots (
        id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, last REAL NOT NULL,
        previous_close REAL NOT NULL, atr REAL NOT NULL, timestamp TEXT NOT NULL,
        UNIQUE(symbol, timestamp))""")
    db.execute("""CREATE TABLE IF NOT EXISTS calendar_events (
        event_id TEXT PRIMARY KEY, date_utc TEXT NOT NULL, event TEXT NOT NULL,
        country TEXT NOT NULL, source TEXT NOT NULL, importance TEXT NOT NULL, url TEXT NOT NULL)""")
    db.commit()
    return db


def save_scan_meta(started_at, news_count, instruments_checked):
    db = connect()
    db.execute("INSERT INTO scan_meta(started_at,news_count,instruments_checked) VALUES (?,?,?)",
               (started_at.isoformat(), news_count, instruments_checked))
    db.commit()
    db.close()


def save_quotes(quotes):
    if not quotes:
        return
    db = connect()
    for quote in quotes.values():
        db.execute("""INSERT OR IGNORE INTO quote_snapshots
            (symbol,last,previous_close,atr,timestamp) VALUES (?,?,?,?,?)""",
            (quote.symbol, quote.last, quote.previous_close, quote.atr, quote.timestamp.isoformat()))
    db.commit()
    db.close()


def save_calendar_events(events):
    if not events:
        return
    db = connect()
    for event in events:
        db.execute("""INSERT OR REPLACE INTO calendar_events
            (event_id,date_utc,event,country,source,importance,url) VALUES (?,?,?,?,?,?,?)""",
            (event["id"], event["date_utc"], event["event"], event["country"],
             event["source"], event["importance"], event["url"]))
    db.commit()
    db.close()


def _signal_dedup_key(signal: Signal) -> str:
    """Stable key for one instrument/direction per UTC hour."""
    hour_bucket = int(signal.created_at.timestamp() // 3600)
    material = "|".join([signal.instrument, signal.symbol, signal.direction, str(hour_bucket)])
    return hashlib.sha256(material.encode()).hexdigest()


def save_result(signal: Signal | None, instrument: str, symbol: str, status: str) -> bool:
    db = connect()
    if signal:
        # The same direction should be deduplicated within an hour, not forever.
        # A time bucket lets a still-valid setup alert again later while suppressing
        # the five-minute scan duplicates. News URLs are deliberately excluded:
        # changing headlines must not bypass deduplication for the same setup.
        key = _signal_dedup_key(signal)
        cursor = db.execute("""INSERT OR IGNORE INTO runs
        (created_at,instrument,symbol,status,direction,confidence,reference_price,
         stop_loss,target_1,target_2,rationale,news_urls,signal_key)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (signal.created_at.isoformat(), signal.instrument, signal.symbol, status,
         signal.direction, signal.confidence, signal.reference_price, signal.stop_loss,
         signal.target_1, signal.target_2, signal.rationale, json.dumps(signal.news_urls), key))
        inserted = cursor.rowcount == 1
    else:
        db.execute("INSERT INTO runs (created_at,instrument,symbol,status) VALUES (?,?,?,?)",
                   (datetime.now(timezone.utc).isoformat(), instrument, symbol, status))
        inserted = False
    db.commit()
    db.close()
    return inserted



def delete_signal(signal: Signal):
    """Remove an unsent alert so a later scheduled scan can retry it."""
    key = _signal_dedup_key(signal)
    db = connect()
    db.execute("DELETE FROM runs WHERE signal_key = ?", (key,))
    db.commit()
    db.close()


def get_status():
    db = connect()
    row = db.execute("SELECT started_at,news_count,instruments_checked FROM scan_meta ORDER BY id DESC LIMIT 1").fetchone()
    signals = db.execute("SELECT COUNT(*) AS n FROM runs WHERE direction IS NOT NULL AND created_at >= ?",
                         ((datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)).isoformat(),)).fetchone()["n"]
    db.close()
    return (dict(row) if row else None), signals


def get_latest_signals(limit=5):
    db = connect()
    rows = db.execute("""SELECT created_at,instrument,symbol,direction,confidence,
        reference_price,stop_loss,target_1,target_2,rationale
        FROM runs WHERE direction IS NOT NULL ORDER BY created_at DESC LIMIT ?""", (limit,)).fetchall()
    db.close()
    return [dict(row) for row in rows]


def get_latest_quotes():
    db = connect()
    rows = db.execute("""SELECT q.symbol,q.last,q.timestamp FROM quote_snapshots q
        JOIN (SELECT symbol,MAX(timestamp) AS ts FROM quote_snapshots GROUP BY symbol) x
        ON q.symbol=x.symbol AND q.timestamp=x.ts ORDER BY q.symbol""").fetchall()
    db.close()
    return [dict(row) for row in rows]


def get_upcoming_events(limit=8):
    db = connect()
    now = datetime.now(timezone.utc).isoformat()
    rows = db.execute("""SELECT date_utc,event,country,source,url FROM calendar_events
        WHERE date_utc >= ? ORDER BY date_utc LIMIT ?""", (now, limit)).fetchall()
    db.close()
    return [dict(row) for row in rows]


def get_scheduler_state(key, default=None):
    db = connect()
    db.execute("""CREATE TABLE IF NOT EXISTS scheduler_state (
        key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    row = db.execute("SELECT value FROM scheduler_state WHERE key=?", (key,)).fetchone()
    db.commit()
    db.close()
    if row is None:
        return default
    try:
        return json.loads(row["value"])
    except (TypeError, ValueError):
        return default


def save_scheduler_state(key, value):
    db = connect()
    db.execute("""CREATE TABLE IF NOT EXISTS scheduler_state (
        key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    db.execute("""INSERT OR REPLACE INTO scheduler_state(key,value,updated_at)
        VALUES (?,?,?)""",
        (key, json.dumps(value, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))
    db.commit()
    db.close()
