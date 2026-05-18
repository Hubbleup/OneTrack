import streamlit as st
import psycopg2
import pandas as pd
from sqlalchemy import create_engine
import urllib.parse
from auth import check_auth, logout

# Set global page config
st.set_page_config(page_title="OneTrack Hub", page_icon="📈", layout="wide")

# Authentication Check
check_auth()
logout() # Add logout button to sidebar

st.title("🛡️ OneTrack Investment Command Centre")
st.markdown("---")

try:
    user = urllib.parse.quote_plus(st.secrets['supabase']['user'])
    password = urllib.parse.quote_plus(st.secrets['supabase']['password'])
    host = st.secrets['supabase']['host']
    port = st.secrets['supabase']['port']
    database = st.secrets['supabase']['database']
    db_url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"
    engine = create_engine(db_url)
    
    # Quick KPI Row
    col1, col2, col3 = st.columns(3)
    
    # Total Invested
    # Note: Using quoted table names to match Supabase capitalization
    investments = pd.read_sql('SELECT "Purchase_Value", "Exchange_Rate", "Country" FROM "Investment"', engine)
    def get_aud_cost(row):
        val, rate, country = row['Purchase_Value'], row['Exchange_Rate'], row['Country']
        if country == 'IND' and (rate is None or rate == 1.0 or pd.isna(rate)):
            return val * 0.018
        return val * (rate if rate and not pd.isna(rate) else 1.0)
    
    cost_basis = investments.apply(get_aud_cost, axis=1).sum() if not investments.empty else 0
    col1.metric("Total Cost Basis", f"${cost_basis:,.2f}")
    
    # Total Dividends
    total_div = pd.read_sql('SELECT SUM("total_dividend") FROM "Dividends"', engine).iloc[0,0] or 0
    col2.metric("Total Dividends", f"${total_div:,.2f}")

    yield_pct = (total_div / cost_basis * 100) if cost_basis > 0 else 0
    col3.metric("All-time Yield", f"{yield_pct:.2f}%")
    
    st.info("👈 Use the sidebar to navigate between Add Assets, Dividends, and Net Worth.")
except Exception as e:
    st.error(f"An error occurred while loading the dashboard: {e}")
    st.info("Please check your Supabase connection settings in secrets.toml.")