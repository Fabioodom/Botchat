from typing import Optional, List, Dict, Any
from .db import get_connection
from models.appointment import Appointment

def add_appointment(a: Appointment) -> int:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""INSERT INTO appointments(nombre,email,servicio,fecha_iso,hora_iso,observaciones,confianza)
                   VALUES (?,?,?,?,?,?,?)""",
                (a.nombre,a.email,a.servicio,a.fecha_iso,a.hora_iso,a.observaciones,a.confianza))
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id

def list_appointments(q: Optional[str]=None, limit:int=50) -> List[Dict[str,Any]]:
    conn = get_connection(); cur = conn.cursor()
    sql = "SELECT * FROM appointments"
    params = []
    if q:
        sql += " WHERE nombre LIKE ? OR email LIKE ? OR servicio LIKE ?"
        wild = f"%{q}%"; params = [wild,wild,wild]
    sql += " ORDER BY fecha_iso DESC, hora_iso DESC LIMIT ?"
    params.append(limit)
    rows = cur.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_appointment(id_: int):
    conn = get_connection(); cur = conn.cursor()
    cur.execute("DELETE FROM appointments WHERE id=?", (id_,))
    conn.commit(); conn.close()
