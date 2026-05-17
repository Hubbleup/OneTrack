import streamlit as st
import os
import psycopg2
import urllib.parse
from sqlalchemy import create_engine

def get_db_connection():
    """Centralized function to get a psycopg2 connection, filtering out non-PG keys."""
    pg_keys = ["host", "port", "database", "user", "password", "options"]
    conn_params = {k: v for k, v in st.secrets["supabase"].items() if k in pg_keys}
    return psycopg2.connect(**conn_params)

def get_db_engine():
    """Centralized function to create a SQLAlchemy engine for Pandas compatibility."""
    user = urllib.parse.quote_plus(st.secrets['supabase']['user'])
    password = urllib.parse.quote_plus(st.secrets['supabase']['password'])
    host = st.secrets['supabase']['host']
    port = st.secrets['supabase']['port']
    database = st.secrets['supabase']['database']
    
    # Construct URL manually to ensure non-PG keys like 'url' or 'anon_key' aren't used
    db_url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"
    return create_engine(db_url)

def show_sync_status():
    """Displays the Green/Red dot in the sidebar."""
    from Portfolio_updater import PortfolioUpdater
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
            updater = PortfolioUpdater()
            with st.spinner("Updating..."):
                updater.refresh_live_prices()
            st.rerun()
