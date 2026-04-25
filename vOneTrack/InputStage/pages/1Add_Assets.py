import streamlit as st
import psycopg2
import os
import sys
import pandas as pd
import plotly.express as px
from datetime import datetime, date
from sqlalchemy import create_engine
import urllib.parse
import re

#Scope for the GmailService
default_scope = ['https://www.googleapis.com/auth/gmail.readonly']

# 1. SETUP PATHS & IMPORTS
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from googleapi import create_google_service, get_messages_from_sender
from Calculate_dividend import DividendCalculator
from Portfolio_updater import PortfolioUpdater 

def get_engine():
    """Utility to create a SQLAlchemy engine to resolve Pandas UserWarnings."""
    user = urllib.parse.quote_plus(st.secrets['supabase']['user'])
    password = urllib.parse.quote_plus(st.secrets['supabase']['password'])
    host = st.secrets['supabase']['host']
    port = st.secrets['supabase']['port']
    database = st.secrets['supabase']['database']
    db_url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"
    return create_engine(db_url)

# --- 2. DATABASE LOGIC ---
def init_db_sequences():
    """Synchronizes all table sequences to prevent UniqueViolation (duplicate key) errors."""
    conn = psycopg2.connect(**st.secrets["supabase"])
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS "Super_Tracking" (
            "row_id" SERIAL PRIMARY KEY,
            "super_name" TEXT NOT NULL,
            "recorded_date" DATE NOT NULL,
            "value_aud" REAL NOT NULL,
            "created_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Comprehensive sequence sync for all primary tables
    sync_targets = [
        ('public."Super_Tracking"', 'row_id'),
        ('public."Investment"', 'id'),
        ('public."Dividends"', 'id')
    ]
    
    for table, col in sync_targets:
        try:
            cursor.execute(f"""
                SELECT setval(pg_get_serial_sequence('{table}', '{col}'), 
                              COALESCE((SELECT MAX("{col}") FROM {table}), 0) + 1, 
                              false);
            """)
        except Exception:
            pass # Handle cases where tables might not be initialized yet
            
    conn.commit()
    conn.close()

def add_investment(ticker, units, price, date, country, currency):
    init_db_sequences() # Sync before manual insert
    purchase_value = units * price
    try:
        conn = psycopg2.connect(**st.secrets["supabase"])
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO "Investment" (
                "Ticker", "Units", "Purchase_Price", "Purchase_Value", 
                "Purchase_Date", "Country", "Currency", "Remain_Balance",
                "Live_Price", "Live_Value", "Capital_Gain_Value", "Capital_Gain_Percent", "Investment_Type"
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, 0, 0, 0, 'Equity')
        """, (ticker.upper(), units, price, purchase_value, date, country, currency, units))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Error: {e}")
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
    
    return {
        "data": all_data,
    "service": service
    }

#if __name__ == "__main__":
    #final_assets = run_sync()


def save_super_entry(name, r_date, value):
    init_db_sequences() # Sync before manual insert
    try:
        conn = psycopg2.connect(**st.secrets["supabase"])
        cursor = conn.cursor()
        cursor.execute('INSERT INTO "Super_Tracking" ("super_name", "recorded_date", "value_aud") VALUES (%s, %s, %s)', (name, r_date, value))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Error saving super entry: {e}")
        return False

def get_super_history():
    engine = get_engine()
    try:
        df = pd.read_sql_query('SELECT * FROM "Super_Tracking" ORDER BY "recorded_date" ASC', engine)
    except:
        df = pd.DataFrame()
    return df

def clean_currency_string(value):
    """Removes ' USD', ' AUD', commas, and spaces to return a clean float."""
    if pd.isna(value) or value == "":
        return 0.0
    if isinstance(value, str):
        # Keeps only digits (0-9) and the decimal point (.)
        # This turns '132.8500 USD' into '132.8500'
        cleaned = re.sub(r'[^0-9.]', '', value)
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
    return float(value)

def map_cmc_csv(df):
    mapped_rows = []
    
    for _, row in df.iterrows():
        # ... (your existing Ticker/Country/Currency logic) ...

        mapped_entry = {
            "Ticker": ticker,
            "Units": clean_currency_string(row['Quantity']),
            "Purchase_Price": clean_currency_string(row['Price']),
            "Avg_Purchase_Price": clean_currency_string(row['Avg Price']),
            "Exchange_Rate": clean_currency_string(row['Exch Rate']),
            "Purchase_Value": clean_currency_string(row['Consideration']),
            "Purchase_Date": pd.to_datetime(row['Trade Date'], dayfirst=True).strftime('%Y-%m-%d'),
            "Country": country,
            "Currency": currency,
            "Remain_Balance": clean_currency_string(row['Quantity']),
            
            # --- ADD THESE MISSING COLUMNS TO SATISFY DATABASE CONSTRAINTS ---
            "Live_Price": 0.0,
            "Live_Value": 0.0,
            "Capital_Gain_Value": 0.0,
            "Capital_Gain_Percent": 0.0,
            "Investment_Type": "Equity"
        }
        mapped_rows.append(mapped_entry)
        
    return pd.DataFrame(mapped_rows)

def map_Vanguard_csv(df):
    mapped_rows = []
    
    for _, row in df.iterrows():
        ticker = row['Product ID'].strip().upper()
        country = "AUS" if len(ticker) <= 4 else "USA"
        currency = "AUD" if country == "AUS" else "USD"
        # ... (your existing Ticker/Country/Currency logic) ...
        #'Product ID', 'Trade Date', 'Value', 'Unit Price', 'Quantity', 'Product Type'
        mapped_entry = {
            "Ticker": row['Product ID'],
            "Units": clean_currency_string(row['Quantity']),
            "Purchase_Price": clean_currency_string(row['Unit Price']),
            "Purchase_Value": clean_currency_string(row['Value']),
            "Purchase_Date": pd.to_datetime(row['Trade Date'], dayfirst=True).strftime('%Y-%m-%d'),
            "Country": country,
            "Currency": currency,
            "Remain_Balance": clean_currency_string(row['Quantity']),
            
            # --- ADD THESE MISSING COLUMNS TO SATISFY DATABASE CONSTRAINTS ---
            "Live_Price": 0.0,
            "Live_Value": 0.0,
            "Capital_Gain_Value": 0.0,
            "Capital_Gain_Percent": 0.0,
            "Investment_Type": row['Product Type']  # Default value - adjust based on 'Product Type' if needed
        }
        mapped_rows.append(mapped_entry)    
        
    return pd.DataFrame(mapped_rows)

init_db_sequences()

# --- 3. UI CONFIGURATION ---
st.set_page_config(page_title="Asset Console", layout="wide", page_icon="💹")
st.title("💼 Portfolio Management Console")

# Create Main Tabs
tab_trading, tab_super = st.tabs(["📉 Trading Desk (Stocks/ETFs)", "🛡️ Superannuation Vault"])

# --- TAB 1: TRADING DESK (Manual + Email Intelligence) ---
with tab_trading:
    # --- Part A: Manual Form ---
    st.subheader("⌨️ Manual Trade Entry")
    with st.form("investment_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            ticker = st.text_input("Ticker Symbol", placeholder="e.g. NVDA")
            units = st.number_input("Units", min_value=0.0, format="%.0f")
        with c2:
            price = st.number_input("Purchase Price (Local)", min_value=0.0)
            purchase_date = st.date_input("Trade Date", value=datetime.now())
        with c3:
            country = st.selectbox("Market Country", ["USA", "AUS", "IND"])
            currency = st.selectbox("Local Currency", ["USD", "AUD", "INR"])

        if st.form_submit_button("🚀 Record Manual Trade", use_container_width=True):
            if ticker and units > 0:
                 # Step 1: Save to DB
                success = add_investment(ticker, units, price, purchase_date.strftime('%Y-%m-%d'), country, currency)
            
                if success:
                    # Step 2: Trigger Live Calculation
                    with st.spinner(f"Fetching live price for {ticker.upper()}..."):
                        try:
                            updater = PortfolioUpdater()
                            updater.refresh_live_prices()
                            st.toast(f"✅ {ticker.upper()} added with Live Data!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Trade saved, but Live Update failed: {e}")
            else:
                st.warning("Ticker and Units are required.")

    st.divider()

# --- Part B: Unified Broker Intelligence ---
st.subheader("📁 Intelligence: Broker Import")
st.caption("Select your broker and upload the trade confirmation CSV.")

# 1. User Input Parameters
broker_choice = st.selectbox("Select Broker", ["CMC Markets", "Vanguard Australia"], key="broker_selector")
uploaded_file = st.file_uploader("Upload Trade CSV", type="csv", key="broker_csv_uploader")

if uploaded_file:
    try:
        raw_df = pd.read_csv(uploaded_file)
        
        if st.button("🛠️ Map & Preview Trades", use_container_width=True):
            # --- ROUTING LOGIC ---
            if broker_choice == "CMC Markets":
                required = ['AsxCode', 'Trade Date', 'Consideration', 'Exch Rate', 'Avg Price', 'Price', 'Quantity']
                if all(col in raw_df.columns for col in required):
                    st.session_state['pending_trades'] = map_cmc_csv(raw_df)
                    st.success(f"Mapped {len(raw_df)} CMC trades.")
                else:
                    st.error("CSV headers don't match CMC format. Check your export.")

            elif broker_choice == "Vanguard Australia":
                required = ['Product ID', 'Trade Date', 'Value', 'Unit Price', 'Quantity', 'Product Type']
                if all(col in raw_df.columns for col in required):
                    st.session_state['pending_trades'] = map_Vanguard_csv(raw_df)
                    st.success(f"Mapped {len(raw_df)} Vanguard trades.")
                else:
                    st.error("CSV headers don't match Vanguard format. Check your export.")
    except Exception as e:
        st.error(f"Failed to read file: {e}")

# --- 2. Review and Batch Import (Shared for all brokers) ---
if 'pending_trades' in st.session_state:
    df_pending = st.session_state['pending_trades']
    st.write(f"### Review {broker_choice} Trades")
    st.dataframe(df_pending, use_container_width=True, hide_index=True)
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🚀 Import All to Database", type="primary", use_container_width=True):
             try:
                engine = get_engine()

                # Step 1: Batch Save CSV data
                with engine.connect() as conn:
                    # Use correct case for 'Investment'
                    df_pending.to_sql('Investment', conn, if_exists='append', index=False, schema='public')
                
                # Sync sequences immediately after batch import to heal the ID counter
                init_db_sequences()

                # Step 2: Batch Refresh all prices (Replaces 0.0s with real numbers)
                with st.spinner("Synchronising with Market Data..."):
                    updater = PortfolioUpdater()
                    updater.refresh_live_prices()
                    
                st.toast("✅ All trades imported and prices updated!")
                del st.session_state['pending_trades']
                st.rerun()
             except Exception as e:
                st.error(f"Critical Import Error: {e}")
    with col2:
        if st.button("❌ Clear/Cancel", use_container_width=True):
            del st.session_state['pending_trades']
            st.rerun()

# --- TAB 2: SUPERANNUATION VAULT ---
with tab_super:
    super_data = get_super_history()
    
    # Header Metrics
    m1, m2 = st.columns(2)
    latest_combined_super_balance=super_data.sort_values('recorded_date').drop_duplicates('super_name', keep='last')['value_aud'].sum()
    latest_val = latest_combined_super_balance if not super_data.empty else 0
    m1.metric("🏦 Current Super Balance", f"${latest_val:,.2f}")
    if len(super_data) > 1:
        prev_val = super_data['value_aud'].iloc[-2]
        change = latest_val - prev_val
        m2.metric("📈 Last Growth Step", f"${change:,.2f}", delta=f"${change:,.2f}")

    st.subheader("📝 Log New Balance Check")
    dropdown_options = ["BRIGHTER SUPER", "PLUM SUPER"]

    with st.form("super_form", clear_on_submit=True):
        sc1, sc2, sc3 = st.columns(3)
        with sc1:
            selected_option = st.selectbox("Select Super Fund", options=dropdown_options)
        with sc2:
            s_date = st.date_input("Date Recorded", value=date.today())
        with sc3:
            s_value = st.number_input("Balance (AUD)", min_value=0.0)
        
        if st.form_submit_button("💾 Save Balance to History", use_container_width=True):
            if selected_option and s_value > 0:
                if save_super_entry(selected_option, s_date.strftime('%Y-%m-%d'), s_value):
                    st.toast("Balance recorded!")
                    st.rerun()

    if not super_data.empty:
        st.divider()
        st.subheader("📊 Visual Growth Trend")
        # Ensure proper types for plotting
        super_data['recorded_date'] = pd.to_datetime(super_data['recorded_date'])
        super_data = super_data.sort_values("recorded_date")

        fig = px.line(super_data, x="recorded_date", y="value_aud", color="super_name", markers=True, template="plotly_white")
        fig.update_layout(yaxis=dict(tickprefix="$", tickformat=",.2f"), margin=dict(l=0, r=0, t=30, b=0))
        st.plotly_chart(fig, use_container_width=True)
        
        with st.expander("📂 View Full Audit Log"):
            st.dataframe(super_data.sort_values("recorded_date", ascending=False), use_container_width=True, hide_index=True)
