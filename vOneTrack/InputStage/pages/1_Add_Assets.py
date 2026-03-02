import streamlit as st
import sqlite3
import os
from datetime import datetime

# Path to your database
DB_PATH = "/Users/nawinprabhujayaraman/Nawin/projects/OneTrack/vOneTrack/InputStage/onetrack.db"

def add_investment(ticker, units, price, date, country, currency):
    """Inserts a new investment record into the database."""
    purchase_value = units * price
    # Initial balance is same as units purchased
    remain_balance = units 
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Mapping to your Investment table columns
        cursor.execute("""
            INSERT INTO Investment (
                Ticker, Units, Purchase_Price, Purchase_Value, 
                Purchase_Date, Country, Currency, Remain_Balance,
                Live_Price, Live_Value, Capital_Gain_Value, Capital_Gain_Percent
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0)
        """, (ticker.upper(), units, price, purchase_value, date, country, currency, remain_balance))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Error updating database: {e}")
        return False

# --- UI Layout ---
st.set_page_config(page_title="Add Assets", layout="centered")
st.title("➕ Register New Investment")
st.write("Enter details below to add a new stock or ETF to your portfolio.")

# Form for user input
with st.form("investment_form", clear_on_submit=True):
    col1, col2 = st.columns(2)
    
    with col1:
        ticker = st.text_input("Ticker Symbol", placeholder="e.g. AAPL, VGS.AX").strip()
        units = st.number_input("Number of Units", min_value=0.0001, step=0.01, format="%.4f")
        price = st.number_input("Average Purchase Price", min_value=0.01, step=0.01)
        
    with col2:
        purchase_date = st.date_input("Purchase Date", value=datetime.now())
        country = st.selectbox("Country", ["USA", "AUS", "IND", "UK"])
        currency = st.selectbox("Currency", ["USD", "AUD", "INR", "GBP"])

    submitted = st.form_submit_button("Add to Portfolio")

    if submitted:
        if not ticker:
            st.error("Please enter a Ticker Symbol.")
        else:
            # Convert date to string for SQLite compatibility (YYYY-MM-DD)
            formatted_date = purchase_date.strftime('%Y-%m-%d')
            
            if add_investment(ticker, units, price, formatted_date, country, currency):
                st.success(f"✅ Successfully added {units} shares of {ticker.upper()}!")
                st.balloons()
