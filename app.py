# streamlit_app.py
import os, pickle
from datetime import datetime
from dateutil import parser as dtparse
import streamlit as st
from dotenv import load_dotenv, find_dotenv

# Backend (tus módulos)
from backend.db import init_db, get_user_by_email, upsert_user_token
from backend.services import add_appointment, list_appointments, delete_appointment
from backend.llm import chat_with_groq, chat_with_ollama, extract_json_block, build_llm_messages
from backend.google_calendar import create_event  # debe aceptar token_path (te expliqué antes)
from models.appointment import Appointment

# Google auth libs
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Load .env
load_dotenv(find_dotenv())

# Inicializar DB (crea tablas si no existen)
init_db()

# Scopes para Gmail y Google Calendar
SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid"
]

# Asegurar carpeta tokens (aquí guardamos token por usuario)
os.makedirs("tokens", exist_ok=True)

st.set_page_config(page_title="Bot de Citas (IA + Calendar)", page_icon="🗓️", layout="wide")
st.title("🤖 Bot de Citas con IA y Google Calendar")

# -----------------------
# Estado inicial
# -----------------------
if "history" not in st.session_state:
    st.session_state.history = []

# -----------------------
# Helpers para fechas/hora
# -----------------------
def normalize_date(txt):
    if not txt: return None
    try:
        return dtparse.parse(txt, dayfirst=True, fuzzy=True).date().isoformat()
    except:
        return None

def normalize_time(txt):
    if not txt: return None
    try:
        return dtparse.parse(txt, fuzzy=True).strftime("%H:%M")
    except:
        return None

# -----------------------
# SIDEBAR: Configuración y Login
# -----------------------
with st.sidebar:
    st.header("⚙️ Configuración")

    # --- Autenticación con Google ---
    st.subheader("🔑 Autenticación con Google")

    # Si ya hay usuario cargado, intentar recuperar token desde DB
    if "user_email" in st.session_state and "creds" not in st.session_state:
        user = get_user_by_email(st.session_state.user_email)
        if user and user.get("token_path") and os.path.exists(user["token_path"]):
            # Cargar token desde archivo
            with open(user["token_path"], "rb") as f:
                st.session_state.creds = pickle.load(f)
                st.session_state.token_path = user["token_path"]

    if "user_email" not in st.session_state:
        if st.button("Iniciar sesión con Google"):
            try:
                # Flujo OAuth
                flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
                creds = flow.run_local_server(port=0)

                oauth_service = build("oauth2", "v2", credentials=creds)
                user_info = oauth_service.userinfo().get().execute()
                user_email = user_info.get("email")
                user_name = user_info.get("name", "Usuario")

                # Guardar token en archivo por usuario
                token_path = f"tokens/{user_email.replace('@','_at_')}.pkl"
                with open(token_path, "wb") as f:
                    pickle.dump(creds, f)

                # Guardar en BBDD (upsert)
                upsert_user_token(user_email, user_name, user_email, token_path)

                # Guardar en sesión
                st.session_state.creds = creds
                st.session_state.user_email = user_email
                st.session_state.user_name = user_name
                st.session_state.token_path = token_path

                st.success(f"✅ Conectado como {user_name} ({user_email})")

            except Exception as e:
                st.error(f"Error al iniciar sesión con Google: {e}")
    else:
        st.info(f"👤 Usuario: {st.session_state.user_email}")
        if st.button("Cerrar sesión"):
            for key in ["creds", "user_email", "user_name", "token_path"]:
                st.session_state.pop(key, None)
            st.rerun()

    # --- Configuración LLM ---
    provider = st.radio("Proveedor LLM", ["Ollama (local)", "Groq (cloud)"], index=0)
    if provider.startswith("Ollama"):
        model_name = st.text_input("Modelo Ollama", value="llama3.2:1b")
        api_key = None
    else:
        model_name = st.text_input("Modelo Groq", value="llama-3.1-70b-versatile")
        api_key = st.text_input("GROQ_API_KEY", type="password", value=os.getenv("GROQ_API_KEY", ""))

    autosave = st.checkbox("Guardar citas en SQLite", value=True)
    add_to_calendar = st.checkbox("Crear evento en Google Calendar", value=True)
    invite_user = st.checkbox("Invitar al cliente por email", value=True)

    if st.button("🧹 Limpiar chat"):
        st.session_state.history = []

# -----------------------
# INTERFACE: columnas principales
# -----------------------
left, right = st.columns((7,5), gap="large")

with left:
    # Mostrar historial del chat
    for m in st.session_state.history:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    msg = st.chat_input("Escribe tu mensaje…")
    if msg:
        st.session_state.history.append({"role":"user","content":msg})
        with st.chat_message("user"):
            st.markdown(msg)

        llm_messages = build_llm_messages(st.session_state.history[-12:])
        with st.spinner("Pensando…"):
            try:
                if provider.startswith("Ollama"):
                    answer = chat_with_ollama(llm_messages, model_name)
                else:
                    answer = chat_with_groq(llm_messages, model_name, api_key)
            except Exception as e:
                answer = f"❌ Error al contactar con el modelo: {e}"

        with st.chat_message("assistant"):
            st.markdown(answer)
        st.session_state.history.append({"role":"assistant","content":answer})

        # Extraer bloque JSON interpretado por el LLM (tus helpers)
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

                        # Pasamos token_path del usuario para crear el evento en SU calendario
                        token_path = st.session_state.get("token_path")
                        created = create_event(
                            summary=summary,
                            date_iso=a.fecha_iso,
                            time_hhmm=a.hora_iso,
                            duration_minutes=60,
                            description=description,
                            attendees_emails=[a.email] if invite_user else None,
                            token_path=token_path
                        )

                        # Guardar id_evento_google si quieres (puedes hacerlo en add_appointment o aquí)
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
    # Calendario de Google (embebido, personal)
    st.markdown("---")
    st.header("📅 Tu calendario de Google")
    if "creds" in st.session_state and "user_email" in st.session_state:
        try:
            calendar_email = st.session_state.user_email
            calendar_url = f"https://calendar.google.com/calendar/embed?src={calendar_email}&ctz=Europe/Madrid"
            st.components.v1.html(
                f'''
                <iframe src="{calendar_url}" 
                        style="border:0; width:100%; height:600px;" 
                        frameborder="0" 
                        scrolling="no">
                </iframe>
                ''',
                height=600
            )
        except Exception as e:
            st.warning(f"⚠️ No se pudo mostrar el calendario: {e}")
    else:
        st.info("Inicia sesión con Google para ver tu calendario personal.")
