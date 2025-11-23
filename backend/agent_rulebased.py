#llm.py

'''

import os, json
from typing import List, Dict, Optional

try:
    from groq import Groq
except: Groq = None

try:
    import ollama
except: ollama = None

SYSTEM_PROMPT = """Eres un asistente de agenda que recopila datos para una CITA.
Objetivo: pedir de forma amable los datos necesarios y devolver SIEMPRE un bloque JSON al final.

Reglas:
- Pregunta SOLO por el dato que falte, de uno en uno, con una frase breve y clara.
- No repitas preguntas ya contestadas; si el usuario aporta varios datos a la vez, intégralos.
- Si tienes baja seguridad, pide confirmación. No inventes.
- Español neutro, tono profesional y cercano.

FORMATO OBLIGATORIO al final de CADA respuesta:
Incluye EXACTAMENTE un bloque de código JSON (y nada más dentro del bloque) con la forma:

```json
{
  "nombre": null | "string",
  "email": null | "string",
  "servicio": null | "string",
  "fecha_texto": null | "string",
  "fecha_iso": null | "YYYY-MM-DD",
  "hora_texto": null | "string",
  "hora_iso": null | "HH:MM",
  "observaciones": null | "string",
  "confianza": number  // 0.0 a 1.0
}
```"""

def extract_json_block(text:str)->Optional[dict]:
    if not text: return None
    s=text.rfind("```json"); e=text.rfind("```")
    if s!=-1 and e!=-1 and e>s:
        try: return json.loads(text[s+7:e].strip())
        except: pass
    try: return json.loads(text)
    except: return None

def chat_with_groq(messages:List[Dict],model:str,api_key:str)->str:
    if Groq is None: raise RuntimeError("Instala groq")
    client=Groq(api_key=api_key or os.getenv("GROQ_API_KEY"))
    resp=client.chat.completions.create(model=model,messages=messages,temperature=0.3)
    return resp.choices[0].message.content

def chat_with_ollama(messages:List[Dict],model:str)->str:
    if ollama and hasattr(ollama,"chat"):
        resp=ollama.chat(model=model,messages=messages,options={"temperature":0.3})
        return resp["message"]["content"]
    import requests
    r=requests.post("http://localhost:11434/api/chat",
        json={"model":model,"messages":messages,"stream":False})
    return r.json()["message"]["content"]

def build_llm_messages(history:List[Dict])->List[Dict]:
    return [{"role":"system","content":SYSTEM_PROMPT}] + history

'''

import re, json
def extract_json_block(text: str):    
    """Buscamos un bloque de texto JSON y lo convertimos a diccionario para acceder facilmente por clave/valor
       Si no encuentra ningun JSON que sea valido devolvera un None
    """

    if not text:
        return None
    
    match = re.search(r'```json\s*(\{[\s\S]*?\})\s*```', text)
    if not match:
        match = re.search(r'(\{[\s\S]*?\})', text)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            try:
                return json.load(match.group(0))
            except Exception:
                return None
    
    return None


# backend/agent_rulebased.py
import re
from datetime import datetime
from typing import Dict, Optional

ORDER = ["nombre", "email", "servicio", "fecha_texto", "hora_texto", "observaciones"]

def valid_email(s: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", (s or "").strip()))

def parse_date_iso(s: Optional[str]) -> Optional[str]:
    if not s: return None
    s = s.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except:
            pass
    return None

def parse_time_iso(s: Optional[str]) -> Optional[str]:
    if not s: return None
    s = s.strip().replace(".", ":")
    try:
        t = datetime.strptime(s, "%H:%M").time()
        return f"{t.hour:02d}:{t.minute:02d}"
    except:
        return None

def initial_state() -> Dict:
    return {
        "nombre": None,
        "email": None,
        "servicio": None,
        "fecha_texto": None,
        "fecha_iso": None,
        "hora_texto": None,
        "hora_iso": None,
        "observaciones": None,
        "confianza": 1.0,
        "expected": "nombre",  # campo que toca pedir ahora
    }

def next_expected(state: Dict) -> Optional[str]:
    for k in ORDER:
        if not state.get(k):
            return k
    # Si ya hay texto pero falta ISO, seguimos esperando confirmaciones implícitas
    if not state.get("fecha_iso"): return "fecha_texto"
    if not state.get("hora_iso"):  return "hora_texto"
    return None

def prompt_for(field: str) -> str:
    prompts = {
        "nombre": "¿Cuál es tu nombre completo?",
        "email": "¿Cuál es tu email para la confirmación?",
        "servicio": "¿Para qué servicio quieres la cita?",
        "fecha_texto": "¿Qué día te viene bien? (dd/mm/aaaa recomendado)",
        "hora_texto": "¿A qué hora? (HH:MM 24h, por ejemplo 17:30)",
        "observaciones": "¿Alguna observación adicional? (opcional, puedes dejarlo en blanco)",
    }
    return prompts.get(field, "¿Puedes indicarme el dato que falta?")

def parse_and_update(state: Dict, user_text: str) -> Dict:
    field = state.get("expected") or next_expected(state) or "observaciones"
    txt = (user_text or "").strip()

    if field == "nombre":
        state["nombre"] = txt if txt else None

    elif field == "email":
        state["email"] = txt if valid_email(txt) else None

    elif field == "servicio":
        state["servicio"] = txt if txt else None

    elif field == "fecha_texto":
        state["fecha_texto"] = txt if txt else None
        state["fecha_iso"] = parse_date_iso(txt)

    elif field == "hora_texto":
        state["hora_texto"] = txt if txt else None
        state["hora_iso"] = parse_time_iso(txt)

    elif field == "observaciones":
        state["observaciones"] = txt if txt else None

    # Ajusta el siguiente esperado según lo que falte
    nxt = next_expected(state)
    state["expected"] = nxt if nxt else None
    return state

def is_complete(state: Dict) -> bool:
    return all(state.get(k) for k in ["nombre","email","servicio","fecha_iso","hora_iso"])

def final_json(state: Dict) -> Dict:
    return {
        "nombre": state.get("nombre"),
        "email": state.get("email"),
        "servicio": state.get("servicio"),
        "fecha_texto": state.get("fecha_texto"),
        "fecha_iso": state.get("fecha_iso"),
        "hora_texto": state.get("hora_texto"),
        "hora_iso": state.get("hora_iso"),
        "observaciones": state.get("observaciones"),
        "confianza": 1.0,
    }
