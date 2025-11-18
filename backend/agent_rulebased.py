# backend/agent_rulebased.py
import re
from datetime import datetime
from typing import Dict, Optional

ORDER = ["nombre", "email", "servicio", "fecha_texto", "hora_texto", "observaciones"]

def valid_email(s: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", (s or "").strip()))

def parse_date_iso(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except:
            pass
    # Intento salvaje: dd/mm o dd-mm con año actual
    m = re.match(r"^(\d{1,2})[/-](\d{1,2})$", s)
    if m:
        d, mth = m.groups()
        try:
            dt = datetime(datetime.now().year, int(mth), int(d))
            return dt.date().isoformat()
        except:
            return None
    return None

def parse_time_iso(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%H:%M", "%H.%M", "%H"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%H:%M")
        except:
            pass
    # Algunas cosas como "a las 5", "5 de la tarde"
    m = re.search(r"(\d{1,2})", s)
    if m:
        h = int(m.group(1))
        if 0 <= h <= 23:
            return f"{h:02d}:00"
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
    }

def next_expected(state: Dict) -> Optional[str]:
    for field in ORDER:
        if not state.get(field):
            return field
    if not state.get("fecha_iso"):
        return "fecha_texto"
    if not state.get("hora_iso"):
        return "hora_texto"
    return None

def prompt_for(state: Dict) -> str:
    missing = next_expected(state)
    if missing == "nombre":
        return "¿Cómo te llamas?"
    if missing == "email":
        return "¿Cuál es tu correo electrónico?"
    if missing == "servicio":
        return "¿Qué tipo de servicio necesitas (por ejemplo, corte de pelo, consulta, etc.)?"
    if missing == "fecha_texto":
        return "¿Para qué día quieres la cita? (por ejemplo, 25/12/2025)"
    if missing == "hora_texto":
        return "¿A qué hora te viene bien? (por ejemplo, 16:30)"
    if missing == "observaciones":
        return "¿Quieres añadir alguna observación o preferencia adicional? (si no, dime 'no')"
    return "Creo que ya tengo todos los datos, pero dime si quieres revisar algo."

def parse_and_update(state: Dict, user_text: str) -> Dict:
    user_text = (user_text or "").strip()
    new_state = dict(state)
    missing = next_expected(state)

    if missing == "nombre":
        new_state["nombre"] = user_text or state.get("nombre")
        return new_state

    if missing == "email":
        if valid_email(user_text):
            new_state["email"] = user_text
        else:
            # Si no es válido, no lo guardamos
            pass
        return new_state

    if missing == "servicio":
        new_state["servicio"] = user_text or state.get("servicio")
        return new_state

    if missing == "fecha_texto":
        new_state["fecha_texto"] = user_text
        iso = parse_date_iso(user_text)
        if iso:
            new_state["fecha_iso"] = iso
        return new_state

    if missing == "hora_texto":
        new_state["hora_texto"] = user_text
        iso = parse_time_iso(user_text)
        if iso:
            new_state["hora_iso"] = iso
        return new_state

    if missing == "observaciones":
        if user_text.lower() in ("no", "ninguna", "no tengo", "ninguna observación"):
            new_state["observaciones"] = ""
        else:
            new_state["observaciones"] = user_text
        return new_state

    return new_state

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
