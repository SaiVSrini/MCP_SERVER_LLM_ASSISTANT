from typing import Dict, Optional, List
from datetime import datetime, timedelta
import os

class Scheduler:
    """Meeting scheduler with privacy protection."""
    
    def __init__(self, cfg: Optional[Dict] = None, llm=None):
        self.cfg = cfg or {}
        self.llm = llm
        self.calendar_scopes = self._resolve_scopes()
        self._setup_calendar()
    
    def _resolve_scopes(self) -> List[str]:
        """Determine the scopes required for calendar access."""
        scopes = self.cfg.get("calendar_scopes")
        if scopes:
            return scopes
        env_scopes = os.environ.get("GOOGLE_CALENDAR_SCOPES")
        if env_scopes:
            return [scope.strip() for scope in env_scopes.split(",") if scope.strip()]
        return [
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/calendar.events",
        ]

    def _setup_calendar(self):
        """Set up Google Calendar API client."""
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build
            from google.auth.exceptions import RefreshError

            info = {
                "client_id": os.environ.get("GOOGLE_CLIENT_ID"),
                "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET"),
                "refresh_token": os.environ.get("GOOGLE_REFRESH_TOKEN"),
                "token_uri": "https://oauth2.googleapis.com/token",
            }

            creds = Credentials.from_authorized_user_info(info, scopes=self.calendar_scopes)

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    try:
                        creds.refresh(Request())
                    except RefreshError as refresh_error:
                        printable_scopes = ", ".join(self.calendar_scopes)
                        print(
                            "Calendar setup error: refresh token is missing the required scopes.\n"
                            f"Requested scopes: {printable_scopes}\n"
                            "Please regenerate GOOGLE_REFRESH_TOKEN using get_google_refresh_token.py "
                            "with the same scopes."
                        )
                        raise

            self.service = build('calendar', 'v3', credentials=creds)
            return True
        except Exception as e:
            print(f"Calendar setup error: {e}")
            self.service = None
            return False

    def schedule_meeting(self, title: str, description: str, start_time: datetime,
                        duration_minutes: int, attendees: List[str]) -> Dict:
        """Schedule a meeting with privacy protection."""
        try:
            if self.llm:
                description = self.llm._redact_sensitive_info(description)
                title = self.llm._redact_sensitive_info(title)
            
            if not self.service:
                if not self._setup_calendar():
                    return {
                        "error": "Calendar service not available",
                        "status": "failed"
                    }

            end_time = start_time + timedelta(minutes=duration_minutes)
            event = {
                'summary': title,
                'description': description,
                'start': {
                    'dateTime': start_time.isoformat(),
                    'timeZone': 'America/Chicago',
                },
                'end': {
                    'dateTime': end_time.isoformat(),
                    'timeZone': 'America/Chicago',
                },
                'attendees': [{'email': email} for email in attendees],
                'reminders': {
                    'useDefault': True
                }
            }

            event = self.service.events().insert(
                calendarId='primary',
                body=event,
                sendUpdates='all'
            ).execute()

            return {
                "title": title,
                "description": description,
                "start": start_time.isoformat(),
                "end": end_time.isoformat(),
                "attendees": attendees,
                "eventId": event.get('id'),
                "status": "scheduled"
            }
        except Exception as e:
            return {
                "error": str(e),
                "status": "failed"
            }
