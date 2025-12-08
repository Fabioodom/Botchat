# chat_manager.py
from backend.db import execute_query, query_all, get_user_by_email
# Importaciones para manejar el historial de chat de forma correcta
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_ollama import OllamaLLM
import os
import dateparser
from datetime import datetime
import re
import json
import streamlit as st
# Asumimos que esta función está en tu backend (agent_rulebased.py)
from backend.agent_rulebased import extract_json_block


class ChatManagerDB:
    """
    ChatManager para agendar citas:
    - Pregunta solo lo necesario
    - Interpreta fechas como 'mañana'
    - Usa email del usuario logueado
    - Genera JSON final solo cuando todo está completo
    - Implementa memoria limpia para evitar repetición de acciones
    """

    def __init__(self, usuario_id: str, provider='ollama', model_name=None, api_key=None):
        self.usuario_id = usuario_id
        self.provider = provider.lower()
        self.api_key = api_key
        self.model_name = model_name or "llama3.2:1b"

        # =========================================================
        # SYSTEM PROMPT COMPLETO
        # =========================================================
        self.prompt_template = ChatPromptTemplate.from_messages([
            (
                "system",
                """
                Eres un asistente especializado en gestionar citas y eventos para el usuario (reuniones, exámenes, entrevistas, médicos, fiestas, etc.). Tu función es:            
                - Hacer UNA pregunta corta cuando falte información
                - O devolver UN JSON cuando tengas todos los datos
               
                =======================================================================
                📌 REGLAS ABSOLUTAS
                =======================================================================
                1. NUNCA escribas código, ejemplos de programación, ni explicaciones técnicas
                2. NUNCA menciones "estado_cita_en_progreso" al usuario
                3. NUNCA hagas menús de opciones
                4. NUNCA preguntes por datos que ya tienes en el estado
                5. Tu respuesta SOLO puede ser:
                   A) Una pregunta corta (sin JSON)
                   B) Un bloque JSON (sin texto adicional)
                6. Antes de decidir qué preguntar, SIEMPRE debes leer [estado_cita_en_progreso=...].
                   Si en ese estado ya existe "servicio", "fecha_iso" o "hora_iso", NO debes volver a preguntar por esos campos.

                =======================================================================
                📌 CONTEXTO DESDE PDF
                =======================================================================
                El usuario puede haber subido un PDF. El texto relevante del PDF se pasa en la variable {{pdf_text}}.

                ➜ MODO NORMAL (sin PDF)
                - Si {{pdf_text}} está vacío, ignóralo por completo.
                - Actúa solo con lo que diga el usuario en el chat y el estado_cita_en_progreso.

                ➜ MODO PDF
                - Si el usuario dice cosas como:
                  "usa el pdf", "usar el pdf", "saca los datos del pdf",
                  "crea la cita con los datos del documento", "del pdf", etc.
                  ENTONCES:
                  - Debes LEER el CONTEXTO DEL PDF (entre las marcas de inicio y fin).
                  - Extraer de ahí NOMBRE, EMAIL, SERVICIO, FECHA y HORA si están presentes.
                  - Devolver directamente el JSON completo de la cita, sin hacer más preguntas,
                    siempre que tengas todos los campos necesarios.

                ====== INICIO CONTEXTO PDF ======
                {{pdf_text}}
                ====== FIN CONTEXTO PDF ======

                =======================================================================
                📌 DETECCIÓN DE ACCIÓN
                =======================================================================
                Según las palabras del usuario:

                "agendar", "programa", "quiero una cita", "ponme" → action = "create"
                "qué citas tengo", "ver mis citas", "consultar" → action = "consult"
                "cancela", "anula", "borra", "elimina" → action = "cancel"
                "cambia", "modifica", "reprograma", "mueve" → action = "modify"

                =======================================================================
                📌 ESTADO ACTUAL
                =======================================================================
                Recibirás una línea así:
                [estado_cita_en_progreso={{"nombre":"...", "email":"...", "servicio":"...", "fecha_iso":"...", "hora_iso":"..."}}]

                REGLA CRÍTICA:
                - Si un campo YA tiene valor en estado_cita_en_progreso → NO preguntes por él
                - Si "servicio" existe → NO preguntes "¿Qué servicio necesitas?"
                - Si "fecha_iso" existe → NO preguntes "¿Para qué día?"
                - Si "hora_iso" existe → NO preguntes "¿A qué hora?"

                =======================================================================
                📌 CREAR CITA (action = "create")
                =======================================================================
                Necesitas: nombre, email, servicio, fecha_iso, hora_iso

                Si TODOS están completos → devuelve SOLO este JSON:
                {{
                  "action": "create",
                  "nombre": "NOMBRE",
                  "email": "EMAIL",
                  "servicio": "SERVICIO",
                  "fecha_iso": "YYYY-MM-DD",
                  "hora_iso": "HH:MM",
                  "observaciones": "",
                  "confianza": 0.95
                }}

                Si falta algo → pregunta SOLO por lo que falta:
                - Falta servicio: "¿Qué tipo de cita o evento necesitas?"
                - Falta fecha: "¿Para qué día?"
                - Falta hora: "¿A qué hora?"

                =======================================================================
                📌 CONSULTAR CITAS (action = "consult")
                =========================================================================
                Si el usuario pregunta por SUS citas con frases como:
                - "qué citas tengo"
                - "ver mis citas"
                - "mis citas"
                - "consultar citas"

                ENTONCES:
                - NO hagas preguntas largas
                - NO pidas más confirmaciones
                - Simplemente devuelve:
                {{
                  "action": "consult",
                  "filtro": "EMAIL_USUARIO"
                }}

                donde EMAIL_USUARIO es el email del usuario logueado que recibes en el contexto
                [email_usuario_logueado=...].

                Solo si NO tienes ningún email en estado ni en el contexto, puedes hacer
                UNA pregunta corta: "¿Cuál es tu email para buscar tus citas?"

                =======================================================================
                📌 CANCELAR CITA (action = "cancel")
                =======================================================================
                Si el usuario menciona una fecha o servicio, devuelve:
                {{
                  "action": "cancel",
                  "filtro": "FECHA_O_TEXTO"
                }}

                Si no especifica nada, pregunta: "¿Qué cita deseas cancelar? (indica fecha o servicio)"

                =======================================================================
                📌 MODIFICAR CITA (action = "modify")
                =======================================================================
                Necesitas: filtro (cita a modificar), nueva_fecha, nueva_hora

                Si el usuario da todo ("Cambia mi cita del 10/12 a las 11:30"), devuelve:
                {{
                  "action": "modify",
                  "filtro": "10/12/2025",
                  "nueva_fecha": "2025-12-10",
                  "nueva_hora": "11:30"
                }}

                Si falta algo, pregunta solo por eso.

                =======================================================================
                📌 EJEMPLOS CORRECTOS
                =======================================================================
                Usuario: "Quiero una reunión con mi jefe"
                Estado: {{"servicio": "reunión con mi jefe", "fecha_iso": null, "hora_iso": null}}
                Bot: "¿Para qué día?"

                Usuario: "Mañana"
                Estado: {{"servicio": "reunión con mi jefe", "fecha_iso": "2025-12-10", "hora_iso": null}}
                Bot: "¿A qué hora?"

                Usuario: "A las 10"
                Estado: {{"servicio": "reunión con mi jefe", "fecha_iso": "2025-12-10", "hora_iso": "10:00"}}
                Bot: [JSON COMPLETO]

                Usuario: "Cancela mi cita del 10/12/2025"
                Bot: {{"action": "cancel", "filtro": "10/12/2025"}}

                =======================================================================
                📌 EJEMPLOS INCORRECTOS (PROHIBIDO)
                =======================================================================
                ❌ Usuario: "Quiero una cita de médico"
                   Bot: "¿Qué servicio necesitas?" (YA LO DIJO)

                ❌ Bot: "Puedes elegir entre: agendar, consultar, cancelar..." (MENÚ)

                ❌ Bot: "Antes de empezar, quiero asegurarme..." (EXPLICACIÓN)

                ❌ Bot: "¿Quieres que genere el JSON?" (PREGUNTA INNECESARIA)
                """
            ),

            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}")
        ])

        # MODELO
        if self.provider == "ollama":
            from langchain_ollama import OllamaLLM
            self.llm = OllamaLLM(
                model=self.model_name,
                temperature=0.2,
                top_p=0.9
            )

        elif self.provider == "groq":
            from groq import Groq
            if not self.api_key:
                raise ValueError("❌ Falta GROQ_API_KEY para usar Groq")
            self.groq_client = Groq(api_key=self.api_key)
            self.llm = None  # No usamos LangChain para Groq
        else:
            raise ValueError("Proveedor de LLM no válido. Use 'ollama' o 'groq'.")

    # ============================================================
    # MÉTODOS DE ESTADO
    # ============================================================
    def init_conversation_state(self):
        if "conversation_state" not in st.session_state:
            st.session_state.conversation_state = {
                "action": None,
                "nombre": None,
                "email": None,
                "servicio": None,
                "fecha_iso": None,
                "hora_iso": None,
                "observaciones": ""
            }

    def update_conversation_state(self, data: dict):
        """Actualiza solo los campos que el LLM haya devuelto."""
        self.init_conversation_state()
        for key, value in data.items():
            if value not in [None, "", "null"]:
                st.session_state.conversation_state[key] = value

    def reset_conversation_state(self):
        """Reinicia completamente el estado."""
        st.session_state.conversation_state = {
            "action": None,
            "nombre": None,
            "email": None,
            "servicio": None,
            "fecha_iso": None,
            "hora_iso": None,
            "observaciones": ""
        }

    def reset_memory(self):
        """Limpia el historial de la DB (útil para el botón de Streamlit)."""
        execute_query("DELETE FROM memoria_chat WHERE usuario_id = ?", (self.usuario_id,))

    # ============================================================
    # 🧠 MEMORIA LIMPIA
    # ============================================================

    def _clean_bot_response(self, bot_resp: str) -> str:
        """Extrae el texto que NO es un bloque JSON para la memoria."""
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', bot_resp, re.DOTALL)
        if json_match:
            # Reemplaza el bloque JSON con una cadena vacía
            cleaned = bot_resp[:json_match.start()] + bot_resp[json_match.end():]
            return cleaned.strip()
        return bot_resp.strip()

    def get_memory(self):
        """Carga el historial y lo limpia de bloques JSON."""
        rows = query_all(
            "SELECT mensaje_usuario, respuesta_bot FROM memoria_chat WHERE usuario_id = ? ORDER BY id_memoria ASC",
            (self.usuario_id,)
        )
        hist = []
        for r in rows:
            bot_msg_limpio = self._clean_bot_response(r["respuesta_bot"])
            if bot_msg_limpio:
                hist.append(HumanMessage(content=r["mensaje_usuario"]))
                hist.append(AIMessage(content=bot_msg_limpio))
        return hist

    def save_memory(self, user_msg, bot_msg):
        execute_query(
            "INSERT INTO memoria_chat (usuario_id, fecha, mensaje_usuario, respuesta_bot, contexto) "
            "VALUES (?, datetime('now'), ?, ?, ?)",
            (self.usuario_id, user_msg, bot_msg, "")
        )

    # ============================================================
    # 🔎 PARSEO DE FECHAS
    # ============================================================

    def preprocess_input(self, text: str):
        """
        Devuelve:
        - processed_text: texto original + (opcional) tag [interpreta fecha=... hora=...]
        - fecha_iso: str | None
        - hora_iso: str | None
        """
        now = datetime.now()
        fecha_iso = None
        hora_iso = None

        # 1. Detectar formato dd/mm/yyyy o dd-mm-yyyy
        match = re.search(r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})', text)
        if match:
            d, m, y = match.groups()
            fecha_iso = f"{y}-{m.zfill(2)}-{d.zfill(2)}"

        # 2. Detectar hora explícita (HH:MM)
        hour_match = re.search(r'(\d{1,2}):(\d{2})', text)
        if hour_match:
            hora_iso = f"{hour_match.group(1).zfill(2)}:{hour_match.group(2)}"

        # 3. Si no hay fecha explícita, usar dateparser para expresiones como "mañana"
        if not fecha_iso:
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
                fecha_iso = parsed.strftime("%Y-%m-%d")
                # Si también extrajo hora distinta de 00:00, usarla
                if not hora_iso and (parsed.hour != 0 or parsed.minute != 0):
                    hora_iso = parsed.strftime("%H:%M")

        processed = text
        if fecha_iso and hora_iso:
            processed += f"\n[interpreta fecha={fecha_iso} hora={hora_iso}]"
        elif fecha_iso:
            processed += f"\n[interpreta fecha={fecha_iso}]"

        return processed, fecha_iso, hora_iso

    # ============================================================
    # 💬 MÉTODO PRINCIPAL
    # ============================================================
    def ask(self, user_input: str):
        """
        Lógica principal de conversación:
        - Prioriza reglas deterministas para create/consult/cancel/modify
        - Solo usa el LLM como último recurso cuando no se puede inferir nada claro
        """

        # 1) Parseo de fecha y hora (posible nueva fecha/hora para create/modify)
        processed, fecha_iso, hora_iso = self.preprocess_input(user_input)
        texto_usuario_lower = user_input.lower().strip()

        usa_pdf = any(p in texto_usuario_lower for p in [
            "usar el pdf", "usa el pdf", "según el pdf", "segun el pdf", "del pdf", "del documento"
        ])

        # 2) Inicializar estado
        self.init_conversation_state()
        state = st.session_state.conversation_state

        # 3) Actualizar estado con fecha/hora si se extrajeron
        if fecha_iso and not state.get("fecha_iso"):
            state["fecha_iso"] = fecha_iso
        if hora_iso and not state.get("hora_iso"):
            state["hora_iso"] = hora_iso

        # 4) Intentar extraer servicio del texto (para create)
        servicio = None
        servicios_map = {
            "médico de cabecera": ["médico de cabecera", "medico de cabecera", "cabecera"],
            "médico": ["médico", "medico", "doctor"],
            "dermatología": ["dermatólogo", "dermatologia", "dermatologo"],
            "cardiología": ["cardiólogo", "cardiologia", "cardiologo"],
            "fisioterapia": ["fisioterapia", "fisioterapeuta"],
            "ginecología": ["ginecología", "ginecologo", "ginecologia"],
            "traumatología": ["traumatología", "traumatologo", "traumatologia", "trauma"],
            "pediatría": ["pediatría", "pediatra", "pediatria"],
            "reunión": ["reunión", "reunion", "junta"],
            "entrevista": ["entrevista"],
            "examen": ["examen", "prueba", "test"],
            "fiesta": ["fiesta", "celebración", "celebracion"],
            "mecánico": ["mecanico", "mecánico", "taller"]
        }

        for servicio_normalizado, patrones in servicios_map.items():
            for patron in patrones:
                if patron in texto_usuario_lower:
                    servicio = servicio_normalizado
                    break
            if servicio:
                break

        if not servicio:
            # Buscar patrones como "cita de X", "reunión de X", etc.
            match_servicio = re.search(
                r'(?:cita|reunion|reunión|evento)\s+(?:de|con|para)\s+([a-záéíóúñ\s]+?)(?:\s+para|\s+el|\s+mañana|$)',
                texto_usuario_lower
            )
            if match_servicio:
                servicio = match_servicio.group(1).strip()

        if servicio and not state.get("servicio"):
            state["servicio"] = servicio

        # 5) Datos del usuario actual (email + nombre)
        current_email_env = os.getenv("CURRENT_USER_EMAIL", "")
        user_row = get_user_by_email(current_email_env) if current_email_env else None

        if user_row:
            processed += f"\n[email_usuario_logueado={user_row['email']}]"
            processed += f"\n[nombre_usuario_logueado={user_row['nombre']}]"
            if not state.get("nombre"):
                state["nombre"] = user_row["nombre"]
            if not state.get("email"):
                state["email"] = user_row["email"]

        # =====================================================
        # A) DETECCIÓN DE INTENCIÓN POR PALABRAS CLAVE
        # =====================================================
        quiere_consultar = any(p in texto_usuario_lower for p in [
            "qué citas tengo", "que citas tengo", "ver mis citas", "mis citas", "consultar citas"
        ])
        quiere_cancelar = any(p in texto_usuario_lower for p in [
            "cancela", "anula", "elimina", "borra"
        ])
        quiere_modificar = any(p in texto_usuario_lower for p in [
            "cambia", "modifica", "reprograma", "mueve"
        ])
        quiere_crear = (
            any(p in texto_usuario_lower for p in [
                "agendame", "agéndame", "agenda", "agendar", "ponme una cita",
                "quiero una cita", "reserva una cita", "programa una cita"
            ])
            or "cita" in texto_usuario_lower
            or "reunión" in texto_usuario_lower
            or "reunion" in texto_usuario_lower
        )

        # 🔁 NUEVO: si ya hay datos de cita en el estado, seguimos en modo "create"
        tiene_estado_creacion = any(
            state.get(k) for k in ("servicio", "fecha_iso", "hora_iso", "nombre", "email")
        )
        if tiene_estado_creacion and not (quiere_consultar or quiere_cancelar or quiere_modificar):
            quiere_crear = True

        # =====================================================
        # B) CONSULT: "ver mis citas", etc. (SIN LLM)
        # =====================================================
        if quiere_consultar:
            filtro_email = None
            if user_row and user_row.get("email"):
                filtro_email = user_row["email"]
            elif state.get("email"):
                filtro_email = state["email"]

            if filtro_email:
                bot_resp = (
                    "```json\n"
                    "{\n"
                    '  "action": "consult",\n'
                    f'  "filtro": "{filtro_email}"\n'
                    "}\n"
                    "```"
                )
                self.save_memory(user_input, bot_resp)
                return bot_resp
            else:
                bot_resp = "¿Cuál es tu email para buscar tus citas?"
                self.save_memory(user_input, bot_resp)
                return bot_resp

        # =====================================================
        # C) MODIFY: "cambia mi cita del ... a las ..." (SIN LLM si se puede)
        # =====================================================
        if quiere_modificar:
            # Fecha de la cita que EXISTE (la original a modificar)
            filtro_fecha = None
            m1 = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", user_input)
            m2 = re.search(r"(\d{4})-(\d{2})-(\d{2})", user_input)
            if m1:
                d, m, y = m1.groups()
                filtro_fecha = f"{y}-{m.zfill(2)}-{d.zfill(2)}"
            elif m2:
                y, m, d = m2.groups()
                filtro_fecha = f"{y}-{m}-{d}"

            nueva_fecha = fecha_iso
            nueva_hora = hora_iso

            # Caso ideal: usuario da todo en una frase
            if filtro_fecha and nueva_fecha and nueva_hora:
                bot_resp = (
                    "```json\n"
                    "{\n"
                    '  "action": "modify",\n'
                    f'  "filtro": "{filtro_fecha}",\n'
                    f'  "nueva_fecha": "{nueva_fecha}",\n'
                    f'  "nueva_hora": "{nueva_hora}"\n'
                    "}\n"
                    "```"
                )
                self.save_memory(user_input, bot_resp)
                return bot_resp

            # Faltan datos → preguntar lo mínimo, SIN LLM
            if not filtro_fecha:
                bot_resp = "¿De qué fecha es la cita que quieres cambiar?"
                self.save_memory(user_input, bot_resp)
                return bot_resp

            if not nueva_fecha or not nueva_hora:
                bot_resp = "¿A qué nueva fecha y hora quieres mover la cita?"
                self.save_memory(user_input, bot_resp)
                return bot_resp

        # =====================================================
        # D) CANCEL: "cancela mi cita del ..." (SIN LLM si se puede)
        # =====================================================
        if quiere_cancelar:
            filtro = None
            m1 = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", user_input)
            m2 = re.search(r"(\d{4})-(\d{2})-(\d{2})", user_input)
            if m1:
                d, m, y = m1.groups()
                filtro = f"{y}-{m.zfill(2)}-{d.zfill(2)}"
            elif m2:
                y, m, d = m2.groups()
                filtro = f"{y}-{m}-{d}"

            if filtro:
                bot_resp = (
                    "```json\n"
                    "{\n"
                    '  "action": "cancel",\n'
                    f'  "filtro": "{filtro}"\n'
                    "}\n"
                    "```"
                )
                self.save_memory(user_input, bot_resp)
                return bot_resp
            else:
                bot_resp = "¿Qué cita deseas cancelar? (indica fecha o servicio)"
                self.save_memory(user_input, bot_resp)
                return bot_resp

        # =====================================================
        # E) CREATE: flujo guiado multi-turno (SIN LLM si se puede)
        # =====================================================
        if quiere_crear:
            nombre = state.get("nombre")
            email = state.get("email")
            servicio_state = state.get("servicio")
            fecha_state = state.get("fecha_iso")
            hora_state = state.get("hora_iso")

            # Caso 1: TODO completo → JSON create
            if nombre and email and servicio_state and fecha_state and hora_state:
                bot_resp = (
                    "```json\n"
                    "{\n"
                    '  "action": "create",\n'
                    f'  "nombre": "{nombre}",\n'
                    f'  "email": "{email}",\n'
                    f'  "servicio": "{servicio_state}",\n'
                    f'  "fecha_iso": "{fecha_state}",\n'
                    f'  "hora_iso": "{hora_state}",\n'
                    f'  "observaciones": "{state.get("observaciones", "")}",\n'
                    '  "confianza": 0.95\n'
                    "}\n"
                    "```"
                )
                self.save_memory(user_input, bot_resp)
                self.reset_conversation_state()
                return bot_resp

            # Caso 2: tenemos fecha y hora, falta servicio
            if fecha_state and hora_state and not servicio_state:
                bot_resp = f"¿Qué tipo de cita o evento necesitas para el {fecha_state} a las {hora_state}?"
                self.save_memory(user_input, bot_resp)
                return bot_resp

            # Caso 3: tenemos fecha, no hora
            if fecha_state and not hora_state:
                bot_resp = f"¿A qué hora quieres la cita del {fecha_state}?"
                self.save_memory(user_input, bot_resp)
                return bot_resp

            # Caso 4: no tenemos fecha
            if not fecha_state:
                bot_resp = "¿Para qué día quieres la cita?"
                self.save_memory(user_input, bot_resp)
                return bot_resp

            # Caso 5: como fallback, si solo falta servicio
            if not servicio_state:
                bot_resp = "¿Qué tipo de cita o evento necesitas?"
                self.save_memory(user_input, bot_resp)
                return bot_resp

        # =====================================================
        # F0) NUEVO: si el estado YA está completo para crear, devolvemos JSON
        #      sin pasar por el LLM (evita bucles de “¿Qué tipo de cita…?”)
        # =====================================================
        nombre = state.get("nombre")
        email = state.get("email")
        servicio_state = state.get("servicio")
        fecha_state = state.get("fecha_iso")
        hora_state = state.get("hora_iso")

        if nombre and email and servicio_state and fecha_state and hora_state:
            bot_resp = (
                "```json\n"
                "{\n"
                '  "action": "create",\n'
                f'  "nombre": "{nombre}",\n'
                f'  "email": "{email}",\n'
                f'  "servicio": "{servicio_state}",\n'
                f'  "fecha_iso": "{fecha_state}",\n'
                f'  "hora_iso": "{hora_state}",\n'
                f'  "observaciones": "{state.get("observaciones", "")}",\n'
                '  "confianza": 0.95\n'
                "}\n"
                "```"
            )
            self.save_memory(user_input, bot_resp)
            self.reset_conversation_state()
            return bot_resp

        # =====================================================
        # F) Si no hemos podido determinar nada → usar LLM
        # =====================================================

        state_json = json.dumps(state, ensure_ascii=False)
        processed += f"\n[estado_cita_en_progreso={state_json}]"

        history = self.get_memory()

        pdf_text = st.session_state.get("pdf_text", "") or ""
        if usa_pdf:
            pdf_text = pdf_text[:4000]  # recorte por seguridad
        else:
            # Si no ha pedido usar el PDF, no metas el texto para no distraer al modelo
            pdf_text = ""

        prompt = self.prompt_template.format_prompt(
            chat_history=history,
            input=processed,
            pdf_text=pdf_text,
        )

        try:
            if self.provider == "ollama":
                bot_resp_messages = self.llm.invoke(prompt.to_messages())
                bot_resp = bot_resp_messages.content if hasattr(bot_resp_messages, 'content') else str(bot_resp_messages)
            elif self.provider == "groq":
                messages = []
                for msg in prompt.to_messages():
                    if hasattr(msg, 'type'):
                        role = "user" if msg.type == "human" else "assistant"
                        if msg.type == "system":
                            role = "system"
                        messages.append({"role": role, "content": msg.content})

                completion = self.groq_client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    temperature=0.3,
                    max_tokens=512,
                )
                bot_resp = completion.choices[0].message.content

        except Exception as e:
            bot_resp = f"❌ Error al invocar el LLM: {str(e)}"
            st.error(bot_resp)
            return bot_resp

        # Procesar respuesta del LLM (por si devuelve JSON)
        data = extract_json_block(bot_resp)
        if data:
            self.update_conversation_state(data)
            action = data.get("action", "").lower()
            is_create_complete = (
                action == "create" and
                data.get("fecha_iso") and data.get("hora_iso") and data.get("servicio")
            )
            is_modify_complete = (
                action == "modify" and
                data.get("filtro") and data.get("nueva_fecha") and data.get("nueva_hora")
            )
            is_cancel_complete = (action == "cancel" and data.get("filtro"))
            is_consult_complete = (action == "consult")

            if is_create_complete or is_modify_complete or is_cancel_complete or is_consult_complete:
                self.reset_conversation_state()

        self.save_memory(user_input, bot_resp)
        return bot_resp
