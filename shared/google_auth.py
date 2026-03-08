"""
Google OAuth2 authentication for Google Docs and Drive APIs.
Handles token storage, refresh, and service object creation.
"""

import socket
import threading
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

CREDENTIALS_PATH = Path(__file__).parent.parent / 'data' / 'google_credentials.json'
TOKEN_PATH = Path(__file__).parent.parent / 'data' / 'google_token.json'

SCOPES = [
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/drive.file',
]

# Track background OAuth flow state
_oauth_lock = threading.Lock()
_oauth_status = {'running': False, 'error': None}


class GoogleAuthError(Exception):
    """Raised when Google auth is not configured or token is invalid."""
    pass


def _load_credentials():
    """Load and refresh credentials from stored token. Returns None if unavailable."""
    if not TOKEN_PATH.exists():
        return None

    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json())
        except Exception:
            return None

    if creds and creds.valid:
        return creds

    return None


def is_connected():
    """Check if we have valid Google credentials."""
    return _load_credentials() is not None


def get_user_email():
    """Get the email of the connected Google account, or None."""
    creds = _load_credentials()
    if not creds:
        return None
    try:
        service = build('drive', 'v3', credentials=creds)
        about = service.about().get(fields='user(emailAddress)').execute()
        return about.get('user', {}).get('emailAddress')
    except Exception:
        return None


def _kill_stale_oauth_server():
    """Check if port 8090 is occupied and reset the running flag so a new flow can start."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(1)
        result = sock.connect_ex(('127.0.0.1', 8090))
        if result == 0:
            # Port is occupied — a stale server is still running.
            # Send a dummy request to unblock it so the thread can exit.
            try:
                sock.sendall(b'GET /?error=cancelled HTTP/1.0\r\nHost: localhost\r\n\r\n')
                sock.recv(1024)
            except Exception:
                pass
            # Give the thread a moment to clean up
            threading.Event().wait(0.5)
            with _oauth_lock:
                _oauth_status['running'] = False
    except Exception:
        pass
    finally:
        sock.close()


def start_oauth_flow():
    """Start the OAuth flow in a background thread.
    Returns the auth URL for the frontend to open.
    The callback is handled by InstalledAppFlow's built-in local server on port 8090.
    Poll is_connected() to check completion.
    """
    if not CREDENTIALS_PATH.exists():
        raise GoogleAuthError(
            f"OAuth credentials not found at {CREDENTIALS_PATH}. "
            "Download from Google Cloud Console -> Credentials -> OAuth 2.0 Client ID."
        )

    with _oauth_lock:
        if _oauth_status['running']:
            return _oauth_status.get('auth_url')
        _oauth_status['running'] = True
        _oauth_status['error'] = None
        _oauth_status['auth_url'] = None

    # Kill any stale OAuth server occupying port 8090 from a previous failed attempt
    _kill_stale_oauth_server()

    # run_local_server uses webbrowser.get(None).open(url) internally.
    # We intercept the browser controller's open() to capture the auth URL
    # instead of actually opening a browser (which doesn't work in WSL2).
    captured_url = {}

    import webbrowser

    class _CaptureBrowser:
        """Fake browser that captures the URL instead of opening it."""
        def open(self, url, *args, **kwargs):
            captured_url['url'] = url

    _original_get = webbrowser.get

    def _capture_get(using=None):
        return _CaptureBrowser()

    def _run():
        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_PATH), SCOPES
            )
            webbrowser.get = _capture_get
            try:
                creds = flow.run_local_server(
                    port=8090,
                    open_browser=True,
                    success_message='Authorization complete! You can close this tab and return to DMM Tools.',
                    access_type='offline',
                    prompt='consent',
                )
            finally:
                webbrowser.get = _original_get

            TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            TOKEN_PATH.write_text(creds.to_json())
        except Exception as e:
            with _oauth_lock:
                _oauth_status['error'] = str(e)
        finally:
            webbrowser.get = _original_get
            with _oauth_lock:
                _oauth_status['running'] = False

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    # Wait for the URL to be captured (server starts fast, URL comes before blocking)
    for _ in range(50):  # up to 5 seconds
        if 'url' in captured_url:
            break
        threading.Event().wait(0.1)

    auth_url = captured_url.get('url')
    with _oauth_lock:
        _oauth_status['auth_url'] = auth_url

    return auth_url


def get_oauth_status():
    """Return the current OAuth flow status."""
    with _oauth_lock:
        return {
            'running': _oauth_status['running'],
            'error': _oauth_status['error'],
        }


def get_credentials():
    """Get valid credentials. Raises GoogleAuthError if not connected."""
    creds = _load_credentials()
    if not creds:
        raise GoogleAuthError(
            "Google account not connected. Go to Settings -> Google Account to connect."
        )
    return creds


def get_docs_service():
    """Returns an authenticated Google Docs API service object."""
    return build('docs', 'v1', credentials=get_credentials())


def get_drive_service():
    """Returns an authenticated Google Drive API service object."""
    return build('drive', 'v3', credentials=get_credentials())


def disconnect():
    """Revoke token and delete stored credentials."""
    creds = _load_credentials()
    if creds:
        try:
            creds.revoke(Request())
        except Exception:
            pass

    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()
