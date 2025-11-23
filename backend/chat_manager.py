from backend.db import execute_query, query_all, get_user_by_email
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_ollama import OllamaLLM
import os
import dateparser
from datetime import datetime


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

        # PROMPT CORRECTO Y ESTRICTO
        self.prompt_template = ChatPromptTemplate.from_messages([
            (
            "system",
            "Eres un asistente especializado en gestionar citas médicas. "
            "Puedes: crear, consultar, modificar y cancelar citas.\n\n"

            "========================================================\n"
            "🎯 ACCIONES QUE PUEDES REALIZAR\n"
            "========================================================\n"
            "1) CREAR cita\n"
            "2) CONSULTAR citas del usuario\n"
            "3) MODIFICAR una cita existente\n"
            "4) CANCELAR una cita\n\n"

            "========================================================\n"
            "📌 1. CREAR CITA (lógica anterior)\n"
            "========================================================\n"
            "Debes obtener estos campos:\n"
            "- nombre\n- email\n- servicio\n- fecha_iso\n- hora_iso\n- observaciones\n\n"

            "⚠️ Reglas importantes:\n"
            "1. Si el sistema añade una línea como:\n"
            "[interpreta fecha=YYYY-MM-DD hora=HH:MM]\n"
            "→ DEBES usar esos valores directamente.\n\n"

            "2. Si el sistema añade:\n"
            "[email_usuario_logueado=EMAIL]\n"
            "→ Usa ese email si el usuario no da uno.\n\n"

            "3. Si el sistema añade:\n"
            "[nombre_usuario_logueado=NOMBRE]\n"
            "→ Usa ese nombre automáticamente.\n\n"

            "4. Pregunta solo por los datos que falten.\n"
            "5. NO muestres al usuario las líneas del sistema.\n"
            "6. Cuando el usuario diga 'sí', 'vale', 'correcto', genera el JSON final.\n"
            "7. Tu respuesta debe ser breve.\n\n"

            "Formato JSON final para CREAR cita:\n"
            "```json\n"
            "{{\"action\":\"create\",\"nombre\":\"...\",\"email\":\"...\",\"servicio\":\"...\","
            "\"fecha_iso\":\"YYYY-MM-DD\",\"hora_iso\":\"HH:MM\",\"observaciones\":\"\",\"confianza\":0.95}}\n"
            "```\n\n"

            "========================================================\n"
            "📌 2. CONSULTAR CITAS\n"
            "========================================================\n"
            "Si el usuario pregunta por sus citas (ej: 'qué citas tengo', 'mis citas de esta semana'), "
            "NO crees una cita nueva.\n\n"

            "Debes responder con un JSON de acción:\n"
            "```json\n"
            "{{\"action\":\"consult\",\"filtro\":\"texto original del usuario\"}}\n"
            "```\n\n"

            "========================================================\n"
            "📌 3. MODIFICAR CITA\n"
            "========================================================\n"
            "Cuando el usuario diga algo como: 'cambia mi cita del martes a las 12', "
            "DEBES interpretar la fecha/hora y generar:\n\n"

            "```json\n"
            "{{\"action\":\"modify\",\"nueva_fecha\":\"YYYY-MM-DD\",\"nueva_hora\":\"HH:MM\",\"filtro\":\"lo que dijo el usuario\"}}\n"
            "```\n\n"

            "========================================================\n"
            "📌 4. CANCELAR CITA\n"
            "========================================================\n"
            "Cuando el usuario diga: 'elimina mi cita', 'cancela la del dentista', 'borra mi cita del viernes', "
            "DEBES generar:\n\n"

            "```json\n"
            "{{\"action\":\"cancel\",\"filtro\":\"texto original del usuario\"}}\n"
            "```\n\n"

            "========================================================\n"
            "🏁 REGLA FINAL\n"
            "========================================================\n"
            "Tu respuesta SIEMPRE debe terminar con un bloque JSON válido. "
            "Nada más fuera del bloque JSON aparte del texto normal."
        ),
            MessagesPlaceholder(variable_name="chat_history"),
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

    def ask(self, user_input: str) -> str:
        processed = self.preprocess_input(user_input)

        # email del usuario de BD
        user_row = get_user_by_email(os.getenv("CURRENT_USER_EMAIL", ""))
        
        if user_row and user_row["email"]:
            processed += f"\n[email_usuario_logueado={user_row['email']}]"
        
        if user_row and user_row.get("nombre"):
            processed += f"\n[nombre_usuario_logueado={user_row['nombre']}]"

        # historial
        history = self.get_memory()

        # construir prompt
        prompt = self.prompt_template.format_prompt(
            chat_history=history,
            input=processed
        )

        # responder
        try:
            bot_resp = self.llm.invoke(prompt.to_string())
        except Exception as e:
            bot_resp = f"⚠️ Error con el modelo: {e}"

        # guardar
        self.save_memory(user_input, bot_resp)

        return bot_resp

    # reset
    def reset_memory(self):
        execute_query(
            "DELETE FROM memoria_chat WHERE usuario_id = ?",
            (self.usuario_id,)
        )