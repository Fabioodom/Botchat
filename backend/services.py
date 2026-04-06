# backend/services.py
import sqlite3
from typing import Optional, List, Dict, Any
from .db import get_connection, execute_query, query_all, query_one
from models.appointment import Appointment
#Lector pdf
from PyPDF2 import PdfReader
import os
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_community.embeddings import OllamaEmbeddings

DB_VECTOR_PATH = "./chroma_db_data"


def add_appointment(a: Appointment) -> int:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO citas (usuario_id, fecha, hora, tipo, descripcion, recordatorio, id_evento_google, creado_en)
        VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
    """, (
        a.email,            
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
        import re
        fecha_iso = None
        m1 = re.match(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", q.strip())
        m2 = re.match(r"(\d{4})-(\d{2})-(\d{2})", q.strip())

        if m1:
            d, m, y = m1.groups()
            fecha_iso = f"{y}-{m.zfill(2)}-{d.zfill(2)}"
        elif m2:
            y, m, d = m2.groups()
            fecha_iso = f"{y}-{m}-{d}"

        if fecha_iso:
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



def procesar_pdf_rag(pdf_bytes: bytes, filename: str) -> bool:
    """
    Guarda el PDF en la memoria vectorial usando Ollama.
    """
    temp_path = f"temp_{filename}"
    with open(temp_path, "wb") as f:
        f.write(pdf_bytes)
        
    try:
        loader = PyPDFLoader(temp_path)
        documentos = loader.load()
        
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        chunks = text_splitter.split_documents(documentos)
        
        embeddings = OllamaEmbeddings(model="llama3.2:1b")
        
        Chroma.from_documents(
            documents=chunks, 
            embedding=embeddings, 
            persist_directory=DB_VECTOR_PATH
        )
        return True
    except Exception as e:
        print(f"Error en RAG: {e}")
        return False
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)