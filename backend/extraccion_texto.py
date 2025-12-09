#Extraccion_texto.py
import re, json

from typing import Optional, Dict

def extract_json_block(text: str) -> Optional[Dict]:
    """
    Extrae el primer bloque JSON válido de un texto.
    Soporta:
    - ```json { ... } ```
    - { ... }
    """
    
    # Intentar extraer bloque con ```json
    match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    
    # Intentar extraer JSON directo
    match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    
    return None