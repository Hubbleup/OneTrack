import streamlit as st
import sqlite3
import pandas as pd
import os

# Set global page config
st.set_page_config(page_title="OneTrack Hub", page_icon="📈", layout="wide")

DB_PATH = "onetrack.db"

st.title("🛡️ OneTrack Investment Command Centre")
st.markdown("---")

if os.path.exists(DB_PATH):
    conn = sqlite3.connect(DB_PATH)
    
    # Quick KPI Row
    col1, col2, col3 = st.columns(3)
    
    # Total Invested
    cost_basis = pd.read_sql("SELECT SUM(Purchase_Value) FROM Investment", conn).iloc[0,0] or 0
    col1.metric("Total Cost Basis", f"${cost_basis:,.2f}")
    
    # Total Dividends
    total_div = pd.read_sql("SELECT SUM(total_dividend) FROM Dividends", conn).iloc[0,0] or 0
    col2.metric("Total Dividends", f"${total_div:,.2f}")
    
    # Portfolio Yield
    yield_pct = (total_div / cost_basis * 100) if cost_basis > 0 else 0
    col3.metric("All-time Yield", f"{yield_pct:.2f}%")
    
    conn.close()
    
    st.info("👈 Use the sidebar to navigate between Add Assets, Dividends, and Net Worth.")
else:
    st.error(f"Database not found at {DB_PATH}. Please check file location.")
