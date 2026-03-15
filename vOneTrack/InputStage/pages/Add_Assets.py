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
from googleapi import fetch_emails_for_sender, create_google_service, get_messages_from_sender
from Calculate_dividend import DividendCalculator
from Portfolio_updater import PortfolioUpdater 

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
        """, (
            ticker.upper(),  # 1
            units,           # 2
            price,           # 3
            purchase_value,  # 4 
            date,            # 5
            country,         # 6
            currency,        # 7
            units            # 8
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Error updating database: {e}")
        return False

def run_sync():
    # 1. Setup paths
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir) 
    creds_path = os.path.join(parent_dir, 'Secret', 'client_secret.json')
    scopes = ['https://www.googleapis.com/auth/gmail.readonly']
    
    # 2. Define your target accounts
    # These names will be used to create 'token_id1.json' and 'token_id2.json'
    accounts = ['id1', 'id2'] 
    
    all_data = []

    for account_id in accounts:
        print(f"--- Syncing Account: {account_id} ---")
        
        # Create a unique token file path for this ID
        this_token = os.path.join(parent_dir, 'Secret', f'token_{account_id}.json')
        
        # 3. Get the service (will trigger browser login ONLY if the token file is missing)
        service = create_google_service(
            credentials_path=creds_path,
            token_path=this_token,
            scopes=scopes
        )
        
        # 4. Fetch and process messages
        messages = get_messages_from_sender(service, 'brokingservice@cmcmarkets.com.au')
        all_data.extend(messages)
        print(f"Success: Found {len(messages)} messages for {account_id}")

    return all_data

#if __name__ == "__main__":
    #final_assets = run_sync()

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
st.subheader("📧 Trade Importer")
st.write("Scan your inbox for CMC Markets buy orders.")

if st.button("🔍 Sync with mail"):
    with st.spinner("Fetching emails from all accounts..."):
        # CALL your new multi-account function
        messages = run_sync() 
        
        if messages:
            calc = DividendCalculator(DB_PATH)
            # This is where the magic "mapping" happens
            #trades = calc.extract_trade_data(messages) 
            st.session_state['pending_trades'] = pd.DataFrame(calc.extract_trade_data(messages))
            st.success(f"Found {len(st.session_state['pending_trades'])} trades.")
        else:
            st.warning("No new buy orders found")

# SECTION C: APPROVAL TABLE
if 'pending_trades' in st.session_state:
    df = st.session_state['pending_trades']
    
    st.write("### Review & Approve Extracts")
    
    event = st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="multi-row"
    )

    selected_indices = event.selection.rows
    
    # Only show the button if rows are actually selected
    if selected_indices:
        if st.button(f"✅ Import {len(selected_indices)} Selected Trades"):
            approved_df = df.iloc[selected_indices]
            success_count = 0 

            for _, row in approved_df.iterrows():
                if add_investment(row['Ticker'], row['Units'], row['Price'], row['Date'], "AUS", row['Currency']):
                    success_count += 1
            
            if success_count > 0:
                with st.spinner("🔄 Syncing live values for new assets..."):
                    updater = PortfolioUpdater(db_path=DB_PATH) # Reusing your existing global sync function
                    updater.refresh_live_prices()
                st.success(f"Successfully imported {success_count} trades and updated live prices!")
                # Use a toast or a persistent message before rerunning

                # Remove the data so the table goes away
                del st.session_state['pending_trades']
                # Rerun to refresh the UI and clear the table
                st.rerun()
