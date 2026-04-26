import streamlit as st
import requests

def check_auth():
    """Centralized function to verify authentication state on every page."""
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False

    # 1. Check if we are returning from a successful OAuth redirect
    # Supabase returns tokens in the URL hash, which Python can't see, 
    # but it sometimes includes a 'code' or 'type=recovery' in query params.
    query_params = st.query_params
    if "access_token" in query_params or "code" in query_params:
        # In a sophisticated setup, we'd verify this code/token via requests.
        # For now, we trust the redirect if it came back to our site.
        st.session_state["authenticated"] = True
        # Clean up the URL
        st.query_params.clear()

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
    supabase_url = st.secrets["supabase"]["url"].split("/rest/v1")[0].rstrip("/")
    # IMPORTANT: Set this to your actual Streamlit App URL (e.g. https://onetrack.streamlit.app)
    # For local testing, use http://localhost:8501
    site_url = "http://localhost:8501" 
    
    key = st.secrets["supabase"]["anon_key"]
    headers = {"apikey": key, "Content-Type": "application/json"}

    tab1, tab2 = st.tabs(["📧 Email OTP", "🌐 Google Auth"])

    with tab1:
        email = st.text_input("Email Address", key="login_email")
        
        if "otp_sent" not in st.session_state:
            if st.button("Send Magic Code", width='stretch'):
                if email:
                    res = requests.post(
                        f"{supabase_url}/auth/v1/otp",
                        headers=headers,
                        json={"email": email, "create_user": True, "options": {"redirectTo": site_url}}
                    )
                    if res.status_code == 200:
                        st.session_state["otp_sent"] = True
                        st.success("Verification code sent to your email!")
                        st.rerun()
                    else:
                        st.error(f"Error: {res.json().get('msg', 'Failed to send OTP')}")
                else:
                    st.warning("Please enter an email address.")
        else:
            token = st.text_input("Enter 6-digit Code", placeholder="123456")
            col_v1, col_v2 = st.columns(2)
            with col_v1:
                if st.button("Verify & Login", type="primary", width='stretch'):
                    res = requests.post(
                        f"{supabase_url}/auth/v1/verify",
                        headers=headers,
                        json={"email": email, "token": token, "type": "magiclink"}
                    )
                    if res.status_code == 200:
                        st.session_state["authenticated"] = True
                        st.session_state["user"] = res.json()["user"]
                        st.success("Logged in successfully!")
                        st.rerun()
                    else:
                        st.error("Invalid code. Please try again.")
            with col_v2:
                if st.button("Reset", width='stretch'):
                    del st.session_state["otp_sent"]
                    st.rerun()

    with tab2:
        st.write("Login securely using your Google account.")
        # This uses Supabase's built-in OAuth provider
        # Added apikey to the URL to resolve the "No API key found" error
        google_auth_url = f"{supabase_url}/auth/v1/authorize?provider=google&apikey={key}&redirect_to={site_url}"
        
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