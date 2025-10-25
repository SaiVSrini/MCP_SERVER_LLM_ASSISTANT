from typing import Dict, Optional, List

class Emailer:
    """Email connector with privacy protection."""
    
    def __init__(self, cfg: Optional[Dict] = None, llm=None):
        self.cfg = cfg or {}
        self.llm = llm
        self._setup_gmail()
    
    def _setup_gmail(self):
        """Set up Gmail API client using OAuth credentials."""
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build
            import base64
            from email.mime.text import MIMEText
            import os

            creds = Credentials.from_authorized_user_info({
                "client_id": os.environ.get("GOOGLE_CLIENT_ID"),
                "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET"),
                "refresh_token": os.environ.get("GOOGLE_REFRESH_TOKEN"),
                "token_uri": "https://oauth2.googleapis.com/token",
                "scopes": ["https://www.googleapis.com/auth/gmail.send"]
            })

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())

            self.service = build('gmail', 'v1', credentials=creds)
            return True
        except Exception as e:
            print(f"Gmail setup error: {e}")
            self.service = None
            return False

    def send(self, to: str, subject: str, body: str) -> Dict:
        """Send email with privacy checks."""
        try:
            if self.llm:
                body = self.llm._redact_sensitive_info(body)
            
            if not self.service:
                if not self._setup_gmail():
                    return {
                        "error": "Gmail service not available",
                        "status": "failed"
                    }

            from email.mime.text import MIMEText
            import base64
            message = MIMEText(body)
            message['to'] = to
            message['subject'] = subject
            
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
            sent = self.service.users().messages().send(
                userId='me',
                body={'raw': raw}
            ).execute()
            
            return {
                "to": to,
                "subject": subject,
                "body": body,
                "messageId": sent.get('id'),
                "status": "sent"
            }
        except Exception as e:
            return {
                "error": str(e),
                "status": "failed"
            }
