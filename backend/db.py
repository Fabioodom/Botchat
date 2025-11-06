import os, sqlite3
from pathlib import Path

DB_PATH = os.getenv("DB_PATH", "botcitas.db")

def get_connection():
    p = Path(DB_PATH)
    if p.parent and not p.parent.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS appointments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        email TEXT NOT NULL,
        servicio TEXT NOT NULL,
        fecha_iso TEXT NOT NULL,
        hora_iso TEXT NOT NULL,
        observaciones TEXT,
        confianza REAL,
        created_at TEXT DEFAULT (datetime('now'))
    )
    """)
    conn.commit()
    conn.close()
