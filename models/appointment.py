# Appointment.py
from dataclasses import dataclass, asdict
from typing import Optional
from datetime import datetime

@dataclass
class Appointment:
    id: Optional[int] = None
    nombre: Optional[str] = None
    email: Optional[str] = None
    servicio: Optional[str] = None
    fecha_texto: Optional[str] = None
    fecha_iso: Optional[str] = None       # YYYY-MM-DD
    hora_texto: Optional[str] = None
    hora_iso: Optional[str] = None        # HH:MM
    observaciones: Optional[str] = None
    confianza: float = 0.0
    gcal_event_id: Optional[str] = None
    created_at: str = datetime.utcnow().isoformat()

    def to_dict(self):
        return asdict(self)