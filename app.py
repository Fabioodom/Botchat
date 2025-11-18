# streamlit_app.py
import os, pickle, json
from datetime import datetime
import streamlit as st
from dotenv import load_dotenv, find_dotenv

# Backend (tus módulos)
from backend.db import init_db, get_user_by_email, upsert_user_token
from backend.services import add_appointment, list_appointments, delete_appointment
from backend.google_calendar import create_event
from models.appointment import Appointment
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

# Scopes para Gmail y Google Calendar + perfil
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
# helpers de token
# -----------------------
def get_token_path(email: str) -> str:
    safe = email.replace("@", "_at_").replace(".", "_")
    return os.path.join("tokens", f"{safe}.pkl")


def save_creds(email: str, creds) -> str:
    """Guarda las credenciales en disco y devuelve la ruta."""
    token_path = get_token_path(email)
    with open(token_path, "wb") as f:
        pickle.dump(creds, f)
    return token_path


def load_creds(email: str):
    path = get_token_path(email)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return pickle.load(f)


# -----------------------
# SIDEBAR: Configuración y Login
# -----------------------
with st.sidebar:
    st.header("⚙️ Configuración")

    # --- Autenticación con Google ---
    st.subheader("🔑 Autenticación con Google")

    # Si ya hay usuario guardado en sesión, intentamos precargar
    if "user_email" in st.session_state and "creds" not in st.session_state:
        user = get_user_by_email(st.session_state.user_email)
        if user and user.get("token_path"):
            try:
                with open(user["token_path"], "rb") as f:
                    st.session_state.creds = pickle.load(f)
                    st.session_state.token_path = user["token_path"]
            except:
                pass

    # Inputs para email y nombre
    default_owner_email = os.getenv("OWNER_EMAIL", "")
    default_owner_name = os.getenv("OWNER_NAME", "Dueño de la agenda")

    user_email = st.text_input("Tu email (dueño de la agenda)", value=st.session_state.get("user_email", default_owner_email))
    user_name = st.text_input("Tu nombre", value=st.session_state.get("user_name", default_owner_name))

    if user_email:
        st.session_state.user_email = user_email
        st.session_state.user_name = user_name

    # Botón login
    if "creds" not in st.session_state:
        if st.button("Iniciar sesión con Google"):
            if not user_email:
                st.error("Por favor, introduce tu email antes de iniciar sesión.")
            else:
                try:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json"),
                        SCOPES
                    )
                    creds = flow.run_local_server(port=0)
                    st.session_state.creds = creds
                    token_path = save_creds(user_email, creds)
                    st.session_state.token_path = token_path

                    # Guardar/actualizar usuario en DB
                    upsert_user_token(
                        usuario_id=user_email,
                        nombre=user_name,
                        email=user_email,
                        token_path=token_path
                    )

                    st.success("Autenticación correcta. Token guardado.")
                except Exception as e:
                    st.error(f"Error al autenticar con Google: {e}")
    else:
        st.info("Introduce tu email para poder iniciar sesión con Google.")

    # Mostrar info de sesión
    if "creds" in st.session_state:
        st.success(f"Sesión iniciada como: {st.session_state.user_email}")
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
        api_key = st.text_input("GROQ_API_KEY", value=os.getenv("GROQ_API_KEY", ""), type="password")

    st.caption("⚠️ De momento el bot está en modo entrevista rule-based. El LLM se integrará después.")

    # --- Opciones de guardado ---
    st.subheader("💾 Opciones de guardado")
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
# ESTADO DE LA SESIÓN
# -----------------------
if "history" not in st.session_state:
    st.session_state.history = []

if "state" not in st.session_state:
    st.session_state.state = initial_state()

if "saved_last_id" not in st.session_state:
    st.session_state.saved_last_id = None

# -----------------------
# LAYOUT PRINCIPAL
# -----------------------
left, right = st.columns((7, 5), gap="large")

with left:
    # 0) Primera pregunta del bot (solo se añade al history)
    if not st.session_state.history:
        first_q = prompt_for(st.session_state.state)
        st.session_state.history.append({"role": "assistant", "content": first_q})

    # 1) PINTAR HISTÓRICO DE CHAT (de más antiguo a más nuevo)
    for m in st.session_state.history:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    # 2) Entrada del usuario
    user_msg = st.chat_input("Escribe tu respuesta…")

    # 3) LÓGICA: si el user ha escrito algo
    if user_msg:
        # 3.a) Añadimos mensaje del usuario al histórico
        st.session_state.history.append({"role": "user", "content": user_msg})

        # 3.b) Actualizamos estado con la respuesta
        new_state = parse_and_update(st.session_state.state, user_msg)
        st.session_state.state = new_state

        # 3.c) ¿Está ya completo?
        if is_complete(new_state):
            data = final_json(new_state)
            resumen = (
                f"Perfecto, he registrado estos datos:\n"
                f"- Nombre: {data['nombre']}\n"
                f"- Email: {data['email']}\n"
                f"- Servicio: {data['servicio']}\n"
                f"- Fecha: {data['fecha_texto']} (ISO: {data['fecha_iso']})\n"
                f"- Hora: {data['hora_texto']} (ISO: {data['hora_iso']})\n"
                f"- Observaciones: {data.get('observaciones') or 'Ninguna'}\n"
            )
            st.session_state.history.append({"role": "assistant", "content": resumen})

            # Crear objeto Appointment
            ap = Appointment(
                nombre=data["nombre"],
                email=data["email"],
                servicio=data["servicio"],
                fecha_texto=data["fecha_texto"],
                fecha_iso=data["fecha_iso"],
                hora_texto=data["hora_texto"],
                hora_iso=data["hora_iso"],
                observaciones=data.get("observaciones"),
                confianza=data.get("confianza", 1.0),
                created_at=datetime.utcnow().isoformat()
            )

            # Guardar en SQLite
            if autosave:
                try:
                    new_id = add_appointment(ap)
                    st.session_state.saved_last_id = new_id
                    st.success(f"✅ Cita guardada en SQLite con ID {new_id}.")
                except Exception as e:
                    st.error(f"Error al guardar cita en DB: {e}")

            # Crear evento en Google Calendar
            if add_to_calendar:
                if "creds" in st.session_state:
                    try:
                        # Construir objeto service de Calendar con las creds en sesión
                        service = build("calendar", "v3", credentials=st.session_state.creds)

                        from datetime import timedelta
                        dt_str = f"{ap.fecha_iso} {ap.hora_iso}"
                        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
                        end_dt = dt + timedelta(hours=1)

                        tz = os.getenv("TZ", "Europe/Madrid")
                        start = dt.isoformat()
                        end = end_dt.isoformat()

                        event_body = {
                            "summary": f"Cita: {ap.servicio} - {ap.nombre}",
                            "description": ap.observaciones or "",
                            "start": {"dateTime": start, "timeZone": tz},
                            "end": {"dateTime": end, "timeZone": tz},
                        }
                        if invite_user and ap.email:
                            event_body["attendees"] = [{"email": ap.email}]

                        cal_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")
                        event = service.events().insert(
                            calendarId=cal_id,
                            body=event_body,
                            sendUpdates="all"
                        ).execute()

                        st.success(f"📅 Evento creado en Google Calendar: {event.get('htmlLink','(sin link)')}")
                    except Exception as e:
                        st.error(f"Error al crear evento en Google Calendar: {e}")
                else:
                    st.warning("Para crear eventos en Calendar debes iniciar sesión con Google en el sidebar.")

            # Reset de estado para una nueva cita
            st.session_state.state = initial_state()
            nxt_q = prompt_for(st.session_state.state)
            st.session_state.history.append({"role": "assistant", "content": nxt_q})

        else:
            # Aún faltan datos, siguiente pregunta
            nxt_q = prompt_for(new_state)
            st.session_state.history.append({"role": "assistant", "content": nxt_q})

        # 3.d) Forzamos un rerun para que lo recién agregado se vea ya encima del input
        st.rerun()

    # 4) Panel de progreso (queda sobre el input, pero no molesta)
    with st.expander("📊 Progreso de la cita", expanded=False):
        st.write("Estado interno:", st.session_state.state)


with right:
    st.subheader("📋 Citas guardadas")

    # Buscar citas
    q = st.text_input("Buscar por tipo/descripcion", key="search_q")
    try:
        rows = list_appointments(q=q or None, limit=50)
        if rows:
            for r in rows:
                rid = r["id_cita"]
                st.markdown(
                    f"**ID {rid}** | {r['fecha']} {r['hora']}  \n"
                    f"**Tipo:** {r['tipo']}  \n"
                    f"**Descripción:** {r['descripcion']}"
                )
                if st.button(f"🗑️ Borrar {rid}", key=f"del_{rid}"):
                    delete_appointment(rid)
                    st.rerun()
        else:
            st.info("No hay citas que coincidan con la búsqueda.")
    except Exception as e:
        st.error(f"Error al listar citas: {e}")

    # =========================
    # Calendario de Google embebido
    # =========================
    st.markdown("---")
    st.subheader("📆 Vista rápida de tu Google Calendar")

    if "creds" in st.session_state:
        try:
            calendar_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")
            calendar_url = f"https://calendar.google.com/calendar/embed?src={calendar_id}&ctz=Europe%2FMadrid"
            st.components.v1.html(
                f"""
                <iframe src="{calendar_url}" 
                        style="border:0; width:100%; height:600px;" 
                        frameborder="0" 
                        scrolling="no">
                </iframe>
                """,
                height=600
            )
        except Exception as e:
            st.warning(f"⚠️ No se pudo mostrar el calendario: {e}")
    else:
        st.info("Inicia sesión con Google para ver tu calendario personal.")
