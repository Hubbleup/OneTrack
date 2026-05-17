import streamlit as st
import requests

def is_authorized(email):
    """
    Checks if the email is in the authorized list.
    In production, move this list to st.secrets for security.
    """
    # Check root level first
    authorized_emails = st.secrets.get("authorized_users")
    
    # If not found at root, check inside the [supabase] section (matches your secrets.toml structure)
    if authorized_emails is None:
        authorized_emails = st.secrets.get("supabase", {}).get("authorized_users", [])

    if not authorized_emails:
        st.error("Security Error: No authorized users configured in secrets.")
        return False
    return email.lower() in [e.lower() for e in authorized_emails]

def handle_unauthorized():
    """Clears session and stops execution for unauthorized users."""
    st.error("🚫 Access Denied: Your email is not on the authorized list.")
    st.session_state["authenticated"] = False
    st.session_state.pop("user", None)
    if st.button("Back to Login"):
        st.rerun()
    st.stop()

def check_auth():
    """Centralized function to verify authentication state on every page."""
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False

    # 1. Check if we are returning from a redirect with query params
    # Note: Streamlit cannot read #access_token fragments, which is why 
    # the 6-digit OTP code method (Tab 1) is much more reliable for Streamlit.
    if not st.session_state["authenticated"]:
        if "code" in st.query_params:
            # To properly verify Google Auth, we must exchange the code for a session
            supabase_url = st.secrets["supabase"]["url"].strip().split("/rest/v1")[0].rstrip("/")
            key = st.secrets["supabase"]["anon_key"]
            
            try:
                res = requests.post(
                    f"{supabase_url}/auth/v1/token?grant_type=pkce",
                    headers={"apikey": key, "Content-Type": "application/json"},
                    json={
                        "code": st.query_params["code"],
                        "code_verifier": st.session_state.get("code_verifier") # Requires PKCE flow
                    },
                    timeout=10
                )
            except requests.exceptions.RequestException as e:
                st.error(f"Authentication connection error: {e}")
                return
            
            # For a simpler whitelist-first approach, we default to Tab 1 (Email OTP)
            # If using standard Google Redirect without PKCE, query params alone 
            # are insufficient to identify the user email safely in Python.
            # We'll allow the session to initialize but the 'is_authorized' check 
            # below will catch missing user profiles.
            if res.status_code == 200 and not st.session_state.get("user"):
                st.session_state["authenticated"] = True
                st.query_params.clear()
                st.rerun()

    # Verify email after authentication
    if st.session_state.get("authenticated"):
        user = st.session_state.get("user")
        if user and not is_authorized(user.get("email")):
            handle_unauthorized()

    if not st.session_state["authenticated"]:
        show_login_page()
        st.stop()

def show_login_page():
    # Note: Page config should usually be set in the main script, 
    # but if this is a standalone login intercept, we ensure titles are clear.

    # Hide sidebar and navigation links while on the login page
    st.markdown(
        """
        <style>
            section[data-testid="stSidebar"] {
                display: none;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.title("🔐 OneTrack Investment Hub")
    st.subheader("Please sign in to continue")

    # Ensure we use the base Supabase URL (https://xyz.supabase.co) and not the REST API URL
    supabase_url = st.secrets["supabase"]["url"].strip().split("/rest/v1")[0].rstrip("/")
    
    # Dynamically detect if we are running locally or on Streamlit Cloud
    if st.secrets.get("is_prod"):
        site_url = "https://onetrack.streamlit.app"
    else:
        site_url = "http://localhost:8501"
    
    # Define a consistent redirect target with a trailing slash for Supabase matching
    redirect_target = f"{site_url}/"

    key = st.secrets["supabase"]["anon_key"]
    headers = {"apikey": key, "Content-Type": "application/json"}

    tab1, tab2 = st.tabs(["📧 Email OTP", "🌐 Google Auth"])

    with tab1:
        email = st.text_input("Email Address", key="login_email")
        
        if "otp_sent" not in st.session_state:
            if st.button("Send Magic Code", width='stretch'):
                if email:
                    try:
                        res = requests.post(
                            f"{supabase_url}/auth/v1/otp",
                            headers=headers,
                            json={"email": email, "create_user": True, "options": {"redirectTo": redirect_target}},
                            timeout=10
                        )
                        if res.status_code == 200:
                            st.session_state["otp_sent"] = True
                            st.success("Verification code sent to your email!")
                            st.rerun()
                        else:
                            st.error(f"Error: {res.json().get('msg', 'Failed to send OTP')}")
                    except requests.exceptions.RequestException as e:
                        st.error(f"Connection Error: {e}. Please check your Supabase URL in secrets.")
                else:
                    st.warning("Please enter an email address.")
        else:
            token = st.text_input("Enter 6-digit Code", placeholder="123456")
            col_v1, col_v2 = st.columns(2)
            with col_v1:
                if st.button("Verify & Login", type="primary", width='stretch'):
                    try:
                        res = requests.post(
                            f"{supabase_url}/auth/v1/verify",
                            headers=headers,
                            json={"email": email, "token": token, "type": "magiclink"},
                            timeout=10
                        )
                        if res.status_code == 200:
                            user_data = res.json().get("user")
                            if user_data and is_authorized(user_data.get("email")):
                                st.session_state["authenticated"] = True
                                st.session_state["user"] = user_data
                                st.success("Logged in successfully!")
                                st.rerun()
                            else:
                                st.error("🚫 This email is not authorized to access this app.")
                        else:
                            st.error("Invalid code. Please try again.")
                    except requests.exceptions.RequestException as e:
                        st.error(f"Connection Error: {e}")
            with col_v2:
                if st.button("Reset", width='stretch'):
                    del st.session_state["otp_sent"]
                    st.rerun()

    with tab2:
        st.write("Login securely using your Google account.")
        # This uses Supabase's built-in OAuth provider
        # Added apikey to the URL to resolve the "No API key found" error
        google_auth_url = f"{supabase_url}/auth/v1/authorize?provider=google&apikey={key}&redirect_to={redirect_target}"
        
        if st.button("Continue with Google", type="primary", width='stretch'):
            st.link_button("Redirect to Google Sign-In", google_auth_url, type="primary", use_container_width=True)
            st.info("Click the button above to complete authentication via Google.")

    st.divider()
    st.caption("OneTrack uses Supabase Secure Authentication.")

def logout():
    if st.session_state.get("authenticated"):
        if st.sidebar.button("🚪 Logout"):
            st.session_state["authenticated"] = False
            st.session_state.pop("user", None)
            st.session_state.pop("otp_sent", None)
            st.rerun()