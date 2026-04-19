import streamlit as st
import os
from Portfolio_updater import PortfolioUpdater

def show_sync_status():
    """Displays the Green/Red dot in the sidebar."""
    with st.sidebar:
        st.divider()
        # Read the timestamp from the file created by the updater
        if os.path.exists("last_sync.txt"):
            with open("last_sync.txt", "r") as f:
                last_time = f.read()
            st.success(f"🟢 **System Live**")
            st.caption(f"Last Price Sync: {last_time}")
        else:
            st.warning("🟡 **Sync Initializing...**")
        
        # Manual Force Refresh Button
        if st.button("⚡ Force Refresh Now"):
            updater = PortfolioUpdater("onetrack.db")
            with st.spinner("Updating..."):
                updater.refresh_live_prices()
            st.rerun()
