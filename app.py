import os, json
import streamlit as st
from dotenv import load_dotenv, find_dotenv

from backend.db import init_db
from backend.services import add_appointment, list_appointments, delete_appointment
from backend.google_calendar import create_event
from backend.agent_rulebased import (
    initial_state, prompt_for, parse_and_update, is_complete, final_json
)
from models.appointment import Appointment

st.set_page_config(page_title="Bot de Citas (sin IA)", page_icon="🗓️", layout="wide")
load_dotenv(find_dotenv())
init_db()

# Estado de conversación
if "history" not in st.session_state:
    st.session_state.history = []
if "state" not in st.session_state:
    st.session_state.state = initial_state()
if "saved_last_id" not in st.session_state:
    st.session_state.saved_last_id = None

with st.sidebar:
    st.header("⚙️ Configuración")
    autosave = st.toggle("Guardar citas en SQLite", value=True)
    add_to_calendar = st.toggle("Crear evento en Google Calendar", value=True)
    invite_user = st.toggle("Invitar al cliente por email", value=True)
    if st.button("🧹 Reiniciar flujo"):
        st.session_state.history = []
        st.session_state.state = initial_state()
        st.session_state.saved_last_id = None
        st.rerun()

st.title("🗓️ Bot de Citas · Modo Entrevista (sin IA)")

left, right = st.columns((7,5), gap="large")

with left:
    # Mostrar historial
    for m in st.session_state.history:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    # Si es la primera vez o tras reinicio, el bot pregunta el primer dato
    if not st.session_state.history:
        first_q = prompt_for(st.session_state.state["expected"])
        st.session_state.history.append({"role":"assistant","content":first_q})
        with st.chat_message("assistant"): st.markdown(first_q)

    # Input usuario
    user_msg = st.chat_input("Escribe tu respuesta…")
    if user_msg is not None and user_msg != "":
        # pinta turno user
        st.session_state.history.append({"role":"user","content":user_msg})
        with st.chat_message("user"): st.markdown(user_msg)

        # procesa y decide siguiente pregunta
        st.session_state.state = parse_and_update(st.session_state.state, user_msg)

        if is_complete(st.session_state.state):
            # mostrar JSON final
            data = final_json(st.session_state.state)
            block = "```json\n" + json.dumps(data, ensure_ascii=False, indent=2) + "\n```"
            msg = "¡Perfecto! Estos son tus datos de la cita. ¿Está todo correcto?\n\n" + block
            st.session_state.history.append({"role":"assistant","content":msg})
            with st.chat_message("assistant"): st.markdown(msg)

            # Guardar y calendar (una sola vez por completitud)
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

            # Tras completar, puedes reiniciar el flujo automáticamente:
            # st.session_state.history.append({"role":"assistant","content":"Si deseas crear otra cita, escribe 'nueva'."})

        else:
            # pregunta siguiente
            nxt_q = prompt_for(st.session_state.state["expected"])
            st.session_state.history.append({"role":"assistant","content":nxt_q})
            with st.chat_message("assistant"): st.markdown(nxt_q)

    # Panel lateral de “datos interpretados”
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
    st.header("🗓️ Citas guardadas")
    q = st.text_input("Buscar (nombre / servicio)")
    rows = list_appointments(q=q)
    if not rows:
        st.info("Sin resultados.")
    else:
        for r in rows:
            rid = r["id"] if isinstance(r, dict) else getattr(r, "id", None)
            servicio = r.get("servicio") if isinstance(r, dict) else getattr(r, "servicio", "")
            fecha_iso = r.get("fecha_iso") if isinstance(r, dict) else getattr(r, "fecha_iso", "")
            hora_iso = r.get("hora_iso") if isinstance(r, dict) else getattr(r, "hora_iso", "")
            nombre = r.get("nombre") if isinstance(r, dict) else getattr(r, "nombre", "")
            email = r.get("email") if isinstance(r, dict) else getattr(r, "email", "")

            st.markdown("---")
            st.markdown(f"**{rid}** · {servicio} · {fecha_iso} {hora_iso}")
            st.caption(f"{nombre} — {email}")
            if st.button("🗑️ Eliminar", key=f"del-{rid}"):
                delete_appointment(rid)
                st.rerun()
