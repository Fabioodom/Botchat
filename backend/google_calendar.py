# google_calendar.py
import os, pytz
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar"]

def _load_creds(token_path: Optional[str], creds_path: Optional[str] = None):
    creds_path = creds_path or os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
    token_path = token_path or os.getenv("GOOGLE_TOKEN_PATH", "token.json")

    creds = None
    
    # Intentar cargar credenciales existentes
    if token_path and os.path.exists(token_path):
        try:
            # Verificar que el archivo no esté vacío
            if os.path.getsize(token_path) > 0:
                creds = Credentials.from_authorized_user_file(token_path, SCOPES)
            else:
                print(f"⚠️ Token vacío en {token_path}, se regenerará")
                os.remove(token_path)
        except Exception as e:
            print(f"⚠️ Error al leer token en {token_path}: {e}")
            print(f"🔄 Eliminando token corrupto y regenerando...")
            try:
                os.remove(token_path)
            except:
                pass
            creds = None
    
    # Si no hay credenciales válidas, obtenerlas
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"⚠️ Error al refrescar token: {e}")
                print(f"🔄 Iniciando flujo de autenticación completo...")
                flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
                creds = flow.run_local_server(port=0)
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Guardar token
        if token_path:
            try:
                with open(token_path, "w", encoding="utf-8") as f:
                    f.write(creds.to_json())
                print(f"✅ Token guardado en {token_path}")
            except Exception as e:
                print(f"⚠️ Error al guardar token: {e}")
    
    return creds

def get_service(token_path: Optional[str] = None):
    creds = _load_creds(token_path)
    return build("calendar", "v3", credentials=creds)

def create_event(summary: str, date_iso: str, time_hhmm: str,
                 duration_minutes: int = 60, description: str = "",
                 attendees_emails: Optional[List[str]] = None,
                 token_path: Optional[str] = None) -> Dict:
    """
    Crea un evento y devuelve el dict de evento (incluye 'id' y 'htmlLink').
    token_path: ruta al token del usuario (para operar en SU calendario).
    """
    service = get_service(token_path)
    tz = os.getenv("TIMEZONE", "Europe/Madrid")

    start_dt = datetime.strptime(f"{date_iso} {time_hhmm}", "%Y-%m-%d %H:%M")
    end_dt = start_dt + timedelta(minutes=duration_minutes)

    start = pytz.timezone(tz).localize(start_dt).isoformat()
    end = pytz.timezone(tz).localize(end_dt).isoformat()

    event = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start, "timeZone": tz},
        "end": {"dateTime": end, "timeZone": tz},
        "reminders": {"useDefault": False, "overrides": [
            {"method": "popup", "minutes": 30}, {"method": "email", "minutes": 120}
        ]},
    }
    if attendees_emails:
        event["attendees"] = [{"email": e} for e in attendees_emails]

    cal_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")
    created = service.events().insert(calendarId=cal_id, body=event, sendUpdates="all").execute()
    return created

def get_future_events(token_path: Optional[str] = None, max_results: int = 50):
    service = get_service(token_path)
    tz = os.getenv("TIMEZONE", "Europe/Madrid")
    now = datetime.now(pytz.timezone(tz)).isoformat()
    cal_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")
    events_result = service.events().list(
        calendarId=cal_id,
        timeMin=now,
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime"
    ).execute()
    return events_result.get("items", [])

def update_event(event_id: str,
                 new_date_iso: str,
                 new_time_hhmm: str,
                 token_path: Optional[str] = None) -> Dict:
    """
    Actualiza la fecha y hora de un evento existente en Google Calendar,
    manteniendo su duración original.
    """
    service = get_service(token_path)
    cal_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")

    # 1) Obtener evento actual
    event = service.events().get(calendarId=cal_id, eventId=event_id).execute()

    # 2) Determinar zona horaria
    tz = event.get("start", {}).get("timeZone") or os.getenv("TIMEZONE", "Europe/Madrid")
    tz_obj = pytz.timezone(tz)

    # 3) Calcular la duración del evento
    #    Manejar tanto dateTime como date (all-day)
    start_info = event["start"]
    end_info = event["end"]

    if "dateTime" in start_info and "dateTime" in end_info:
        old_start = datetime.fromisoformat(start_info["dateTime"])
        old_end = datetime.fromisoformat(end_info["dateTime"])
        duration = old_end - old_start
    elif "date" in start_info and "date" in end_info:
        # Evento de todo el día: duración en días
        old_start = datetime.fromisoformat(start_info["date"])
        old_end = datetime.fromisoformat(end_info["date"])
        duration = old_end - old_start
    else:
        # Fallback: 60 minutos
        duration = timedelta(minutes=60)

    # 4) Construir nueva fecha/hora de inicio con la zona horaria correcta
    #    new_date_iso: 'YYYY-MM-DD', new_time_hhmm: 'HH:MM'
    new_start_naive = datetime.strptime(f"{new_date_iso} {new_time_hhmm}", "%Y-%m-%d %H:%M")
    new_start = tz_obj.localize(new_start_naive)
    new_end = new_start + duration

    # 5) Actualizar campos start/end igual que en create_event
    event["start"] = {
        "dateTime": new_start.isoformat(),
        "timeZone": tz,
    }
    event["end"] = {
        "dateTime": new_end.isoformat(),
        "timeZone": tz,
    }

    # 6) Enviar actualización
    updated = service.events().update(
        calendarId=cal_id,
        eventId=event_id,
        body=event,
        sendUpdates="all"
    ).execute()

    return updated

def delete_event(event_id: str, token_path: Optional[str] = None) -> bool:
    service = get_service(token_path)
    cal_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")
    service.events().delete(calendarId=cal_id, eventId=event_id, sendUpdates="all").execute()
    return True
