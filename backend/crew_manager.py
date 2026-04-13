# backend/crew_manager.py
from crewai import Agent, Task, Crew, Process, LLM
from datetime import datetime
import os
from dotenv import load_dotenv
from backend.tools_openai import agendar_cita_tool, consultar_calendario_tool, consultar_pdf_tool, modificar_cita_tool, eliminar_cita_tool

load_dotenv()

def ejecutar_agentes_cita(mensaje_usuario: str, email_usuario: str) -> str:
    """
    Inicia un flujo secuencial con CrewAI usando el LLM de Groq.
    Corregido para precisión de fechas y persistencia de datos.
    """
    # 🚀 MEJORA: Pasamos el día de la semana para que el LLM no se pierda
    ahora = datetime.now()
    hoy_fecha = ahora.strftime("%Y-%m-%d")
    dia_semana = ahora.strftime("%A") # Ejemplo: "Monday"
    
    api_key_groq = os.getenv("GROQ_API_KEY")
    if not api_key_groq:
        return "❌ Error: No se ha encontrado GROQ_API_KEY en el archivo .env"

    mi_llm = LLM(
        model="llama-3.3-70b-versatile",
        temperature=0.0, 
        base_url="https://api.groq.com/openai/v1",
        api_key=api_key_groq
    )
    
    # 2. DEFINICIÓN DE AGENTES
    analista = Agent(
        role='Analista de Intenciones y Fechas',
        goal='Extraer datos estructurados y realizar cálculos de fechas exactos.',
        backstory='Eres un asistente administrativo experto en España. Eres extremadamente preciso calculando fechas.',
        verbose=True,
        allow_delegation=False,
        llm=mi_llm
    )

    gestor = Agent(
        role='Coordinador de Agenda',
        goal='Confirmar o ejecutar acciones de agenda basándose en el análisis.',
        backstory='Eres un gestor eficiente. Si los datos están completos, ejecutas la herramienta. Si falta la HORA o el SERVICIO, lo pides.',
        verbose=True,
        allow_delegation=False,
        tools=[agendar_cita_tool, consultar_calendario_tool, consultar_pdf_tool, modificar_cita_tool, eliminar_cita_tool], 
        llm=mi_llm
    )

    # 3. DEFINICIÓN DE TAREAS (Lógica de Fechas Blindada)
    tarea_analisis = Task(
        description=f'''Hoy es {dia_semana}, fecha: {hoy_fecha}. 
        Analiza este historial: "{mensaje_usuario}"
        
        REGLAS CRÍTICAS DE INTENCIÓN:
        1. PRIORIDAD RAG: Si el usuario hace una PREGUNTA (usa signos de interrogación o palabras como "cuánto", "qué dice", "cuándo") sobre normativas o el PDF, la intención es SIEMPRE "CONSULTAR_PDF". 
        2. NO AGENDAR DUDAS: Si el usuario pregunta "cuánto tiempo de ayuno", NO agendes una cita llamada "Ayuno". Simplemente marca la intención como "CONSULTAR_PDF".
        3. AGENDAR: Solo si el usuario pide explícitamente "agendar", "reservar" o "cita para...".
        ''',
        expected_output='Informe con la Intención clara (CONSULTAR_PDF, AGENDAR, MODIFICAR, ELIMINAR) y los datos asociados.',
        agent=analista
    )

    tarea_ejecucion = Task(
        description=f'''Ejecuta la acción siguiendo estas órdenes de seguridad:
        
        - 🚫 PROHIBICIÓN: Si la intención detectada es MODIFICAR, tienes TERMINANTEMENTE PROHIBIDO usar "agendar_cita_tool". Debes usar ÚNICAMENTE "modificar_cita_tool".
        - Si es agendar desde cero: usa agendar_cita_tool (email: {email_usuario}).
        - Si es modificar: usa modificar_cita_tool (pasa el email: {email_usuario}, el servicio a buscar, y la NUEVA fecha y hora).
        - Si es consultar o PDF: usa la herramienta correspondiente.''',
        expected_output='Respuesta final clara. Si modificaste, confirma que has ACTUALIZADO la cita existente sin crear una nueva.',
        agent=gestor
    )

    equipo_citas = Crew(
        agents=[analista, gestor],
        tasks=[tarea_analisis, tarea_ejecucion],
        process=Process.sequential 
    )

    resultado = equipo_citas.kickoff()
    return str(resultado.raw) if hasattr(resultado, 'raw') else str(resultado)