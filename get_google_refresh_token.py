from google_auth_oauthlib.flow import InstalledAppFlow
import os
from dotenv import load_dotenv

load_dotenv()

SCOPES = [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/calendar.events'
]

def get_refresh_token():
    """Get a refresh token for Google APIs."""
    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": os.getenv("GOOGLE_CLIENT_ID"),
                "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "redirect_uris": ["http://localhost:8000/oauth2callback"],
            }
        },
        SCOPES
    )

    credentials = flow.run_local_server(port=8080)

    print("\nYour refresh token:")
    print("-" * 50)
    print(credentials.refresh_token)
    print("-" * 50)
   

if __name__ == "__main__":
    print("Starting Google OAuth flow...")
    print("A browser window will open. Please log in and grant access.")
    get_refresh_token()
