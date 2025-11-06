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
        fecha_registro TEXT,
        preferencias TEXT,
        token_path TEXT
    )
    ''')

    cur.execute('''
    CREATE TABLE IF NOT EXISTS citas (
        id_cita INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id TEXT,
        fecha TEXT,
        hora TEXT,
        tipo TEXT,
        descripcion TEXT,
        recordatorio TEXT,
        id_evento_google TEXT,
        creado_en TEXT
    )
    ''')

    cur.execute('''
    CREATE TABLE IF NOT EXISTS memoria_chat (
        id_memoria INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id TEXT,
        fecha TEXT,
        mensaje_usuario TEXT,
        respuesta_bot TEXT,
        contexto TEXT
    )
    ''')

    cur.execute('''
    CREATE TABLE IF NOT EXISTS documentos_pdf (
        id_doc INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id TEXT,
        titulo TEXT,
        fecha_subida TEXT,
        ruta_archivo TEXT,
        embedding_path TEXT,
        resumen TEXT
    )
    ''')

    con.commit()
    con.close()

# ---------- Helpers ----------
def execute_query(query: str, params: tuple = ()):
    con = get_connection()
    cur = con.cursor()
    cur.execute(query, params)
    con.commit()
    lastrowid = cur.lastrowid
    con.close()
    return lastrowid

def query_one(query: str, params: tuple = ()):
    con = get_connection()
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(query, params)
    row = cur.fetchone()
    con.close()
    if row:
        return dict(row)
    return None

def query_all(query: str, params: tuple = ()):
    con = get_connection()
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(query, params)
    rows = cur.fetchall()
    con.close()
    return [dict(r) for r in rows]

# Usuarios
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
