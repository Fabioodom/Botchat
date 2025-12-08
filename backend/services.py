# backend/services.py
import sqlite3
from typing import Optional, List, Dict, Any
from .db import get_connection, execute_query, query_all, query_one
from models.appointment import Appointment
#Lector pdf
from PyPDF2 import PdfReader




def add_appointment(a: Appointment) -> int:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO citas (usuario_id, fecha, hora, tipo, descripcion, recordatorio, id_evento_google, creado_en)
        VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
    """, (
        a.email,            # usamos el EMAIL como usuario_id
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

def set_event_id_for_appointment(id_cita: int, event_id: str):
    execute_query("UPDATE citas SET id_evento_google = ? WHERE id_cita = ?", (event_id, id_cita))

def list_appointments(q: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    sql = "SELECT * FROM citas"
    params = []

    if q:
        # Intentar detectar si q es una fecha tipo dd/mm/yyyy o yyyy-mm-dd
        import re
        fecha_iso = None

        # Caso dd/mm/yyyy o dd-mm-yyyy
        m1 = re.match(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", q.strip())
        # Caso yyyy-mm-dd
        m2 = re.match(r"(\d{4})-(\d{2})-(\d{2})", q.strip())

        if m1:
            d, m, y = m1.groups()
            fecha_iso = f"{y}-{m.zfill(2)}-{d.zfill(2)}"
        elif m2:
            y, m, d = m2.groups()
            fecha_iso = f"{y}-{m}-{d}"

        if fecha_iso:
            # Buscar también por fecha
            sql += " WHERE (tipo LIKE ? OR descripcion LIKE ? OR usuario_id LIKE ? OR fecha = ?)"
            wildcard = f"%{q}%"
            params = [wildcard, wildcard, wildcard, fecha_iso]
        else:
            sql += " WHERE tipo LIKE ? OR descripcion LIKE ? OR usuario_id LIKE ?"
            wildcard = f"%{q}%"
            params = [wildcard, wildcard, wildcard]

    sql += " ORDER BY fecha DESC, hora DESC LIMIT ?"
    params.append(limit)

    rows = cur.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def find_appointment_by_id(id_cita: int):
    return query_one("SELECT * FROM citas WHERE id_cita = ?", (id_cita,))

def find_appointment(usuario_email: str = None, fecha: str = None, tipo: str = None):
    """
    Devuelve la primera coincidencia
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    sql = "SELECT * FROM citas WHERE 1=1"
    params = []
    if usuario_email:
        sql += " AND usuario_id = ?"
        params.append(usuario_email)
    if fecha:
        sql += " AND fecha = ?"
        params.append(fecha)
    if tipo:
        sql += " AND tipo = ?"
        params.append(tipo)

    sql += " LIMIT 1"
    row = cur.execute(sql, params).fetchone()
    conn.close()
    return dict(row) if row else None

def delete_appointment(id_: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM citas WHERE id_cita=?", (id_,))
    conn.commit()
    conn.close()


def update_appointment(usuario_id: str, id_cita: int, nueva_fecha: str, nueva_hora: str):
    execute_query("""
        UPDATE citas
        SET fecha = ?, hora = ?
        WHERE usuario_id = ? AND id_cita = ?
    """, (nueva_fecha, nueva_hora, usuario_id, id_cita))

def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """
    Recibe el contenido de un PDF en bytes y devuelve el texto extraído.
    Esta función NO depende de Streamlit.
    """
    import io

    pdf_file = io.BytesIO(pdf_bytes)
    reader = PdfReader(pdf_file)

    text_parts = []
    for page in reader.pages:
        page_text = page.extract_text() or ""
        text_parts.append(page_text)

    return "\n".join(text_parts)
