# streamlit_app.py
import os
import pickle
import json
from datetime import datetime
from dateutil import parser as dtparse
import streamlit as st
from dotenv import load_dotenv, find_dotenv
import subprocess

# Backend
from backend.db import init_db, get_user_by_email, upsert_user_token
from backend.services import add_appointment, list_appointments, delete_appointment
from backend.google_calendar import create_event
from models.appointment import Appointment
from backend.chat_manager import ChatManagerDB
from backend.agent_rulebased import extract_json_block  # <-- solo necesitamos esto

# Google Auth
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


# ============================
# INICIALIZACIÓN
# ============================
load_dotenv(find_dotenv())
init_db()

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid",
]

os.makedirs("tokens", exist_ok=True)

# Streamlit setup
st.set_page_config(page_title="Bot de Citas (IA + Calendar)", page_icon="🗓️", layout="wide")
st.title("🤖 Bot de Citas con IA y Google Calendar")


# Estado global
if "chat_manager" not in st.session_state:
    st.session_state.chat_manager = None
if "usuario_id" not in st.session_state:
    st.session_state.usuario_id = None


# ============================
# SIDEBAR
# ============================
with st.sidebar:
    st.header("⚙️ Configuración")

    # ------------------- LLM -----------------------
    st.subheader("🧠 Proveedor LLM")
    provider = st.radio("Proveedor LLM", ["Ollama (local)", "Groq (cloud)"], index=0)

    model_name = None
    api_key = None

    if provider.startswith("Ollama"):
        try:
            result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
            lines = result.stdout.strip().split("\n")[1:]  # saltar cabecera
            modelos_locales = [line.split()[0] for line in lines if line.strip()]

            if not modelos_locales:
                modelos_locales = ["⚠️ No hay modelos instalados"]

            model_name = st.selectbox("Modelos Ollama instalados", modelos_locales, index=0)

            st.caption("💡 Usa 'ollama pull <modelo>' para descargar nuevos modelos.")
            if st.button("🔄 Refrescar modelos"):
                st.rerun()

        except Exception:
            st.warning("No se pudieron obtener los modelos de Ollama.")
            model_name = st.text_input("Modelo Ollama", value="llama3.2:1b")

    else:
        model_name = st.text_input("Modelo Groq", value="llama-3.1-70b-versatile")
        api_key = st.text_input("GROQ_API_KEY", type="password", value=os.getenv("GROQ_API_KEY", ""))

    autosave = st.checkbox("Guardar citas en SQLite", value=True)
    add_to_calendar = st.checkbox("Crear evento en Google Calendar", value=True)
    invite_user = st.checkbox("Invitar por email", value=True)

    # ------------------- LOGIN GOOGLE -----------------------
    st.subheader("🔑 Autenticación con Google")

    # Recuperar token
    if st.session_state.get("user_email") and "creds" not in st.session_state:
        user = get_user_by_email(st.session_state.user_email)
        if user and user.get("token_path") and os.path.exists(user["token_path"]):
            with open(user["token_path"], "rb") as f:
                st.session_state.creds = pickle.load(f)
                st.session_state.token_path = user["token_path"]

    if "user_email" not in st.session_state:
        if st.button("Iniciar sesión con Google"):
            try:
                flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
                creds = flow.run_local_server(port=0)

                oauth = build("oauth2", "v2", credentials=creds)
                user_info = oauth.userinfo().get().execute()

                email = user_info.get("email")
                nombre = user_info.get("name", "Usuario")

                usuario_id = email
                token_path = f"tokens/{email.replace('@', '_at_')}.pkl"

                with open(token_path, "wb") as f:
                    pickle.dump(creds, f)

                upsert_user_token(usuario_id, nombre, email, token_path)

                st.session_state.creds = creds
                st.session_state.user_email = email
                st.session_state.user_name = nombre
                st.session_state.token_path = token_path
                st.session_state.usuario_id = usuario_id

                os.environ["CURRENT_USER_EMAIL"] = email

                st.session_state.chat_manager = ChatManagerDB(
                    usuario_id=usuario_id,
                    provider=provider.split()[0].lower(),
                    model_name=model_name,
                    api_key=api_key,
                )

                st.success(f"✅ Conectado como {nombre} ({email})")

            except Exception as e:
                st.error(f"Error al iniciar sesión: {e}")

    else:
        st.info(f"👤 Usuario: {st.session_state.user_email}")
        if st.button("Cerrar sesión"):
            for key in ["creds","user_email","user_name","token_path","usuario_id","chat_manager"]:
                st.session_state.pop(key, None)
            st.rerun()

    # ------------------- RESET CHAT -----------------------
    if st.button("🧹 Limpiar chat") and st.session_state.chat_manager:
        st.session_state.chat_manager.reset_memory()
        st.rerun()



# ============================
# CREAR CHAT MANAGER SI FALTA
# ============================
if st.session_state.get("usuario_id") and not st.session_state.chat_manager:
    st.session_state.chat_manager = ChatManagerDB(
        usuario_id=st.session_state.usuario_id,
        provider=provider.split()[0].lower(),
        model_name=model_name,
        api_key=api_key,
    )


# ============================
# INTERFAZ PRINCIPAL
# ============================
left, right = st.columns((7,5))

with left:
    chat_manager = st.session_state.chat_manager

    # Mostrar historial del chat
    if chat_manager:
        for m in chat_manager.get_memory():
            role = "user" if m["role"] == "human" else "assistant"
            with st.chat_message(role):
                st.markdown(m["content"])

    # Entrada del usuario
    user_msg = st.chat_input("Escribe tu mensaje…")

    if user_msg and chat_manager:
        with st.chat_message("user"):
            st.markdown(user_msg)

        response = chat_manager.ask(user_msg)

        with st.chat_message("assistant"):
            st.markdown(response)

        # Extraer JSON final del modelo
        data = extract_json_block(response)

        if data:

            action = data.get("action", "create").lower()

            # --------------------------------------------------------
            # 1) CREAR CITA
            # --------------------------------------------------------
            if action == "create":

                nombre = data.get("nombre")
                email = data.get("email")
                servicio = data.get("servicio")
                fecha_iso = data.get("fecha_iso")
                hora_iso = data.get("hora_iso")
                observaciones = data.get("observaciones", "")

                if all([nombre, email, servicio, fecha_iso, hora_iso]):

                    appt = Appointment(
                        nombre=nombre,
                        email=email,
                        servicio=servicio,
                        fecha_texto=data.get("fecha_texto"),
                        fecha_iso=fecha_iso,
                        hora_texto=data.get("hora_texto"),
                        hora_iso=hora_iso,
                        observaciones=observaciones,
                        confianza=data.get("confianza", 1.0),
                    )

                    new_id = add_appointment(appt)
                    st.success(f"✅ Cita guardada (ID={new_id})")

                    # Añadir a Google Calendar
                    if add_to_calendar:
                        try:
                            summary = f"{servicio} — {nombre}"
                            desc = f"Email: {email}\nNotas: {observaciones}"

                            created = create_event(
                                summary=summary,
                                date_iso=fecha_iso,
                                time_hhmm=hora_iso,
                                duration_minutes=60,
                                description=desc,
                                attendees_emails=[email] if invite_user else None,
                            )

                            link = created.get("htmlLink") if isinstance(created, dict) else None
                            if link:
                                st.success(f"📅 Evento creado: [Abrir]({link})")
                        except Exception as e:
                            st.warning(f"⚠️ No se pudo crear evento: {e}")

            # --------------------------------------------------------
            # 2) CONSULTAR CITAS
            # --------------------------------------------------------
            elif action == "consult":

                filtro = data.get("filtro", "")
                st.info(f"🔍 Buscando citas relacionadas con: **{filtro}**")

                resultados = list_appointments(q=filtro)

                if not resultados:
                    st.warning("❌ No se encontraron citas relacionadas.")
                else:
                    st.success(f"📋 Encontradas {len(resultados)} cita(s):")
                    for r in resultados:
                        st.markdown(f"- **{r['tipo']}** → {r['fecha']} {r['hora']}")

            # --------------------------------------------------------
            # 3) CANCELAR CITA
            # --------------------------------------------------------
            elif action == "cancel":

                filtro = data.get("filtro", "")
                st.info(f"🗑️ Buscando para eliminar: **{filtro}**")

                resultados = list_appointments(q=filtro)

                if not resultados:
                    st.warning("❌ No encontré ninguna cita para cancelar.")
                else:
                    # Elegimos la primera coincidencia
                    cita = resultados[0]
                    delete_appointment(cita["id_cita"])
                    st.success(f"🗑️ Cita cancelada correctamente (ID={cita['id_cita']}).")

            # --------------------------------------------------------
            #  4) MODIFICAR CITA
            # --------------------------------------------------------
            elif action == "modify":

                filtro = data.get("filtro", "")
                nueva_fecha = data.get("nueva_fecha")
                nueva_hora = data.get("nueva_hora")

                st.info(f"✏️ Modificando cita que coincida con: **{filtro}**")

                resultados = list_appointments(q=filtro)

                if not resultados:
                    st.warning("❌ No encontré ninguna cita para modificar.")
                else:
                    cita = resultados[0]

                    # Actualizamos en la BD
                    delete_appointment(cita["id_cita"])

                    appt = Appointment(
                        nombre=cita["usuario_id"],
                        email=cita["usuario_id"],
                        servicio=cita["tipo"],
                        fecha_texto="",
                        fecha_iso=nueva_fecha,
                        hora_texto="",
                        hora_iso=nueva_hora,
                        observaciones=cita.get("descripcion", ""),
                        confianza=1.0,
                    )

                    new_id = add_appointment(appt)
                    st.success(f"✏️ Cita modificada (Nueva ID={new_id})")


with right:
    st.header("🗓️ Citas guardadas")

    q = st.text_input("Buscar cita (nombre/servicio)")
    rows = list_appointments(q=q)

    if not rows:
        st.info("Sin resultados.")
    else:
        for r in rows:
            st.markdown("---")
            st.markdown(f"**{r['id_cita']}** · {r['tipo']} · {r['fecha']} {r['hora']}")
            st.caption(f"Usuario: {r['usuario_id']}")
            if r.get("descripcion"):
                st.text(f"📝 {r['descripcion']}")

            if st.button("🗑️ Eliminar", key=f"del-{r['id_cita']}"):
                delete_appointment(r['id_cita'])
                st.rerun()

    st.markdown("---")
    st.header("📅 Tu Google Calendar")

    if st.session_state.get("creds") and st.session_state.get("user_email"):
        try:
            calendar_email = st.session_state.user_email
            url = f"https://calendar.google.com/calendar/embed?src={calendar_email}&ctz=Europe/Madrid"
            st.components.v1.html(
                f'<iframe src="{url}" style="border:0; width:100%; height:600px;" frameborder="0"></iframe>',
                height=600
            )
        except Exception as e:
            st.warning(f"No se pudo cargar calendario: {e}")
    else:
        st.info("Inicia sesión para ver tu calendario.")
