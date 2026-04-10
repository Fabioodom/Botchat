from crewai import Agent, Task, Crew, Process, LLM
from datetime import datetime
import os
from dotenv import load_dotenv
from backend.tools_openai import agendar_cita_tool, consultar_calendario_tool, consultar_pdf_tool, modificar_cita_tool, eliminar_cita_tool

load_dotenv()

def ejecutar_agentes_cita(mensaje_usuario: str, email_usuario: str) -> str:
    """
    Inicia un flujo secuencial con CrewAI usando el LLM de Groq.
    """
    hoy = datetime.now().strftime("%Y-%m-%d")
    api_key_groq = os.getenv("GROQ_API_KEY")
    
    if not api_key_groq:
        return "❌ Error: No se ha encontrado GROQ_API_KEY en el archivo .env"

    mi_llm = LLM(
        model="llama-3.3-70b-versatile",
        temperature=0.0, # Mantenemos 0.0 para que no alucine con las fechas
        base_url="https://api.groq.com/openai/v1",
        api_key=api_key_groq
    )
    
    # 2. DEFINICIÓN DE AGENTES
    analista = Agent(
        role='Analista de Intenciones',
        goal='Determinar la intención del usuario y extraer datos clave (fecha, hora, servicio).',
        backstory='Experto en lenguaje natural. Tu función es estructurar la petición del usuario.',
        verbose=True,
        allow_delegation=False,
        llm=mi_llm
    )

    gestor = Agent(
        role='Coordinador de Agenda',
        goal='Responder al usuario y ejecutar acciones técnicas usando herramientas.',
        backstory='Asistente eficiente que utiliza herramientas para consultar o agendar citas.',
        verbose=True,
        allow_delegation=False,
        tools=[agendar_cita_tool, consultar_calendario_tool, consultar_pdf_tool, modificar_cita_tool, eliminar_cita_tool], 
        llm=mi_llm
    )

    # 3. DEFINICIÓN DE TAREAS (Flujo Secuencial)
    tarea_analisis = Task(
        description=f'''Hoy es {hoy}. Lee este historial de chat reciente del usuario: 
        
        "{mensaje_usuario}"
        
        REGLAS ESTRICTAS PARA EL ANALISTA:
        1. MEMORIA: Analiza el historial completo. Si el usuario dijo el servicio antes (ej. "reunión de trabajo"), USA ESE SERVICIO. ¡NUNCA te inventes "cita médica" si no lo ha dicho!
        2. FECHAS: Hoy es {hoy}. Si el usuario dice "el próximo lunes" o "mañana", HAZ EL CÁLCULO MENTAL desde hoy ({hoy}) para obtener la fecha exacta en formato YYYY-MM-DD.
        3. AGENDAR: Si la intención es crear, extrae Fecha (YYYY-MM-DD), Hora (HH:MM) y Servicio. Si en el historial ya te dio el servicio y ahora te da la fecha, únelos.
        4. MODIFICAR/ELIMINAR: Extrae SOLO el nombre del servicio.
        ''',
        expected_output='Un resumen estructurado con la intención actual y los datos combinados del historial. Si falta fecha o servicio, indícalo.',
        agent=analista
    )

    tarea_ejecucion = Task(
        description=f'''Ejecuta la acción necesaria basándote en el análisis:
        - Si es agendar: usa agendar_cita_tool (email: {email_usuario}).
        - Si es eliminar: usa eliminar_cita_tool (PASA EL email: {email_usuario} Y EL servicio).
        - Si es modificar: usa modificar_cita_tool (PASA EL email: {email_usuario}).
        - Si es consultar agenda: usa consultar_calendario_tool (PASA EL email: {email_usuario}).
        - Si es sobre el PDF: usa consultar_pdf_tool. Lee la información devuelta y responde SOLO a la pregunta específica del usuario de forma natural, directa y conversacional.''',
        expected_output='Respuesta final amigable para el usuario. Si es una consulta de PDF, sintetiza la respuesta basándote en el documento.',
        agent=gestor
    )

    # 4. CREACIÓN DEL CREW
    equipo_citas = Crew(
        agents=[analista, gestor],
        tasks=[tarea_analisis, tarea_ejecucion],
        process=Process.sequential 
    )

    resultado = equipo_citas.kickoff()
    
    return str(resultado.raw) if hasattr(resultado, 'raw') else str(resultado)