import sqlite3
from pathlib import Path
from config import DB_PATH

def connect():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)

def init_db():
    con = connect()
    cur = con.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS market_prices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT, market TEXT, date TEXT, product TEXT,
        price REAL, unit TEXT, weekly_change REAL, url TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS grants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT, title TEXT, published TEXT, deadline TEXT,
        status TEXT, url TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    con.commit()
    con.close()
