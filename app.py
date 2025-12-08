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
from backend.google_calendar import (
    create_event as gc_create_event, 
    update_event as gc_update_event, 
    delete_event as gc_delete_event
)
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


st.set_page_config(page_title="Bot de Citas (IA + Calendar)", page_icon="🗓️", layout="wide")
st.title("🤖 Bot de Citas con IA y Google Calendar")



if "chat_manager" not in st.session_state:
    st.session_state.chat_manager = None
if "usuario_id" not in st.session_state:
    st.session_state.usuario_id = None
if "pdf_text" not in st.session_state:
    st.session_state.pdf_text = ""

if "system_messages" not in st.session_state:
    st.session_state.system_messages = []

if "local_chat_history" not in st.session_state:
    st.session_state.local_chat_history = []


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
        pdf_bytes = uploaded_pdf.read()
        pdf_text = extract_text_from_pdf_bytes(pdf_bytes)
        st.session_state.pdf_text = pdf_text
        st.session_state.pdf_filename = uploaded_pdf.name
        st.success(f"✅ PDF '{uploaded_pdf.name}' cargado correctamente")
        
        # Mostrar preview del contenido
        with st.expander("📄 Ver contenido del PDF"):
            st.text_area("Texto extraído", pdf_text[:2000], height=200, disabled=True)
            if len(pdf_text) > 2000:
                st.caption(f"Mostrando los primeros 2000 caracteres de {len(pdf_text)} totales")
    else:
        st.session_state.pdf_text = ""
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

    
    if st.button("🧹 Limpiar chat") and st.session_state.chat_manager:
        st.session_state.chat_manager.reset_memory()
        st.session_state.local_chat_history = []
        st.session_state.system_messages = []
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

    if user_msg and chat_manager:

        # 1) Añadir el mensaje del usuario al historial local
        st.session_state.local_chat_history.append({
            "role": "user",
            "content": user_msg
        })

        # 2) Llamar al gestor de chat (esto guarda en la BD y devuelve la respuesta)
        raw_response = chat_manager.ask(user_msg)

        # 3) Añadir la respuesta del bot al historial local
        st.session_state.local_chat_history.append({
            "role": "assistant",
            "content": raw_response
        })

        # 4) Intentar extraer JSON para ejecutar acciones (create / consult / cancel / modify)
        data = extract_json_block(raw_response)

        if data:
            action = data.get("action", "").lower()

            # --------------------------------------------------------
            # CREAR CITA
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
                    st.session_state.system_messages.append({
                        "type": "success",
                        "text": f"✅ Cita guardada (ID={new_id})"
                    })

                    # Crear evento en Google Calendar (si está activado)
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
                                st.session_state.system_messages.append({
                                    "type": "success",
                                    "text": f"📅 Evento creado: [Abrir]({link})"
                                })
                        except Exception as e:
                            st.session_state.system_messages.append({
                                "type": "warning",
                                "text": f"⚠️ No se pudo crear evento en Google Calendar: {e}"
                            })

            # --------------------------------------------------------
            # CONSULTAR CITAS
            # --------------------------------------------------------
            elif action == "consult":
                from backend.google_calendar import get_future_events
                st.session_state.system_messages.append({
                    "type": "info",
                    "text": "📅 Consultando todas tus citas futuras en Google Calendar…"
                })

                try:
                    eventos = get_future_events()
                except Exception as e:
                    eventos = []
                    st.session_state.system_messages.append({
                        "type": "warning",
                        "text": f"⚠️ Error al consultar Google Calendar: {e}"
                    })

                if not eventos:
                    st.session_state.system_messages.append({
                        "type": "warning",
                        "text": "❌ No tienes citas futuras en tu calendario."
                    })
                else:
                    texto = f"📋 **Encontradas {len(eventos)} cita(s):**\n\n"
                    for e in eventos:
                        start_raw = e["start"].get("dateTime") or e["start"].get("date")
                        if start_raw:
                            try:
                                if "dateTime" in e["start"]:
                                    start_fmt = dtparse.parse(start_raw).strftime("%Y-%m-%d %H:%M")
                                else:
                                    start_fmt = dtparse.parse(start_raw).strftime("%Y-%m-%d")
                            except Exception:
                                start_fmt = "Fecha inválida"
                        else:
                            start_fmt = "Fecha desconocida"
                        texto += f"- **{e['summary']}** → {start_fmt}\n"

                    st.session_state.system_messages.append({
                        "type": "markdown",
                        "text": texto
                    })

            # --------------------------------------------------------
            # CANCELAR CITA
            # --------------------------------------------------------
            elif action == "cancel":
                filtro = data.get("filtro", "")
                from backend.services import list_appointments, delete_appointment
                current_email = os.getenv("CURRENT_USER_EMAIL", "")

                st.session_state.system_messages.append({
                    "type": "info",
                    "text": f"🗑️ Buscando cita para eliminar con filtro: **{filtro}**"
                })

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
                    st.session_state.system_messages.append({
                        "type": "warning",
                        "text": "❌ No encontré ninguna cita para cancelar."
                    })
                else:
                    cita = resultados[0]
                    token_path = st.session_state.get("token_path")
                    from backend.google_calendar import delete_event as gc_delete_event

                    try:
                        event_id = cita.get("id_evento_google")
                        if event_id:
                            gc_delete_event(event_id, token_path=token_path)
                            st.session_state.system_messages.append({
                                "type": "success",
                                "text": "📅 Evento eliminado de Google Calendar."
                            })
                        else:
                            st.session_state.system_messages.append({
                                "type": "info",
                                "text": "ℹ️ La cita no tenía evento en Google Calendar."
                            })
                    except Exception as e:
                        st.session_state.system_messages.append({
                            "type": "warning",
                            "text": f"⚠️ Error eliminando en Google Calendar: {e}"
                        })

                    delete_appointment(cita["id_cita"])
                    st.session_state.system_messages.append({
                        "type": "success",
                        "text": f"🗑️ Cita eliminada de la base de datos (ID={cita['id_cita']})."
                    })

            # --------------------------------------------------------
            # MODIFICAR CITA
            # --------------------------------------------------------
            elif action == "modify":
                filtro = data.get("filtro", "")
                nueva_fecha = data.get("nueva_fecha")
                nueva_hora = data.get("nueva_hora")

                from backend.services import list_appointments, update_appointment, set_event_id_for_appointment
                from backend.google_calendar import update_event as gc_update_event, create_event as gc_create_event

                current_email = os.getenv("CURRENT_USER_EMAIL", "")

                st.session_state.system_messages.append({
                    "type": "info",
                    "text": f"✏️ Buscando cita para modificar con filtro: **{filtro}**"
                })

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
                    st.session_state.system_messages.append({
                        "type": "warning",
                        "text": "❌ No encontré ninguna cita para modificar."
                    })
                else:
                    cita = resultados[0]
                    token_path = st.session_state.get("token_path")
                    old_event_id = cita.get("id_evento_google")

                    if not nueva_fecha or not nueva_hora:
                        st.session_state.system_messages.append({
                            "type": "warning",
                            "text": "⚠️ Faltan datos para modificar la cita (nueva fecha y/o nueva hora)."
                        })
                    else:
                        try:
                            if old_event_id:
                                gc_update_event(
                                    old_event_id,
                                    nueva_fecha,
                                    nueva_hora,
                                    token_path=token_path
                                )
                                st.session_state.system_messages.append({
                                    "type": "success",
                                    "text": "📅 Evento actualizado en Google Calendar."
                                })
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
                                st.session_state.system_messages.append({
                                    "type": "success",
                                    "text": "📅 Nuevo evento creado en Google Calendar."
                                })
                        except Exception as e:
                            st.session_state.system_messages.append({
                                "type": "warning",
                                "text": f"⚠️ Error actualizando Google Calendar: {e}"
                            })

                        update_appointment(
                            usuario_id=cita["usuario_id"],
                            id_cita=cita["id_cita"],
                            nueva_fecha=nueva_fecha,
                            nueva_hora=nueva_hora
                        )
                        st.session_state.system_messages.append({
                            "type": "success",
                            "text": "✏️ Cita modificada correctamente en la base de datos."
                        })

        
        st.rerun()


with right:
    #st.header("🗓️ Citas guardadas")

    #q = st.text_input("Buscar cita (nombre/servicio)")
    #rows = list_appointments(q=q)

    #if not rows:
        #st.info("Sin resultados.")
    #else:
        #for r in rows:
         #   st.markdown("---")
          #  st.markdown(f"**{r['id_cita']}** · {r['tipo']} · {r['fecha']} {r['hora']}")
           # st.caption(f"Usuario: {r['usuario_id']}")
            #if r.get("descripcion"):
             #   st.text(f"📝 {r['descripcion']}")

            #if st.button("🗑️ Eliminar", key=f"del-{r['id_cita']}"):
             #   delete_appointment(r['id_cita'])
              #  st.rerun()

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
    #st.header("📄 Contexto desde PDF")
    #pdf_text = st.session_state.get("pdf_text", "")

    #if pdf_text:
        #st.text_area("Texto del PDF", pdf_text[:5000], height=200)
    #else:
        #st.info("No se ha cargado ningún PDF todavía.")