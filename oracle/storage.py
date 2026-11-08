import hashlib
import json
import sqlite3
from pathlib import Path
from .config import DB_PATH
from .models import Signal

def connect():
    path = Path(DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("""CREATE TABLE IF NOT EXISTS runs (
        id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, instrument TEXT NOT NULL,
        symbol TEXT NOT NULL, status TEXT NOT NULL, direction TEXT, confidence INTEGER,
        reference_price REAL, stop_loss REAL, target_1 REAL, target_2 REAL,
        rationale TEXT, news_urls TEXT, signal_key TEXT UNIQUE)""")
    db.execute("""CREATE TABLE IF NOT EXISTS scan_meta (
        id INTEGER PRIMARY KEY, started_at TEXT NOT NULL,
        news_count INTEGER NOT NULL, instruments_checked INTEGER NOT NULL)""")
    db.commit()
    return db

def save_scan_meta(started_at, news_count, instruments_checked):
    db = connect()
    db.execute("INSERT INTO scan_meta(started_at,news_count,instruments_checked) VALUES (?,?,?)",
               (started_at.isoformat(), news_count, instruments_checked))
    db.commit()
    db.close()

def save_result(signal: Signal | None, instrument: str, symbol: str, status: str) -> bool:
    db = connect()
    if signal:
        material = "|".join([signal.instrument, signal.symbol, signal.direction, ",".join(sorted(signal.news_urls))])
        key = hashlib.sha256(material.encode()).hexdigest()
        cursor = db.execute("""INSERT OR IGNORE INTO runs
        (created_at,instrument,symbol,status,direction,confidence,reference_price,
         stop_loss,target_1,target_2,rationale,news_urls,signal_key)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (signal.created_at.isoformat(), signal.instrument, signal.symbol, status,
         signal.direction, signal.confidence, signal.reference_price, signal.stop_loss,
         signal.target_1, signal.target_2, signal.rationale, json.dumps(signal.news_urls), key))
        inserted = cursor.rowcount == 1
    else:
        from datetime import datetime, timezone
        db.execute("INSERT INTO runs (created_at,instrument,symbol,status) VALUES (?,?,?,?)",
                   (datetime.now(timezone.utc).isoformat(), instrument, symbol, status))
        inserted = False
    db.commit()
    db.close()
    return inserted
