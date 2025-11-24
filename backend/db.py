# backend/db.py
import sqlite3
from typing import Optional, Dict

DB_PATH = "botcitas.db"

def get_connection():
    return sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)

def init_db():
    con = get_connection()
    cur = con.cursor()

    cur.execute('''
    CREATE TABLE IF NOT EXISTS usuarios (
        usuario_id TEXT PRIMARY KEY,
        nombre TEXT,
        email TEXT,
        fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        token_path TEXT
    )
    ''')

    cur.execute('''
    CREATE TABLE IF NOT EXISTS citas (
        id_cita INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id TEXT,
        fecha DATE,
        hora TIME,
        tipo TEXT,
        descripcion TEXT,
        recordatorio INTEGER,
        id_evento_google TEXT,
        creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    cur.execute('''
    CREATE TABLE IF NOT EXISTS memoria_chat (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id TEXT,
        rol TEXT,
        contenido TEXT,
        creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    cur.execute('''
    CREATE TABLE IF NOT EXISTS documentos_pdf (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id TEXT,
        nombre_archivo TEXT,
        ruta_archivo TEXT,
        subido_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    con.commit()
    con.close()

def query_one(sql: str, params=()) -> Optional[Dict]:
    con = get_connection()
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(sql, params)
    row = cur.fetchone()
    con.close()
    return dict(row) if row else None

def query_all(sql: str, params=()):
    con = get_connection()
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    con.close()
    return [dict(r) for r in rows]

def execute_query(sql: str, params=()):
    con = get_connection()
    cur = con.cursor()
    cur.execute(sql, params)
    con.commit()
    con.close()

def get_user_by_email(email: str) -> Optional[Dict]:
    return query_one("SELECT * FROM usuarios WHERE email = ?", (email,))

def upsert_user_token(usuario_id: str, nombre: str, email: str, token_path: str):
    """
    Inserta o actualiza el usuario y deja token_path.
    """
    execute_query("""
        INSERT INTO usuarios (usuario_id, nombre, email, fecha_registro, token_path)
        VALUES (?, ?, ?, datetime('now'), ?)
        ON CONFLICT(usuario_id) DO UPDATE SET
            nombre = excluded.nombre,
            email = excluded.email,
            token_path = excluded.token_path
    """, (usuario_id, nombre, email, token_path))
