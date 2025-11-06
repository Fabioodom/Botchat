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
