import os, pytz
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar"]

def get_service():
    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
    token_path = os.getenv("GOOGLE_TOKEN_PATH", "token.json")
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as token:
            token.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)

def create_event(
    summary: str,
    description: str,
    start_dt: datetime,
    end_dt: datetime,
    timezone: str = "Europe/Madrid",
    attendees_emails: Optional[List[str]] = None
) -> Dict:
    service = get_service()
    tz = timezone
    start = pytz.timezone(tz).localize(start_dt).isoformat()
    end = pytz.timezone(tz).localize(end_dt).isoformat()
    event = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start, "timeZone": tz},
        "end": {"dateTime": end, "timeZone": tz},
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": 30},
                {"method": "email", "minutes": 120}
            ]
        },
    }
    if attendees_emails:
        event["attendees"] = [{"email": e} for e in attendees_emails]
    cal_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")
    return service.events().insert(calendarId=cal_id, body=event, sendUpdates="all").execute()
