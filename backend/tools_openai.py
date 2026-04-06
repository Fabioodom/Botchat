import os
from crewai.tools import tool
from models.appointment import Appointment
from langchain_chroma import Chroma
from langchain_community.embeddings import OllamaEmbeddings

from backend.services import (
    add_appointment, set_event_id_for_appointment, find_appointment, 
    update_appointment, delete_appointment
)
from backend.google_calendar import (
    get_future_events, create_event, update_event, delete_event
)

@tool
def consultar_calendario_tool(vacio: str = "") -> str:
    """Útil para consultar las citas o eventos futuros en el calendario."""
    try:
        eventos = get_future_events()
        if not eventos:
            return "No hay eventos próximos en el calendario."
        
        resultado = "Eventos en Google Calendar:\n"
        for e in eventos:
            inicio = e['start'].get('dateTime', e['start'].get('date'))
            resumen = e.get('summary', 'Sin título')
            resultado += f"- {resumen} ({inicio})\n"
        return resultado
    except Exception as e:
        return f"Error: {str(e)}"

@tool
def agendar_cita_tool(descripcion: str, fecha: str, hora: str, email_usuario: str) -> str:
    """Útil para agendar una nueva cita."""
    try:
        # 1. Guardar en DB
        appt = Appointment(
            email=email_usuario, servicio=descripcion, 
            fecha_iso=fecha, hora_iso=hora, observaciones="Vía IA"
        )
        new_id = add_appointment(appt)
        
        # 2. Guardar en Google Calendar
        event = create_event(summary=descripcion, date_iso=fecha, time_hhmm=hora)
        
        # 3. Guardar el ID de Google en nuestra base de datos
        google_event_id = event.get('id')
        if google_event_id:
            set_event_id_for_appointment(new_id, google_event_id)
            
        return f"✅ Cita '{descripcion}' agendada para {fecha} a las {hora}."
    except Exception as e:
        return f"Error al agendar: {str(e)}"

@tool
def consultar_pdf_tool(pregunta: str) -> str:
    """Busca información en el PDF."""
    DB_VECTOR_PATH = "./chroma_db_data"
    if not os.path.exists(DB_VECTOR_PATH):
        return "No hay ningún documento PDF subido."
    try:
        from langchain_chroma import Chroma
        from langchain_community.embeddings import OllamaEmbeddings
        embeddings = OllamaEmbeddings(model="llama3.2:1b")
        vectorstore = Chroma(persist_directory=DB_VECTOR_PATH, embedding_function=embeddings)
        docs = vectorstore.similarity_search(pregunta, k=3)
        
        if not docs:
            return "No encontré información."
            
        contexto_limpio = " ".join([d.page_content.replace("\n", " ") for d in docs])
        return f"Información cruda del documento: {contexto_limpio}"
    except Exception as e:
        return f"Error: {str(e)}"

@tool
def modificar_cita_tool(descripcion_actual: str, nueva_fecha: str, nueva_hora: str, email_usuario: str) -> str:
    """Útil para cambiar fecha/hora de una cita existente."""
    try:
        from backend.services import find_appointment, update_appointment
        from backend.google_calendar import update_event
        
        cita = find_appointment(usuario_email=email_usuario, tipo=descripcion_actual)
        if not cita:
            return f"No encontré la cita '{descripcion_actual}' en tu agenda."
        
        id_google = cita.get('id_evento_google')
        if id_google:
            update_event(event_id=id_google, new_date_iso=nueva_fecha, new_time_hhmm=nueva_hora)
            
        update_appointment(email_usuario, cita['id_cita'], nueva_fecha, nueva_hora)
        return f"✅ Cita modificada al {nueva_fecha} a las {nueva_hora}."
    except Exception as e:
        return f"Error al modificar: {str(e)}"

@tool
def eliminar_cita_tool(descripcion: str, email_usuario: str) -> str:
    """Útil para borrar una cita."""
    try:
        cita = find_appointment(usuario_email=email_usuario, tipo=descripcion)
        if not cita:
            return f"No encontré la cita '{descripcion}' en tu agenda."
            
        id_google = cita.get('id_evento_google')
        if id_google:
            try:
                delete_event(id_google)
            except: pass
            
        delete_appointment(cita['id_cita'])
        return f"✅ La cita '{descripcion}' ha sido cancelada."
    except Exception as e:
        return f"Error al eliminar: {str(e)}"