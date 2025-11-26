from backend.db import execute_query, query_all, get_user_by_email
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_ollama import OllamaLLM
import os
import dateparser
from datetime import datetime
import re


class ChatManagerDB:
    """
    ChatManager para agendar citas:
    - Pregunta solo lo necesario
    - Interpreta fechas como 'mañana'
    - Usa email del usuario logueado
    - Genera JSON final solo cuando todo está completo
    """

    def __init__(self, usuario_id: str, provider='ollama', model_name=None, api_key=None):
        self.usuario_id = usuario_id
        self.provider = provider.lower()
        self.api_key = api_key
        self.model_name = model_name or "llama3.2:1b"

        self.prompt_template = ChatPromptTemplate.from_messages([
            (
            "system",
            "Eres un asistente especializado en gestionar citas médicas. "
            "Cada mensaje del usuario debe producir UNA ÚNICA acción.\n\n"

            "========================================================\n"
            "🎯 ACCIONES DISPONIBLES\n"
            "========================================================\n"
            "1) CREAR cita\n"
            "2) CONSULTAR citas del usuario\n"
            "3) MODIFICAR una cita existente\n"
            "4) CANCELAR una cita\n\n"

            "========================================================\n"
            "📌 VARIABLES DEL SISTEMA QUE PUEDES RECIBIR\n"
            "========================================================\n"
            "El sistema puede añadir líneas como:\n"
            "[interpreta fecha=YYYY-MM-DD hora=HH:MM]\n"
            "[email_usuario_logueado=EMAIL]\n"
            "[nombre_usuario_logueado=NOMBRE]\n\n"
            "Reglas:\n"
            "✔️ Debes usar esos valores directamente\n"
            "✔️ NO los muestres al usuario\n"
            "✔️ Si hay email_usuario_logueado, úsalo siempre\n"
            "✔️ Si hay nombre_usuario_logueado, úsalo siempre\n\n"

            "========================================================\n"
            "📌 1. CREAR CITA\n"
            "========================================================\n"
            "Debes recolectar:\n"
            "- nombre\n- email\n- servicio\n- fecha_iso\n- hora_iso\n- observaciones\n\n"
            "Preguntar SOLO por lo que falte. Respuestas breves.\n\n"
            "Formato JSON final al crear:\n"
            "```json\n"
            "{{\"action\":\"create\",\"nombre\":\"...\",\"email\":\"...\",\"servicio\":\"...\","
            "\"fecha_iso\":\"YYYY-MM-DD\",\"hora_iso\":\"HH:MM\",\"observaciones\":\"\",\"confianza\":0.95}}\n"
            "```\n\n"

            "========================================================\n"
            "📌 2. CONSULTAR CITAS\n"
            "========================================================\n"
            "Cuando el usuario pregunte cosas como:\n"
            "- \"¿Qué citas tengo?\"\n"
            "- \"Mis citas del viernes\"\n"
            "- \"Qué tengo programado\"\n\n"
            "SIEMPRE devuelve:\n"
            "```json\n"
            "{{\"action\":\"consult\",\"filtro\":\"<email_usuario_logueado>\"}}\n"
            "```\n"
            "Nunca uses el texto original como filtro. SOLO el email.\n\n"

            "========================================================\n"
            "📌 3. MODIFICAR CITA\n"
            "========================================================\n"
            "Ejemplos:\n"
            "- \"Cambia mi cita del lunes a las 12\"\n"
            "- \"Mueve mi dentista al jueves\"\n\n"
            "Responde con:\n"
            "```json\n"
            "{{\"action\":\"modify\",\"nueva_fecha\":\"YYYY-MM-DD\",\"nueva_hora\":\"HH:MM\","
            "\"filtro\":\"<email_usuario_logueado>\"}}\n"
            "```\n"

            "========================================================\n"
            "📌 4. CANCELAR CITA\n"
            "========================================================\n"
            "Ejemplos:\n"
            "- \"Cancela mi cita del dentista\"\n"
            "- \"Elimina mi cita de mañana\"\n\n"
            "Responde con:\n"
            "```json\n"
            "{{\"action\":\"cancel\",\"filtro\":\"<email_usuario_logueado>\"}}\n"
            "```\n"

            "========================================================\n"
            "🏁 REGLA FINAL OBLIGATORIA\n"
            "========================================================\n"
            "Tu respuesta SIEMPRE debe terminar con UN SOLO bloque JSON válido.\n"
            "No muestres nada más fuera de ese JSON.\n"
            "No dupliques acciones.\n"
            "No mezcles con interacciones previas.\n"
            ),
            ("human", "{input}")
        ])


        # MODELO
        if self.provider == "ollama":
            self.llm = OllamaLLM(model=self.model_name)
        elif self.provider == "groq":
            from groq import Groq
            self.llm = Groq(model=self.model_name, groq_api_key=self.api_key)
        else:
            raise ValueError("Proveedor no válido")

    # ---------------- MEMORIA -----------------

    def get_memory(self):
        rows = query_all(
            "SELECT mensaje_usuario, respuesta_bot FROM memoria_chat WHERE usuario_id = ? ORDER BY id_memoria ASC",
            (self.usuario_id,)
        )
        hist = []
        for r in rows:
            hist.append({"role": "human", "content": r["mensaje_usuario"]})
            hist.append({"role": "ai", "content": r["respuesta_bot"]})
        return hist

    def save_memory(self, user_msg, bot_msg):
        execute_query(
            "INSERT INTO memoria_chat (usuario_id, fecha, mensaje_usuario, respuesta_bot, contexto) "
            "VALUES (?, datetime('now'), ?, ?, ?)",
            (self.usuario_id, user_msg, bot_msg, "")
        )

    # ----------- PREPROCESO DE TEXTO -------------

    def preprocess_input(self, text: str) -> str:
        now = datetime.now()

        # 1) Primero detectamos formato dd-mm-yyyy
        match = re.search(r'(\d{2})-(\d{2})-(\d{4})', text)
        if match:
            d, m, y = match.groups()
            fecha = f"{y}-{m}-{d}" 

            # detectar hora si existe
            hour_match = re.search(r'(\d{1,2}:\d{2})', text)
            hora = hour_match.group(1) if hour_match else "09:00"

            return text + f"\n[interpreta fecha={fecha} hora={hora}]"

        # 2) Si no coincide, usar dateparser normal
        parsed = dateparser.parse(
            text,
            languages=["es"],
            settings={
                "RELATIVE_BASE": now,
                "PREFER_DATES_FROM": "future",
                "PREFER_DAY_OF_MONTH": "current"
            }
        )

        if parsed:
            fecha = parsed.strftime("%Y-%m-%d")
            hora = parsed.strftime("%H:%M")
            return text + f"\n[interpreta fecha={fecha} hora={hora}]"

        return text

    # ---------------- INTERACCIÓN -----------------

    def ask(self, user_input: str):
        processed = self.preprocess_input(user_input)

        # AÑADIR email y nombre del usuario
        user_row = get_user_by_email(os.getenv("CURRENT_USER_EMAIL", ""))
        
        if user_row and user_row["email"]:
            processed += f"\n[email_usuario_logueado={user_row['email']}]"
            
        if user_row and user_row.get("nombre"):
            processed += f"\n[nombre_usuario_logueado={user_row['nombre']}]"

        prompt = self.prompt_template.format_prompt(chat_history=[], input=processed)

        bot_resp = self.llm.invoke(prompt.to_string())

        self.save_memory(user_input, bot_resp)

        return bot_resp

    def reset_memory(self):
        execute_query(
            "DELETE FROM memoria_chat WHERE usuario_id = ?",
            (self.usuario_id,)
        )