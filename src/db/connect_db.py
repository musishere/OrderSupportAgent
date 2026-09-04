import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "order_support.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    customer_id TEXT PRIMARY KEY,
    name TEXT,
    email TEXT,
    default_shipping_address TEXT,
    account_created_at TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    customer_id TEXT,
    status TEXT,
    shipping_address TEXT,
    amount REAL,
    created_at TEXT,
    shipped_at TEXT,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);

CREATE TABLE IF NOT EXISTS address_change_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT,
    old_address TEXT,
    new_address TEXT,
    changed_at TEXT,
    approved_by TEXT
);
"""


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


if __name__ == "__main__":
    conn = get_connection()
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"customers", "orders", "address_change_log"} <= tables
    print(f"OK: db initialized at {DB_PATH} with tables {sorted(tables)}")
    conn.close()
