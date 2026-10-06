import sqlite3
from pathlib import Path
from config import DB_PATH

def connect():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    con=sqlite3.connect(DB_PATH); con.row_factory=sqlite3.Row; return con

def init_db():
    con=connect(); cur=con.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS market_prices (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, market TEXT, date TEXT, product TEXT, price REAL, unit TEXT, weekly_change REAL, url TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    cur.execute("CREATE TABLE IF NOT EXISTS grants (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, title TEXT, published TEXT, deadline TEXT, status TEXT, url TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    cur.execute("CREATE TABLE IF NOT EXISTS farm (id INTEGER PRIMARY KEY CHECK(id=1), name TEXT, owner TEXT, region TEXT, municipality TEXT, address TEXT, tax_code TEXT, notes TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    cur.execute("CREATE TABLE IF NOT EXISTS animals (id INTEGER PRIMARY KEY AUTOINCREMENT, tag TEXT UNIQUE, species TEXT DEFAULT 'ovino', breed TEXT, sex TEXT, birth_date TEXT, mother_tag TEXT, father_tag TEXT, photo_path TEXT, status TEXT DEFAULT 'present', purchase_date TEXT, purchase_price REAL, sale_date TEXT, sale_price REAL, death_date TEXT, death_reason TEXT, notes TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    cur.execute("CREATE TABLE IF NOT EXISTS animal_events (id INTEGER PRIMARY KEY AUTOINCREMENT, animal_id INTEGER, event_type TEXT NOT NULL, event_date TEXT NOT NULL, quantity REAL, value REAL, related_animal_id INTEGER, description TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS milk_production (id INTEGER PRIMARY KEY AUTOINCREMENT, production_date TEXT NOT NULL, animal_id INTEGER, liters REAL NOT NULL, milking_session TEXT, destination TEXT, price_per_liter REAL, notes TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS feed_consumption (id INTEGER PRIMARY KEY AUTOINCREMENT, consumption_date TEXT NOT NULL, animal_id INTEGER, group_name TEXT, feed_type TEXT NOT NULL, quantity_kg REAL NOT NULL, unit_cost REAL, total_cost REAL, notes TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS inventory (id INTEGER PRIMARY KEY AUTOINCREMENT, item_name TEXT NOT NULL, category TEXT NOT NULL, unit TEXT DEFAULT 'kg', quantity REAL DEFAULT 0, average_cost REAL DEFAULT 0, minimum_quantity REAL DEFAULT 0, supplier TEXT, notes TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS inventory_movements (id INTEGER PRIMARY KEY AUTOINCREMENT, movement_date TEXT NOT NULL, inventory_id INTEGER NOT NULL, movement_type TEXT NOT NULL, quantity REAL NOT NULL, unit_cost REAL, total_cost REAL, reference TEXT, notes TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS fields (id INTEGER PRIMARY KEY AUTOINCREMENT, field_name TEXT NOT NULL, parcel_code TEXT, hectares REAL DEFAULT 0, ownership TEXT, location TEXT, notes TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS field_crops (id INTEGER PRIMARY KEY AUTOINCREMENT, field_id INTEGER NOT NULL, season TEXT NOT NULL, crop TEXT NOT NULL, hectares REAL DEFAULT 0, sowing_date TEXT, harvest_date TEXT, production_kg REAL, seed_cost REAL DEFAULT 0, fertilizer_cost REAL DEFAULT 0, treatment_cost REAL DEFAULT 0, fuel_cost REAL DEFAULT 0, other_cost REAL DEFAULT 0, revenue REAL DEFAULT 0)")
    cur.execute("CREATE TABLE IF NOT EXISTS hay_production (id INTEGER PRIMARY KEY AUTOINCREMENT, production_date TEXT NOT NULL, field_id INTEGER, crop TEXT, quantity_kg REAL NOT NULL, unit_cost REAL, total_cost REAL, storage_location TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS fuel_consumption (id INTEGER PRIMARY KEY AUTOINCREMENT, consumption_date TEXT NOT NULL, fuel_type TEXT DEFAULT 'diesel', liters REAL NOT NULL, price_per_liter REAL, total_cost REAL, machine TEXT, hours REAL, field_id INTEGER, operation TEXT, notes TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS financial_transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, transaction_date TEXT NOT NULL, transaction_type TEXT NOT NULL, category TEXT NOT NULL, description TEXT, amount REAL NOT NULL, quantity REAL, unit TEXT, animal_id INTEGER, field_id INTEGER, inventory_id INTEGER, counterparty TEXT, document_number TEXT, payment_method TEXT, notes TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS daily_metrics (id INTEGER PRIMARY KEY AUTOINCREMENT, metric_date TEXT NOT NULL, metric TEXT NOT NULL, value REAL NOT NULL, unit TEXT, notes TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    for sql in ["CREATE INDEX IF NOT EXISTS idx_animals_status ON animals(status)","CREATE INDEX IF NOT EXISTS idx_milk_date ON milk_production(production_date)","CREATE INDEX IF NOT EXISTS idx_feed_date ON feed_consumption(consumption_date)","CREATE INDEX IF NOT EXISTS idx_fuel_date ON fuel_consumption(consumption_date)","CREATE INDEX IF NOT EXISTS idx_financial_date ON financial_transactions(transaction_date)"]:
        cur.execute(sql)
    con.commit(); con.close()


def execute(sql, params=()):
    con=connect(); cur=con.cursor(); cur.execute(sql, params); con.commit(); last=cur.lastrowid; con.close(); return last

def today():
    from datetime import date
    return date.today().isoformat()
