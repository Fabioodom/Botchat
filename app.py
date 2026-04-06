import os
import pickle
import json
from datetime import datetime
from dateutil import parser as dtparse
import streamlit as st
from dotenv import load_dotenv, find_dotenv
import subprocess
from backend.crew_manager import ejecutar_agentes_cita
import time

from backend.db import init_db, get_user_by_email, upsert_user_token
from backend.services import (
    add_appointment,
    list_appointments,
    delete_appointment,
    set_event_id_for_appointment,
    find_appointment,
    update_appointment,
    procesar_pdf_rag
)
from backend.google_calendar import (
    create_event as gc_create_event, 
    update_event as gc_update_event, 
    delete_event as gc_delete_event
)
from models.appointment import Appointment
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

load_dotenv(find_dotenv())
init_db()

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid",
]

os.makedirs("tokens", exist_ok=True)

st.set_page_config(page_title="Bot de Citas (IA + Calendar)", page_icon="🗓️", layout="wide")
st.title("🤖 Bot de Citas con IA y Google Calendar")

if "usuario_id" not in st.session_state:
    st.session_state.usuario_id = None
if "pdf_text" not in st.session_state:
    st.session_state.pdf_text = ""

if "system_messages" not in st.session_state:
    st.session_state.system_messages = []

if "local_chat_history" not in st.session_state:
    st.session_state.local_chat_history = []

if "calendar_timestamp" not in st.session_state:
    st.session_state.calendar_timestamp = 0


# ============================
# SIDEBAR
# ============================
with st.sidebar:
    st.header("⚙️ Configuración")

    # ------------------- LLM -----------------------
    st.subheader("🧠 Proveedor LLM")
    # Dejamos Groq por defecto ya que es lo que usan los Agentes
    provider = st.radio("Proveedor LLM", ["Groq (cloud)", "Ollama (local)"], index=0)

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
        model_name = st.text_input("Modelo Groq", value="llama-3.3-70b-versatile")
        api_key = st.text_input("GROQ_API_KEY", type="password", value=os.getenv("GROQ_API_KEY", ""))

    autosave = st.checkbox("Guardar citas en SQLite", value=True)
    add_to_calendar = st.checkbox("Crear evento en Google Calendar", value=True)
    invite_user = st.checkbox("Invitar por email", value=True)

    # ------------------- RAG (SUBIR PDF) ----------------
    st.subheader("📚 Memoria de Documentos")
    uploaded_pdf = st.file_uploader("Sube un PDF (Contexto RAG)", type=["pdf"])

    if uploaded_pdf is not None:
        if st.session_state.get("pdf_filename") != uploaded_pdf.name:
            with st.spinner("Procesando y memorizando documento usando Ollama..."):
                pdf_bytes = uploaded_pdf.read()
                exito = procesar_pdf_rag(pdf_bytes, uploaded_pdf.name)
                
                if exito:
                    st.session_state.pdf_filename = uploaded_pdf.name
                    st.success(f"✅ PDF '{uploaded_pdf.name}' vectorizado correctamente.")
                else:
                    st.error("❌ Hubo un error al procesar el PDF.")
        else:
            st.success(f"✅ PDF '{uploaded_pdf.name}' ya está en la memoria vectorial.")
    else:
        st.session_state.pdf_filename = None

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

                st.success(f"✅ Conectado como {nombre} ({email})")

            except Exception as e:
                st.error(f"Error al iniciar sesión: {e}")

    else:
        st.info(f"👤 Usuario: {st.session_state.user_email}")
        if st.button("Cerrar sesión"):
            for key in ["creds","user_email","user_name","token_path","usuario_id"]:
                st.session_state.pop(key, None)
            st.rerun()

    if st.button("🧹 Limpiar chat"):
        st.session_state.local_chat_history = []
        st.session_state.system_messages = []
        st.rerun()

# ============================
# INTERFAZ PRINCIPAL
# ============================
left, right = st.columns((7,5))

with left:
    st.markdown("### 💬 Conversación")

    # Contenedor de chat con altura fija
    chat_container = st.container(height=500)

    with chat_container:
        # 1) Pintar historial de mensajes (usuario y bot)
        for msg in st.session_state.local_chat_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        # 2) Pintar mensajes de sistema (éxito, error, etc.) como si fueran mensajes del bot
        for msg in st.session_state.system_messages:
            with st.chat_message("assistant"):
                tipo = msg.get("type", "markdown")
                texto = msg.get("text", "")
                if tipo == "success":
                    st.success(texto)
                elif tipo == "info":
                    st.info(texto)
                elif tipo == "warning":
                    st.warning(texto)
                elif tipo == "error":
                    st.error(texto)
                else:
                    st.markdown(texto)

    # Input del usuario
    user_msg = st.chat_input("Escribe tu mensaje…")

    if user_msg:
        # 1) Añadir el mensaje del usuario al historial visual
        st.session_state.local_chat_history.append({
            "role": "user",
            "content": user_msg
        })
        st.session_state.system_messages = []

        # 2) Llamar a nuestro equipo de Agentes de CrewAI
        email_actual = st.session_state.get("user_email", "usuario@desconocido.com")
        
        with chat_container:
            with st.chat_message("assistant"):
                with st.spinner("🤖 Los agentes están analizando y procesando tu solicitud..."):
                    try:
                        historial_reciente = st.session_state.local_chat_history[-5:]
                        texto_contexto = "HISTORIAL DE LA CONVERSACIÓN:\n"
                        for msg in historial_reciente:
                            texto_contexto += f"- {msg['role']}: {msg['content']}\n"

                        respuesta_agentes = ejecutar_agentes_cita(texto_contexto, email_actual)
                    except Exception as e:
                        respuesta_agentes = f"❌ Lo siento, mis agentes tuvieron un error: {str(e)}"
                
                st.markdown(respuesta_agentes)

        # 3) Añadir al historial
        st.session_state.local_chat_history.append({
            "role": "assistant",
            "content": respuesta_agentes
        })

        import time 
        st.session_state.calendar_timestamp = int(time.time())

        st.rerun()

with right:
    st.markdown("---")
    st.header("📅 Tu Google Calendar")

    if st.session_state.get("creds") and st.session_state.get("user_email"):
        try:
            calendar_email = st.session_state.user_email
            
            url = f"https://calendar.google.com/calendar/embed?src={calendar_email}&ctz=Europe/Madrid&v={st.session_state.calendar_timestamp}"
            
            st.components.v1.html(
                f'<iframe src="{url}" style="border:0; width:100%; height:600px;" frameborder="0"></iframe>',
                height=600
            )
        except Exception as e:
            st.warning(f"No se pudo cargar calendario: {e}")
    else:
        st.info("Inicia sesión para ver tu calendario.")
    
    st.markdown("---")