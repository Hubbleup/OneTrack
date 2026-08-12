import streamlit as st
import requests
import os
import base64
import hashlib

def is_authorized(email):
    """
    Checks if the email is in the authorized list from secrets.
    """
    authorized_emails = st.secrets.get("supabase", {}).get("authorized_users", [])
    if not authorized_emails:
        st.error("Security Error: No authorized users configured in secrets.")
        return False
    return email.lower() in [e.lower() for e in authorized_emails]

def handle_unauthorized():
    """Clears session and stops execution for unauthorized users."""
    st.error("🚫 Access Denied: Your email is not on the authorized list.")
    st.session_state.clear() # Clear the entire session state for security
    if st.button("Back to Login"):
        st.rerun()
    st.stop()

def get_supabase_auth_url():
    """Safely constructs the base Supabase auth URL from secrets."""
    if "url" not in st.secrets.get("supabase", {}):
        st.error("Configuration Error: `url` is missing from `[supabase]` secrets.")
        st.stop()
    # Ensures we get the base URL (e.g., https://project.supabase.co)
    base_url = st.secrets["supabase"]["url"].strip().split("/rest/v1")[0].rstrip("/")
    return f"{base_url}/auth/v1"

def exchange_code_for_session(auth_url, api_key, auth_code):
    """Exchanges a PKCE auth code for a user session. Returns True on success."""
    try:
        res = requests.post(
            f"{auth_url}/token?grant_type=pkce",
            headers={"apikey": api_key, "Content-Type": "application/json"},
            json={
                "auth_code": auth_code,
                "code_verifier": st.session_state.get("code_verifier")
            },
            timeout=10
        )
        res.raise_for_status() # Raise an exception for bad status codes
        data = res.json()
        user = data.get("user")
        if user and is_authorized(user.get("email")):
            st.session_state["authenticated"] = True
            st.session_state["user"] = user
            # Clean up session state after successful login
            st.session_state.pop("code_verifier", None)
            st.session_state.pop("otp_sent", None)
            st.session_state.pop("auth_attempted", None)
            st.query_params.clear() # CRITICAL: Clear URL params
            return True
        else:
            handle_unauthorized()
            return False
    except requests.exceptions.RequestException as e:
        st.error(f"Authentication failed: {e}")
        st.session_state.pop("code_verifier", None) # Clear verifier on failure
        return False

def check_auth():
    """Centralized function to verify authentication state on every page."""
    # --- LOCAL DEVELOPMENT BYPASS ---
    if str(st.secrets.get("is_prod")).lower() != 'true':
        if "authenticated" not in st.session_state:
            print("Auth: Running in LOCAL DEVELOPMENT mode. Bypassing login.")
            st.session_state["authenticated"] = True
            st.session_state["user"] = {"email": "local.dev@example.com"}
        return
    # --- END BYPASS ---

    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False

    auth_url = get_supabase_auth_url()
    api_key = st.secrets.get("supabase", {}).get("anon_key")

    # Check if returning from Google OAuth with a code.
    # Use a flag to ensure this is only attempted once.
    if "code" in st.query_params and not st.session_state.get("auth_attempted"):
        st.session_state["auth_attempted"] = True
        auth_code = st.query_params["code"]
        if exchange_code_for_session(auth_url, api_key, auth_code):
            st.rerun() # Force a rerun into the authenticated state

    # Verify email after authentication is established
    if st.session_state.get("authenticated"):
        user = st.session_state.get("user")
        if not (user and is_authorized(user.get("email"))):
            handle_unauthorized()

    # If not authenticated, show login page and stop
    if not st.session_state.get("authenticated"):
        show_login_page(auth_url, api_key)
        st.stop()

def show_login_page(auth_url, api_key):
    """Displays the login UI."""
    st.markdown(
        "<style> section[data-testid='stSidebar'] {display: none;} </style>",
        unsafe_allow_html=True,
    )
    st.title("🔐 OneTrack Investment Hub")
    st.subheader("Please sign in to continue")

    # Best Practice: Read the site URL from secrets for better configuration.
    prod_site_url = st.secrets.get("supabase", {}).get("site_url")
    if str(st.secrets.get("is_prod")).lower() == 'true' and not prod_site_url:
        st.error("Configuration Error: `site_url` is missing from `[supabase]` secrets.")
        st.stop()
    redirect_target = prod_site_url if str(st.secrets.get("is_prod")).lower() == 'true' else "http://localhost:8501/"

    tab1, tab2 = st.tabs(["📧 Email OTP", "🌐 Google Auth"])

    with tab1:
        email = st.text_input("Email Address", key="login_email")
        if "otp_sent" not in st.session_state:
            if st.button("Send Magic Code", use_container_width=True):
                if email and is_authorized(email):
                    try:
                        res = requests.post(
                            f"{auth_url}/otp",
                            headers={"apikey": api_key, "Content-Type": "application/json"},
                            json={"email": email, "create_user": False},
                            timeout=10
                        )
                        if res.status_code == 200:
                            st.session_state["otp_sent"] = True
                            st.success("Verification code sent! Check your email.")
                            st.rerun()
                        else:
                            st.error(f"Error: {res.json().get('msg', 'Failed to send OTP')}")
                    except requests.exceptions.RequestException as e:
                        st.error(f"Connection Error: {e}")
                else:
                    st.warning("Please enter a valid, authorized email address.")
        else:
            token = st.text_input("Enter 6-digit Code", placeholder="123456")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Verify & Login", type="primary", use_container_width=True):
                    try:
                        res = requests.post(
                            f"{auth_url}/verify",
                            headers={"apikey": api_key, "Content-Type": "application/json"},
                            json={"type": "magiclink", "email": email, "token": token},
                            timeout=10
                        )
                        if res.status_code == 200:
                            st.session_state["authenticated"] = True
                            st.session_state["user"] = res.json().get("user")
                            st.session_state.pop("otp_sent", None)
                            st.success("Logged in successfully!")
                            st.rerun()
                        else:
                            st.error("Invalid code. Please try again.")
                    except requests.exceptions.RequestException as e:
                        st.error(f"Connection Error: {e}")
            with col2:
                if st.button("Reset", use_container_width=True):
                    st.session_state.pop("otp_sent", None)
                    st.rerun()

    with tab2:
        st.info("Login securely using your Google account. You will be redirected.")
        if st.button("Continue with Google", type="primary", use_container_width=True):
            # --- PKCE Flow Step 1: Create and store code verifier ---
            code_verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b'=').decode('utf-8')
            st.session_state['code_verifier'] = code_verifier
            code_challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode('utf-8')).digest()).rstrip(b'=').decode('utf-8')

            google_auth_url = (
                f"{auth_url}/authorize?provider=google"
                f"&redirect_to={redirect_target}"
                f"&code_challenge_method=s256&code_challenge={code_challenge}"
            )
            st.link_button("Redirecting to Google...", google_auth_url, use_container_width=True)
            st.caption("If you are not redirected automatically, please click the button above.")

    st.divider()
    st.caption("OneTrack uses Supabase Secure Authentication.")

def logout():
    """Adds a logout button to the sidebar and handles session clearing."""
    if st.session_state.get("authenticated"):
        if st.sidebar.button("🚪 Logout"):
            # Clear all session state keys except for ones you might want to preserve
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            # Force a rerun to bring the user back to the login page
            st.rerun()
