import os
import json
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

def create_google_service(credentials_path=None, api_name='gmail', api_version='v1', token_path=None, scopes=None, prefix=''):
    """.

    Args:
        credentials_path: path to the OAuth2 client secret file (JSON).
        api_name: the name of the API (e.g. 'sheets', 'gmail').
        api_version: version of the API (e.g. 'v4', 'v1').
        token_path: path to store/read the OAuth token JSON.
        scopes: list of scopes to request (must match credentials file).
        prefix: optional prefix for token or other naming schemes.

    Returns:
        A `googleapiclient.discovery.Resource` for the requested service.  The
        credentials are read from `token_path` if present; if they are missing,
        expired or invalid the user will be prompted to authenticate via the
        local browser.
    """

    # if no credentials_path supplied, default to the project's Secret/client_secret.json
    if credentials_path is None:
        credentials_path = os.path.join(os.path.dirname(__file__), 'Secret', 'client_secret.json')
    # sanity checks for the client secret file
    if not os.path.isfile(credentials_path):
        raise FileNotFoundError(f"credentials_path {credentials_path} does not exist")
    # optionally warn if the file doesn't look like an OAuth client file
    try:
        with open(credentials_path, 'r') as _f:
            info = json.load(_f)
        if not any(k in info for k in ('installed', 'web')):
            raise ValueError("credentials_path does not appear to be an OAuth client secret JSON")
    except Exception:
        # re-raise to alert the caller; we don't want silent surprises
        raise

    API_NAME = api_name
    API_VERSION = api_version
    Client_Secret_File = credentials_path
    if scopes is None:
        SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
    else:
        # support either [['scope1','scope2']] or ['scope1','scope2']
        SCOPES = scopes[0] if isinstance(scopes, list) and len(scopes) and isinstance(scopes[0], list) else scopes

    creds = None
    if token_path is None:
        token_path = os.path.join(os.path.dirname(__file__), 'Secret', 'token.json')

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    # if there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, 'w') as token:
            token.write(creds.to_json())

    service = build(API_NAME, API_VERSION, credentials=creds)
    return service


def get_messages_from_sender(gmail_service, sender, user_id='me'):
    """Retrieve messages from Gmail that originate from a specific sender."""
    query = f"from:{sender}"
    response = gmail_service.users().messages().list(userId=user_id, q=query).execute()
    messages = response.get('messages', [])
    results = []
    for msg in messages:
        msg_id = msg.get('id')
        if msg_id:
            full = gmail_service.users().messages().get(
                        userId=user_id, id=msg_id, format='full').execute()
            results.append(full)
    return results


if __name__ == '__main__':
    current_dir = os.path.dirname(os.path.abspath(__file__))
    creds_file = os.path.join(current_dir, 'Secret', 'client_secret.json')
    token_file = os.path.join(current_dir, 'Secret', 'token.json')

    # FIX: Use a simple list of strings, not a nested list
    SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

    # CRITICAL: If token.json exists from a previous run, delete it manually now.

    service = create_google_service(
        credentials_path=creds_file,
        api_name='gmail',
        api_version='v1',
        token_path=token_file,
        scopes=SCOPES, # Ensure your function doesn't wrap this in another list
    )

    sender_address = 'brokingservice@cmcmarkets.com.au'
    messages = get_messages_from_sender(service, sender_address)

    for m in messages:
        print('Snippet:', m.get('snippet'))
