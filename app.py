# streamlit_app.py
import os, pickle, json
from datetime import datetime
from dateutil import parser as dtparse
import streamlit as st
from dotenv import load_dotenv, find_dotenv

# Backend (tus módulos)
from backend.db import init_db, get_user_by_email, upsert_user_token
from backend.services import add_appointment, list_appointments, delete_appointment
from backend.google_calendar import create_event  # debe aceptar token_path (te expliqué antes)
from models.appointment import Appointment
from backend.google_calendar import create_event
from backend.agent_rulebased import (
    initial_state, prompt_for, parse_and_update, is_complete, final_json
)

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
if "state" not in st.session_state:
    st.session_state.state = initial_state()
if "saved_last_id" not in st.session_state:
    st.session_state.saved_last_id = None

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
        st.session_state.state = initial_state()
        st.session_state.saved_last_id = None
        st.rerun()


st.title("🗓️ Bot de Citas · Modo Entrevista (sin IA)")

# -----------------------
# INTERFACE: columnas principales
# -----------------------
left, right = st.columns((7,5), gap="large")

with left:
    # 0) Primera pregunta si no hay historial (solo se añade al history)
    if not st.session_state.history:
        first_q = prompt_for(st.session_state.state["expected"])
        st.session_state.history.append({"role": "assistant", "content": first_q})

    # 1) RENDER: mostrar el historial (de más antiguo a más nuevo)
    for m in st.session_state.history:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    # (Opcional) auto scroll al fondo tras render
    import streamlit.components.v1 as components
    components.html(
        "<script>window.parent.scrollTo(0, document.body.scrollHeight);</script>",
        height=0,
    )

    # 2) INPUT AL FINAL (queda visualmente abajo del todo)
    user_msg = st.chat_input("Escribe tu respuesta…")

    # 3) LÓGICA: si hay respuesta del usuario, actualizamos y re-pintamos
    if user_msg:
        # 3.a) Guardar turno user
        st.session_state.history.append({"role": "user", "content": user_msg})

        # 3.b) Actualizar estado
        st.session_state.state = parse_and_update(st.session_state.state, user_msg)

        # 3.c) Generar turno assistant: JSON final o siguiente pregunta
        if is_complete(st.session_state.state):
            data  = final_json(st.session_state.state)
            block = "```json\n" + json.dumps(data, ensure_ascii=False, indent=2) + "\n```"
            msg   = "¡Perfecto! Estos son tus datos de la cita. ¿Está todo correcto?\n\n" + block
            st.session_state.history.append({"role": "assistant", "content": msg})

            # Guardar y Calendar solo una vez
            if autosave and st.session_state.saved_last_id is None:
                appt = Appointment(
                    nombre=data["nombre"],
                    email=data["email"],
                    servicio=data["servicio"],
                    fecha_texto=data["fecha_texto"],
                    fecha_iso=data["fecha_iso"],
                    hora_texto=data["hora_texto"],
                    hora_iso=data["hora_iso"],
                    observaciones=data["observaciones"],
                    confianza=data["confianza"],
                )
                new_id = add_appointment(appt)
                st.session_state.saved_last_id = new_id
                st.success(f"✅ Cita guardada (id={new_id})")

                if add_to_calendar:
                    try:
                        summary = f"{appt.servicio} — {appt.nombre}"
                        description = f"Email: {appt.email}\nNotas: {appt.observaciones or ''}"
                        created = create_event(
                            summary=summary,
                            date_iso=appt.fecha_iso,
                            time_hhmm=appt.hora_iso,
                            duration_minutes=60,
                            description=description,
                            attendees_emails=[appt.email] if invite_user else None
                        )
                        link = created.get("htmlLink") if isinstance(created, dict) else None
                        if link:
                            st.success(f"📅 Añadida a Google Calendar: [Abrir]({link})")
                        else:
                            st.info("Evento creado en Calendar.")
                    except Exception as e:
                        st.warning(f"⚠️ No se pudo crear el evento: {e}")
        else:
            nxt_q = prompt_for(st.session_state.state["expected"])
            st.session_state.history.append({"role": "assistant", "content": nxt_q})

        # 3.d) Forzamos un rerun para que lo recién agregado se vea ya encima del input
        st.rerun()

    # 4) Panel de progreso (queda sobre el input, pero al final de la columna)
    st.subheader("📋 Progreso")
    s = st.session_state.state
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Nombre:** {s.get('nombre') or '—'}")
        st.markdown(f"**Email:** {s.get('email') or '—'}")
        st.markdown(f"**Servicio:** {s.get('servicio') or '—'}")
        st.markdown(f"**Observaciones:** {s.get('observaciones') or '—'}")
    with col2:
        st.markdown(f"**Fecha (ISO):** {s.get('fecha_iso') or s.get('fecha_texto') or '—'}")
        st.markdown(f"**Hora (ISO):** {s.get('hora_iso') or s.get('hora_texto') or '—'}")
        st.markdown(f"**Confianza:** {s.get('confianza')}")


with right:
    # =========================
    # =========================
    # Citas guardadas
    # =========================
    st.header("🗓️ Citas guardadas")
    q = st.text_input("Buscar (tipo / descripción)")
    rows = list_appointments(q=q)

    if not rows:
        st.info("Sin resultados.")
    else:
        for r in rows:
            # Extraer campos con nombres reales de la tabla `citas`
            rid = r.get("id_cita")
            tipo = r.get("tipo", "—")
            fecha = r.get("fecha", "—")
            hora = r.get("hora", "—")
            descripcion = r.get("descripcion", "")
            usuario_id = r.get("usuario_id", "—")

            st.markdown("---")
            st.markdown(f"**{rid}** · {tipo} · {fecha} {hora}")
            st.caption(f"Usuario: {usuario_id}")
            if descripcion:
                st.text(f"📝 {descripcion}")

            if st.button("🗑️ Eliminar", key=f"del-{rid}"):
                delete_appointment(rid)
                st.rerun()

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
