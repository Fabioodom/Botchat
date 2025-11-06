import os, json
from datetime import datetime
from dateutil import parser as dtparse
import streamlit as st
from dotenv import load_dotenv, find_dotenv

# Backend
from backend.db import init_db
from backend.services import add_appointment, list_appointments, delete_appointment
from backend.llm import chat_with_groq, chat_with_ollama, extract_json_block, build_llm_messages
from backend.google_calendar import create_event
from models.appointment import Appointment

#Gmail y Google Calendar
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Cargar variables .env
load_dotenv(find_dotenv())

# Inicializar DB
init_db()

# Scopes para Gmail y Google Calendar
SCOPES = [
    'https://www.googleapis.com/auth/calendar.events',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
    'openid'
]

def gmail_login():
    if "creds" in st.session_state and st.session_state.creds:
        return st.session_state.creds
    creds = None
    # Revisar si ya hay token guardado
    if os.path.exists("token.pkl"):
        with open("token.pkl", "rb") as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
        creds = flow.run_local_server(port=0)
        with open("token.pkl", "wb") as f:
            pickle.dump(creds, f)
    st.session_state.creds = creds
    return creds

st.set_page_config(page_title="Bot de Citas (IA + Calendar)", page_icon="🗓️", layout="wide")

# === SIDEBAR ===
with st.sidebar:
    st.header("⚙️ Configuración")

    # --- Login con Google ---
    st.subheader("🔑 Autenticación")
    if "user_email" not in st.session_state:
        if st.button("Iniciar sesión con Google"):
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
            import pickle

            SCOPES = [
                'https://www.googleapis.com/auth/calendar.events',
                'https://www.googleapis.com/auth/userinfo.email',
                'https://www.googleapis.com/auth/userinfo.profile',
                'openid'
            ]

            creds = None
            # Revisar si ya hay token guardado
            if os.path.exists("token.pkl"):
                with open("token.pkl", "rb") as f:
                    creds = pickle.load(f)
            if not creds or not creds.valid:
                flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
                creds = flow.run_local_server(port=0)
                with open("token.pkl", "wb") as f:
                    pickle.dump(creds, f)

            st.session_state.creds = creds
            # Obtener email del usuario
            service = build("oauth2", "v2", credentials=creds)
            user_info = service.userinfo().get().execute()
            st.session_state.user_email = user_info.get("email")
            st.success(f"Conectado como {st.session_state.user_email}")
    else:
        st.info(f"Usuario: {st.session_state.user_email}")

    # --- Configuración LLM ---
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
    # =========================
    # Citas guardadas
    st.header("🗓️ Citas guardadas")
    q = st.text_input("Buscar (nombre / servicio)")
    rows = list_appointments(q=q)
    if not rows: 
        st.info("Sin resultados.")
    for r in rows:
        st.markdown("---")
        st.markdown(f"**{r['id']}** · {r['servicio']} · {r['fecha_iso']} {r['hora_iso']}")
        st.caption(f"{r['nombre']} — {r['email']}")
        if st.button("🗑️ Eliminar", key=f"del-{r['id']}"):
            delete_appointment(r['id'])
            st.experimental_rerun()

    # =========================
    # Calendario de Google
    st.markdown("---")
    st.header("📅 Calendario de Google")
    if "creds" in st.session_state:
        from googleapiclient.discovery import build

        try:
            service = build("calendar", "v3", credentials=st.session_state.creds)
            calendar_id = "primary"
            events_result = service.events().list(
                calendarId=calendar_id,
                maxResults=10,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            events = events_result.get('items', [])

            if events:
                for event in events:
                    start = event['start'].get('dateTime', event['start'].get('date'))
                    st.markdown(f"- **{event['summary']}** · {start}")
            else:
                st.info("No hay eventos próximos en tu Google Calendar.")
        except Exception as e:
            st.warning(f"⚠️ Error al cargar el calendario: {e}")
    else:
        st.info("Inicia sesión con Google para ver tu calendario.")
