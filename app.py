import os
import pickle
import json
from datetime import datetime
from dateutil import parser as dtparse
import streamlit as st
from streamlit_cookies_manager import EncryptedCookieManager
from dotenv import load_dotenv, find_dotenv
import subprocess
import time
import pandas as pd

from backend.crew_manager import ejecutar_agentes_cita
from backend.db import init_db, get_user_by_email, upsert_user_token, get_all_appointments, get_all_users
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
from google.oauth2.credentials import Credentials

load_dotenv(find_dotenv())
init_db()

cookies = EncryptedCookieManager(
    prefix="agenda_",
    password=os.environ.get("COOKIES_PASSWORD", "mi_secreto_para_el_tfg_2026")
)

if not cookies.ready():
    st.stop()

st.session_state.cookies = cookies

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid",
]

os.makedirs("tokens", exist_ok=True)

st.set_page_config(page_title="Bot de Citas (IA + Calendar)", page_icon="🗓️", layout="wide")
st.title("🤖 Bot de Citas con IA y Google Calendar")

if "user_email" not in st.session_state:
    st.session_state.user_email = st.session_state.cookies.get("user_email", "")
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
    st.subheader("🔑 Mi Cuenta")
    
    if not st.session_state.get("user_email"):
        email_en_cookie = st.session_state.cookies.get("user_email")
        if email_en_cookie:
            st.session_state.user_email = email_en_cookie

    # Recuperar token de la base de datos (AHORA EN FORMATO JSON OFICIAL)
    if st.session_state.get("user_email") and not st.session_state.get("creds"):
        user = get_user_by_email(st.session_state.user_email)
        if user and user.get("token_path") and os.path.exists(user["token_path"]):
            st.session_state.creds = Credentials.from_authorized_user_file(user["token_path"], SCOPES)
            st.session_state.token_path = user["token_path"]
            st.session_state.usuario_id = st.session_state.user_email

    if not st.session_state.get("user_email"):
        if st.button("🔌 Conectar Google Calendar", use_container_width=True):
            try:
                flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
                creds = flow.run_local_server(port=0)
                oauth = build("oauth2", "v2", credentials=creds)
                user_info = oauth.userinfo().get().execute()
                
                email = user_info.get("email")
                nombre = user_info.get("name", "Usuario")
                usuario_id = email
                
                # GUARDAMOS EN .JSON
                token_path = f"tokens/{email.replace('@', '_at_')}.json"
                with open(token_path, "w", encoding="utf-8") as f:
                    f.write(creds.to_json())
                    
                upsert_user_token(usuario_id, nombre, email, token_path)
                
                st.session_state.creds = creds
                st.session_state.user_email = email
                st.session_state.user_name = nombre
                st.session_state.token_path = token_path
                st.session_state.usuario_id = usuario_id
                
                st.session_state.cookies["user_email"] = email
                st.session_state.cookies.save()
                st.success(f"✅ Hola, {nombre}")
                st.rerun() 
            except Exception as e:
                st.error(f"Error: {e}")
    else:
        st.info(f"👤 {st.session_state.user_email}")
        if st.button("Cerrar sesión", use_container_width=True):
            st.session_state.cookies["user_email"] = ""
            st.session_state.cookies.save()
            for key in ["creds","user_email","user_name","token_path","usuario_id"]:
                st.session_state.pop(key, None)
            st.rerun()

    st.markdown("---")

    st.subheader("📚 Normativas (RAG)")
    uploaded_pdf = st.file_uploader("Sube requisitos en PDF", type=["pdf"], label_visibility="collapsed")
    if uploaded_pdf is not None:
        if st.session_state.get("pdf_filename") != uploaded_pdf.name:
            with st.spinner("Memorizando..."):
                pdf_bytes = uploaded_pdf.read()
                if procesar_pdf_rag(pdf_bytes, uploaded_pdf.name):
                    st.session_state.pdf_filename = uploaded_pdf.name
                    st.success(f"✅ {uploaded_pdf.name} cargado.")
                else:
                    st.error("❌ Error al procesar.")
        else:
            st.caption(f"✓ Documento activo: {uploaded_pdf.name}")
    
    st.markdown("---")

    with st.expander("⚙️ Configuración IA"):
        provider = st.radio("Proveedor", ["Groq (cloud)", "Ollama (local)"], index=0)
        if provider.startswith("Ollama"):
            try:
                result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
                lines = result.stdout.strip().split("\n")[1:]
                modelos_locales = [line.split()[0] for line in lines if line.strip()]
                model_name = st.selectbox("Modelo local", modelos_locales if modelos_locales else ["⚠️ Sin modelos"])
                if st.button("🔄 Refrescar"): st.rerun()
            except:
                model_name = st.text_input("Modelo Ollama", value="llama3.2:1b")
        else:
            model_name = st.text_input("Modelo Groq", value="llama-3.3-70b-versatile")
            api_key = st.text_input("API KEY", type="password", value=os.getenv("GROQ_API_KEY", ""))

    with st.expander("🛡️ Acceso Admin"):
        modo_admin = st.toggle("Activar Dashboard")
        if modo_admin:
            admin_pass = st.text_input("Contraseña", type="password")
            if admin_pass == "admin123":
                st.session_state.is_admin = True
                st.success("Acceso concedido")
            else:
                st.session_state.is_admin = False
                if admin_pass: st.error("Incorrecta")
        else:
            st.session_state.is_admin = False

    st.markdown("---")

    if st.button("🧹 Limpiar Chat", use_container_width=True):
        st.session_state.local_chat_history = []
        st.session_state.system_messages = []
        st.rerun()

# ============================
# INTERFAZ PRINCIPAL O DASHBOARD
# ============================

if st.session_state.get("is_admin"):
    st.title("📊 Panel de Control General (BI)")
    
    # Obtener datos
    todas_citas = get_all_appointments()
    todos_usuarios = get_all_users()
    
    # 1. KPIs (Métricas principales)
    col1, col2, col3 = st.columns(3)
    col1.metric("👥 Usuarios Totales", len(todos_usuarios))
    col2.metric("📅 Citas Agendadas", len(todas_citas))
    col3.metric("📈 Promedio Citas/Usuario", round(len(todas_citas)/len(todos_usuarios), 1) if todos_usuarios else 0)
    
    st.markdown("---")
    
    # 2. Gráficos y Tablas
    col_chart, col_table = st.columns((1, 1))
    
    with col_chart:
        st.subheader("Demanda por Servicio")
        if todas_citas:
            df_citas = pd.DataFrame(todas_citas)
            conteo_servicios = df_citas['tipo'].value_counts()
            st.bar_chart(conteo_servicios)
        else:
            st.info("No hay datos suficientes para el gráfico.")
            
    with col_table:
        st.subheader("Últimas citas registradas")
        if todas_citas:
            df_mostrar = pd.DataFrame(todas_citas)[['fecha', 'hora', 'tipo', 'usuario_id']]
            st.dataframe(df_mostrar.head(10), use_container_width=True)
        else:
            st.info("La agenda está vacía.")

else:
    left, right = st.columns((7,5))

    with left:
        st.markdown("### 💬 Conversación")
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
        st.header("📅 Tu Calendar")

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