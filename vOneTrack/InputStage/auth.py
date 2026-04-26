import streamlit as st
import requests

def check_auth():
    """Centralized function to verify authentication state on every page."""
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False

    # Handle Google Auth Callback (Token is often in the URL fragment/params)
    # Note: For production Google Auth in Streamlit, libraries like streamlit-oauth are recommended,
    # but this handles the basic Supabase redirect flow logic.
    if not st.session_state["authenticated"]:
        show_login_page()
        st.stop()

def show_login_page():
    # Note: Page config should usually be set in the main script, 
    # but if this is a standalone login intercept, we ensure titles are clear.
    
    st.title("🔐 OneTrack Investment Hub")
    st.subheader("Please sign in to continue")

    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["anon_key"]
    headers = {"apikey": key, "Content-Type": "application/json"}

    tab1, tab2 = st.tabs(["📧 Email OTP", "🌐 Google Auth"])

    with tab1:
        email = st.text_input("Email Address", key="login_email")
        
        if "otp_sent" not in st.session_state:
            if st.button("Send Magic Code", width='stretch'):
                if email:
                    res = requests.post(
                        f"{url}/auth/v1/otp",
                        headers=headers,
                        json={"email": email, "create_user": True}
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
                        f"{url}/auth/v1/verify",
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
        google_auth_url = f"{url}/auth/v1/authorize?provider=google"
        
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