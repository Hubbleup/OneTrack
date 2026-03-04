import streamlit as st
import sqlite3
import os
import sys
import pandas as pd
from datetime import datetime

#Scope for the GmailService
default_scope = ['https://www.googleapis.com/auth/gmail.readonly']

# 1. SETUP PATHS & IMPORTS
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

# Import of custom modules
from googleapi import fetch_emails_for_sender
from Calculate_dividend import DividendCalculator

# DB Path
DB_PATH = os.path.join(parent_dir, "onetrack.db")

# 2. DATABASE LOGIC
def add_investment(ticker, units, price, date, country, currency):
    """Inserts a new investment record into the database."""
    purchase_value = units * price
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO Investment (
                Ticker, Units, Purchase_Price, Purchase_Value, 
                Purchase_Date, Country, Currency, Remain_Balance,
                Live_Price, Live_Value, Capital_Gain_Value, Capital_Gain_Percent
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0)
        """, (ticker.upper(), units, price, purchase_value, date, country, currency, units))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Error updating database: {e}")
        return False

# --- UI START ---
st.set_page_config(page_title="Add Assets", layout="wide")

# SECTION A: MANUAL FORM
st.title("➕ Register New Investment")
with st.form("investment_form", clear_on_submit=True):
    col1, col2 = st.columns(2)
    with col1:
        ticker = st.text_input("Ticker Symbol", placeholder="e.g. AAPL").strip()
        units = st.number_input("Units", min_value=0.0, format="%.4f")
        price = st.number_input("Purchase Price", min_value=0.0)
    with col2:
        purchase_date = st.date_input("Date", value=datetime.now())
        country = st.selectbox("Country", ["USA", "AUS", "IND"])
        currency = st.selectbox("Currency", ["USD", "AUD", "INR"])

    if st.form_submit_button("Add Manually"):
        if ticker and add_investment(ticker, units, price, purchase_date.strftime('%Y-%m-%d'), country, currency):
            st.success(f"Added {ticker}!")

st.divider()

# SECTION B: GMAIL AUTOMATION
st.subheader("📧 Gmail Trade Importer")
st.write("Scan your inbox for CMC Markets buy orders.")

if st.button("🔍 Sync with Gmail"):
    with st.spinner("Fetching emails..."):
        # REUSE: fetch_emails_for_sender handles auth and retrieval in one go
        messages = fetch_emails_for_sender(
            sender='brokingservice@cmcmarkets.com.au',
            scopes= default_scope
            )
        if messages:
            calc = DividendCalculator(DB_PATH)
            trades = calc.extract_trade_data(messages)
            st.session_state['pending_trades'] = pd.DataFrame(trades)
            st.success(f"Found {len(trades)} relevant orders.")
        else:
            st.warning("No new buy orders found.")

# SECTION C: APPROVAL TABLE
if 'pending_trades' in st.session_state:
    df = st.session_state['pending_trades']
    
    st.write("### Review & Approve Extracts")
    
    def color_status(val):
        return 'color: red' if "Already Exists" in val else 'color: green'

    event = st.dataframe(
        df.style.map(color_status, subset=['Status']),
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="multi-row"
    )

    selected_indices = event.selection.rows
    if selected_indices:
        if st.button(f"✅ Import {len(selected_indices)} Selected Trades"):
            approved_df = df.iloc[selected_indices]
            success_count = 0
            
            for _, row in approved_df.iterrows():
                # Map Email data to your DB columns
                if add_investment(row['Ticker'], row['Units'], row['Price'], row['Date'], "AUS", row['Currency']):
                    success_count += 1
            
            st.success(f"Successfully imported {success_count} trades!")
            del st.session_state['pending_trades']
            st.rerun()
