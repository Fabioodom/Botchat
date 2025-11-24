import sqlite3
from typing import Optional, List, Dict, Any
from .db import get_connection
from models.appointment import Appointment

def add_appointment(a: Appointment) -> int:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO citas (usuario_id, fecha, hora, tipo, descripcion, recordatorio, id_evento_google, creado_en)
        VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
    """, (
        a.email,            # <- AHORA usamos el EMAIL como usuario_id
        a.fecha_iso,
        a.hora_iso,
        a.servicio,
        a.observaciones,
        None,
        None
    ))
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def list_appointments(q: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    sql = "SELECT * FROM citas"
    params = []

    if q:
        sql += " WHERE tipo LIKE ? OR descripcion LIKE ? OR usuario_id LIKE ?"
        wildcard = f"%{q}%"
        params = [wildcard, wildcard, wildcard]

    sql += " ORDER BY fecha DESC, hora DESC LIMIT ?"
    params.append(limit)

    rows = cur.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_appointment(id_: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM citas WHERE id_cita=?", (id_,))
    conn.commit()
    conn.close()
