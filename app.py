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
from backend.services import (
    add_appointment,
    list_appointments,
    delete_appointment,
    set_event_id_for_appointment,
    find_appointment,
    update_appointment,
    extract_text_from_pdf_bytes
    
)
from backend.google_calendar import create_event as gc_create_event, update_event as gc_update_event, delete_event as gc_delete_event
from models.appointment import Appointment
from backend.chat_manager import ChatManagerDB
from backend.agent_rulebased import extract_json_block  

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
# 🆕 Inicializar texto del PDF
if "pdf_text" not in st.session_state:
    st.session_state.pdf_text = ""

# 🆕 NUEVO: estado conversacional para manejar preguntas pendientes
if "conversation_state" not in st.session_state:
    st.session_state.conversation_state = {
        "pending_action": None,
        "pending_data": {}
    }
    
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

    uploaded_pdf = st.file_uploader("Sube un PDF (opcional)", type=["pdf"])

    if uploaded_pdf is not None:
        # Leemos el archivo en bytes
        pdf_bytes = uploaded_pdf.read()

        # Llamamos al servicio de backend
        pdf_text = extract_text_from_pdf_bytes(pdf_bytes)
        
        

        # Guardamos el texto en sesión para usarlo en cualquier parte de la app
        st.session_state.pdf_text = pdf_text

        st.success("✅ PDF cargado y leído correctamente")
        


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
            
            # 1. Determinar el rol usando el atributo 'type' del objeto LangChain
            # 'm.type' será 'human' o 'ai'
            role_type = m.type 
            
            # 2. Mapear el tipo de LangChain al rol de Streamlit
            role = "user" if role_type == "human" else "assistant"
            
            # 3. Acceder al contenido usando el atributo 'content'
            content = m.content
            
            with st.chat_message(role):
                st.markdown(content)

    # Entrada del usuario
    user_msg = st.chat_input("Escribe tu mensaje…")

    if user_msg and chat_manager:
        with st.chat_message("user"):
            st.markdown(user_msg)

        response = chat_manager.ask(user_msg)

        with st.chat_message("assistant"):
            st.markdown(response)

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
                            token_path = st.session_state.get("token_path")
                            created = gc_create_event(
                                summary=f"{servicio} — {nombre}",
                                date_iso=fecha_iso,
                                time_hhmm=hora_iso,
                                duration_minutes=60,
                                description=f"Email: {email}\nNotas: {observaciones}",
                                attendees_emails=[email] if invite_user else None,
                                token_path=token_path
                            )
                            event_id = created.get("id")
                            if event_id:
                                set_event_id_for_appointment(new_id, event_id)
                            link = created.get("htmlLink")
                            if link:
                                st.success(f"📅 Evento creado: [Abrir]({link})")
                            # 👉 Recargar para que el iframe del calendario se actualice
                            st.rerun()
                        except Exception as e:
                            st.warning(f"⚠️ No se pudo crear evento: {e}")

            # --------------------------------------------------------
            # 2) CONSULTAR CITAS
            # --------------------------------------------------------
            elif action == "consult":

                st.info("📅 Consultando todas tus citas futuras en Google Calendar…")

                from backend.google_calendar import get_future_events
                eventos = get_future_events()

                if not eventos:
                    st.warning("❌ No tienes citas futuras en tu calendario.")
                else:
                    st.success(f"📋 Encontradas {len(eventos)} cita(s):")

                    for e in eventos:
                        start_raw = e["start"].get("dateTime") or e["start"].get("date")

                        if not start_raw:
                            start_fmt = "Fecha desconocida"
                        else:
                            try:
                                if "dateTime" in e["start"]:
                                    start_fmt = dtparse.parse(start_raw).strftime("%Y-%m-%d %H:%M")
                                else:
                                    start_fmt = dtparse.parse(start_raw).strftime("%Y-%m-%d")
                            except Exception:
                                start_fmt = "Fecha inválida"

                        st.markdown(f"- **{e['summary']}** → {start_fmt}")

            # --------------------------------------------------------
            # 3) CANCELAR CITA (CON GOOGLE CALENDAR)
            # --------------------------------------------------------
            elif action == "cancel":

                filtro = data.get("filtro", "")
                st.info(f"🗑️ Buscando para eliminar: **{filtro}**")

                from backend.services import list_appointments, delete_appointment
                current_email = os.getenv("CURRENT_USER_EMAIL", "")

                # Intentar sacar una fecha del filtro (dd/mm/yyyy o yyyy-mm-dd)
                import re
                fecha_busqueda = None
                m1 = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", filtro)
                m2 = re.search(r"(\d{4})-(\d{2})-(\d{2})", filtro)
                if m1:
                    d, m, y = m1.groups()
                    fecha_busqueda = f"{y}-{m.zfill(2)}-{d.zfill(2)}"
                elif m2:
                    y, m, d = m2.groups()
                    fecha_busqueda = f"{y}-{m}-{d}"

                if fecha_busqueda:
                    posibles = list_appointments(q=fecha_busqueda)
                else:
                    posibles = list_appointments(q=filtro)

                # Filtrar por usuario
                resultados = [c for c in posibles if c.get("usuario_id") == current_email]

                if not resultados:
                    st.warning("❌ No encontré ninguna cita para cancelar.")
                else:
                    cita = resultados[0]  # primera coincidencia

                    token_path = st.session_state.get("token_path")
                    from backend.google_calendar import delete_event as gc_delete_event
                    from backend.services import delete_appointment

                    # ----------------------------------------------------
                    # 1) ELIMINAR DEL GOOGLE CALENDAR
                    # ----------------------------------------------------
                    try:
                        event_id = cita.get("id_evento_google")

                        if event_id:
                            gc_delete_event(event_id, token_path=token_path)
                            st.success("📅 Evento eliminado de Google Calendar.")
                            # 👉 Recargar para que el iframe del calendario se actualice
                            st.rerun()
                        else:
                            st.info("ℹ️ La cita no tenía evento en Google Calendar.")
                    except Exception as e:
                        st.warning(f"⚠️ Error eliminando evento de Google Calendar: {e}")

                    # ----------------------------------------------------
                    # 2) ELIMINAR DE LA BASE DE DATOS
                    # ----------------------------------------------------
                    delete_appointment(cita["id_cita"])
                    st.success(f"🗑️ Cita eliminada correctamente de la base de datos (ID={cita['id_cita']}).")

            # --------------------------------------------------------
            # 4) MODIFICAR CITA  (VERSIÓN COMPLETA CON GOOGLE CALENDAR)
            # --------------------------------------------------------
            elif action == "modify":
                filtro = data.get("filtro", "")
                nueva_fecha = data.get("nueva_fecha")
                nueva_hora = data.get("nueva_hora")

                st.info(f"✏️ Modificando cita que coincida con: **{filtro}**")

                from backend.services import list_appointments, update_appointment, set_event_id_for_appointment
                from backend.google_calendar import update_event as gc_update_event, create_event as gc_create_event

                current_email = os.getenv("CURRENT_USER_EMAIL", "")

                # Extraer fecha del filtro si existe
                import re
                fecha_busqueda = None
                m1 = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", filtro)
                m2 = re.search(r"(\d{4})-(\d{2})-(\d{2})", filtro)
                if m1:
                    d, m, y = m1.groups()
                    fecha_busqueda = f"{y}-{m.zfill(2)}-{d.zfill(2)}"
                elif m2:
                    y, m, d = m2.groups()
                    fecha_busqueda = f"{y}-{m}-{d}"

                if fecha_busqueda:
                    posibles = list_appointments(q=fecha_busqueda)
                else:
                    posibles = list_appointments(q=filtro)

                resultados = [c for c in posibles if c.get("usuario_id") == current_email]

                if not resultados:
                    st.warning("❌ No encontré ninguna cita para modificar.")
                else:
                    cita = resultados[0]  # primera coincidencia del usuario logueado
                    token_path = st.session_state.get("token_path")
                    old_event_id = cita.get("id_evento_google")

                    # Validaciones mínimas
                    if not nueva_fecha or not nueva_hora:
                        st.warning("⚠️ Faltan datos para modificar la cita (fecha y/o hora nuevas).")
                        st.stop()

                    # 1) Google Calendar
                    try:
                        if old_event_id:
                            updated_event = gc_update_event(
                                old_event_id,
                                nueva_fecha,
                                nueva_hora,
                                token_path=token_path
                            )
                            st.success("📅 Evento actualizado en Google Calendar.")
                            # 👉 Recargar para que el iframe del calendario se actualice
                            st.rerun()
                        else:
                            new_event = gc_create_event(
                                summary=f"{cita['tipo']} — {cita['usuario_id']}",
                                date_iso=nueva_fecha,
                                time_hhmm=nueva_hora,
                                duration_minutes=60,
                                description=cita.get("descripcion", ""),
                                attendees_emails=[cita["usuario_id"]],
                                token_path=token_path
                            )
                            if new_event.get("id"):
                                set_event_id_for_appointment(cita["id_cita"], new_event["id"])
                            st.success("📅 Nuevo evento creado en Google Calendar.")
                            # 👉 También recargamos aquí
                            st.rerun()
                    except Exception as e:
                        st.warning(f"⚠️ Error actualizando Google Calendar: {e}")

                    # 2) BD local
                    update_appointment(
                        usuario_id=cita["usuario_id"],
                        id_cita=cita["id_cita"],
                        nueva_fecha=nueva_fecha,
                        nueva_hora=nueva_hora
                    )
                    st.success("✏️ Cita modificada correctamente en la base de datos.")


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

    st.markdown("---")
    st.header("📄 Contexto desde PDF")
    pdf_text = st.session_state.get("pdf_text", "")   # 👈 lo traes de sesión

    if pdf_text:
        st.text_area("Texto del PDF", pdf_text[:5000], height=200)
    else:
        st.info("No se ha cargado ningún PDF todavía.")