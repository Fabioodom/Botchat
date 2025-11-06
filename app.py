import os, json
from datetime import datetime
from dateutil import parser as dtparse
import streamlit as st
from dotenv import load_dotenv, find_dotenv

# Cargar variables .env
load_dotenv(find_dotenv())

# Backend
from backend.db import init_db
from backend.services import add_appointment, list_appointments, delete_appointment
from backend.llm import chat_with_groq, chat_with_ollama, extract_json_block, build_llm_messages
from backend.google_calendar import create_event
from models.appointment import Appointment

# Inicializar DB
init_db()

st.set_page_config(page_title="Bot de Citas (IA + Calendar)", page_icon="🗓️", layout="wide")

# === SIDEBAR ===
with st.sidebar:
    st.header("⚙️ Configuración")
    provider = st.radio("Proveedor LLM", ["Ollama (local)", "Groq (cloud)"], index=0)
    if provider.startswith("Ollama"):
        model_name = st.text_input("Modelo Ollama", value="llama3.2:1b")
        api_key = None
    else:
        model_name = st.text_input("Modelo Groq", value="llama-3.1-70b-versatile")
        api_key = st.text_input("GROQ_API_KEY", type="password", value=os.getenv("GROQ_API_KEY", ""))
    autosave = st.toggle("Guardar citas en SQLite", value=True)
    add_to_calendar = st.toggle("Crear evento en Google Calendar", value=True)
    invite_user = st.toggle("Invitar al cliente por email", value=True)
    if st.button("🧹 Limpiar chat"):
        st.session_state.history = []

st.title("🤖 Bot de Citas con IA y Google Calendar")

if "history" not in st.session_state:
    st.session_state.history = []

# === FUNCIONES AUXILIARES ===
def normalize_date(txt):
    if not txt: return None
    try:
        return dtparse.parse(txt, dayfirst=True, fuzzy=True).date().isoformat()
    except: return None

def normalize_time(txt):
    if not txt: return None
    try:
        return dtparse.parse(txt, fuzzy=True).strftime("%H:%M")
    except: return None

# === UI PRINCIPAL ===
left, right = st.columns((7,5), gap="large")

with left:
    for m in st.session_state.history:
        with st.chat_message(m["role"]): st.markdown(m["content"])

    msg = st.chat_input("Escribe tu mensaje…")
    if msg:
        st.session_state.history.append({"role":"user","content":msg})
        with st.chat_message("user"): st.markdown(msg)

        llm_messages = build_llm_messages(st.session_state.history[-12:])
        with st.spinner("Pensando…"):
            try:
                if provider.startswith("Ollama"):
                    answer = chat_with_ollama(llm_messages, model_name)
                else:
                    answer = chat_with_groq(llm_messages, model_name, api_key)
            except Exception as e:
                answer = f"❌ Error al contactar con el modelo: {e}"

        with st.chat_message("assistant"): st.markdown(answer)
        st.session_state.history.append({"role":"assistant","content":answer})

        data = extract_json_block(answer)
        if data:
            fecha_iso = data.get("fecha_iso") or normalize_date(data.get("fecha_texto"))
            hora_iso  = data.get("hora_iso")  or normalize_time(data.get("hora_texto"))

            st.subheader("📋 Datos interpretados")
            col1,col2 = st.columns(2)
            with col1:
                st.markdown(f"**Nombre:** {data.get('nombre','—')}")
                st.markdown(f"**Email:** {data.get('email','—')}")
                st.markdown(f"**Servicio:** {data.get('servicio','—')}")
                st.markdown(f"**Observaciones:** {data.get('observaciones','—')}")
            with col2:
                st.markdown(f"**Fecha:** {fecha_iso or data.get('fecha_texto','—')}")
                st.markdown(f"**Hora:** {hora_iso or data.get('hora_texto','—')}")
                st.markdown(f"**Confianza:** {data.get('confianza','—')}")

            ok = all([data.get("nombre"),data.get("email"),data.get("servicio"),fecha_iso,hora_iso])
            if ok and autosave:
                a = Appointment(None,data["nombre"],data["email"],data["servicio"],fecha_iso,hora_iso,
                                data.get("observaciones") or "",data.get("confianza"))
                new_id = add_appointment(a)
                st.success(f"✅ Cita guardada (id={new_id})")

                if add_to_calendar:
                    try:
                        summary = f"{a.servicio} — {a.nombre}"
                        description = f"Email: {a.email}\nNotas: {a.observaciones}"
                        created = create_event(
                            summary=summary,
                            date_iso=a.fecha_iso,
                            time_hhmm=a.hora_iso,
                            duration_minutes=60,
                            description=description,
                            attendees_emails=[a.email] if invite_user else None
                        )
                        st.success(f"📅 Añadida a Google Calendar: [Abrir]({created.get('htmlLink')})")
                    except Exception as e:
                        st.warning(f"⚠️ No se pudo crear el evento: {e}")
            else:
                st.info("Faltan datos clave, el asistente te los pedirá.")

with right:
    st.header("🗓️ Citas guardadas")
    q = st.text_input("Buscar (nombre / servicio)")
    rows = list_appointments(q=q)
    if not rows: st.info("Sin resultados.")
    for r in rows:
        st.markdown("---")
        st.markdown(f"**{r['id']}** · {r['servicio']} · {r['fecha_iso']} {r['hora_iso']}")
        st.caption(f"{r['nombre']} — {r['email']}")
        if st.button("🗑️ Eliminar", key=f"del-{r['id']}"):
            delete_appointment(r['id'])
            st.experimental_rerun()
