import os
import sys
import json
import argparse
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

                # Use all defaults
        python googleapi.py
        
        # Override sender
        python googleapi.py --sender="other@example.com"
        
        # Override scope
        python googleapi.py --scope="https://www.googleapis.com/auth/gmail.readonly"
        
        # Override multiple args
        python googleapi.py --sender="user@example.com" --scope="https://www.googleapis.com/auth/gmail.readonly" --creds="/path/to/creds.json"
        
        # Multiple scopes
        python googleapi.py --scope="scope1" --scope="scope2"
        
        # Show help
        python googleapi.py --help
    """

    # before we do anything, make sure the caller supplied what we need
    if scopes is None or (isinstance(scopes, (list, tuple)) and not scopes):
        print("ERROR: no scopes were provided, cannot authenticate.")
        sys.exit(1)

    # if no credentials_path supplied, default to the project's Secret/client_secret.json
    if credentials_path is None:
        credentials_path = os.path.join(os.path.dirname(__file__), 'Secret', 'client_secret.json')
    # sanity checks for the client secret file
    if not os.path.isfile(credentials_path):
        print(f"ERROR: credentials_path {credentials_path} does not exist.")
        sys.exit(1)
    # optionally warn if the file doesn't look like an OAuth client file
    try:
        with open(credentials_path, 'r') as _f:
            info = json.load(_f)
        if not any(k in info for k in ('installed', 'web')):
            print("ERROR: credentials_path does not appear to be an OAuth client secret JSON")
            sys.exit(1)
    except Exception as ex:
        print(f"ERROR reading credentials: {ex}")
        sys.exit(1)

    API_NAME = api_name
    API_VERSION = api_version
    Client_Secret_File = credentials_path
    # convert nested list for backwards compatibility, but prefer a flat list
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
    """Retrieve messages from Gmail that originate from a specific sender.

    This function expects a ready-to-use ``gmail_service`` produced by
    :func:`create_google_service`.  It simply constructs a Gmail search
    query and returns a list of message payloads.
    """
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


def fetch_emails_for_sender(sender, credentials_path=None, token_path=None, scopes=None):
    """Convenience wrapper that checks for the presence of the credentials
    and scopes, creates a service, and fetches messages.

    This is the simple entry point described by the user: if a scope list or
    credentials file are missing the function prints an error and exits; if
    both are present the Gmail API is queried for messages from ``sender``.
    """
    # create_google_service already handles validation and will exit on errors
    service = create_google_service(credentials_path=credentials_path,
                                    token_path=token_path,
                                    scopes=scopes)
    return get_messages_from_sender(service, sender)


if __name__ == '__main__':
    # Default paths and scope
    current_dir = os.path.dirname(os.path.abspath(__file__))
    default_creds_file = os.path.join(current_dir, 'Secret', 'client_secret.json')
    default_token_file = os.path.join(current_dir, 'Secret', 'token.json')
    default_scope = 'https://www.googleapis.com/auth/gmail.readonly'
    default_sender = 'brokingservice@cmcmarkets.com.au'

    # Parse command-line arguments (input takes precedence over hardcoded defaults)
    parser = argparse.ArgumentParser(
        description='Fetch emails from a specific sender via Gmail API'
    )
    parser.add_argument(
        '--sender',
        default=default_sender,
        help=f'Email address of the sender (default: {default_sender})'
    )
    parser.add_argument(
        '--scope',
        action='append',
        dest='scopes',
        help=f'OAuth scope(s) to request (default: {default_scope}). Can be specified multiple times.'
    )
    parser.add_argument(
        '--creds',
        default=default_creds_file,
        help=f'Path to credentials JSON file (default: {default_creds_file})'
    )
    parser.add_argument(
        '--token',
        default=default_token_file,
        help=f'Path to token JSON file (default: {default_token_file})'
    )
    args = parser.parse_args()

    # Use provided scopes or fall back to hardcoded default
    SCOPES = args.scopes if args.scopes else [default_scope]

    # Authenticate and fetch messages
    service = create_google_service(
        credentials_path=args.creds,
        api_name='gmail',
        api_version='v1',
        token_path=args.token,
        scopes=SCOPES,
    )

    messages = get_messages_from_sender(service, args.sender)

    if not messages:
        print(f"No messages found from {args.sender}")
    for m in messages:
        print('Snippet:', m.get('snippet'))
