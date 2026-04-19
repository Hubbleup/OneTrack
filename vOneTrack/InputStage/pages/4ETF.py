import streamlit as st
import sqlite3
import pandas as pd
import yfinance as yf
from datetime import datetime
import os
import sys

# --- 1. PATH SETUP (To find utils.py in the same folder) ---
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from utils import show_sync_status
from Portfolio_updater import PortfolioUpdater

# --- 2. CONFIGURATION ---
DB_PATH = "onetrack.db"

# --- 3. DATA FETCHING FUNCTIONS (Defined BEFORE calling) ---
def get_consolidated_etf_data():
    conn = sqlite3.connect(DB_PATH)
    query = """
    SELECT 
        Ticker, 
        Country, 
        SUM(Units) as Units, 
        SUM(Purchase_Value) as Total_Cost_AUD,
        MAX(Live_Price) as Live_Price,
        MIN(Purchase_Date) as First_Buy_Date
    FROM Investment 
    WHERE Investment_Type = 'ETF'
    GROUP BY Ticker
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

@st.cache_data(ttl=3600)
def fetch_sparklines(df):
    histories = []
    for _, row in df.iterrows():
        symbol = f"{row['Ticker']}.AX" if row['Country'] == "AUS" else row['Ticker']
        try:
            h = yf.download(symbol, period="7d", interval="1d", progress=False)['Close']
            histories.append(h.tolist())
        except:
            histories.append([])
    df['7D Trend'] = histories
    return df

def get_detailed_etf_rows():
    conn = sqlite3.connect(DB_PATH)
    query = """
    SELECT 
        Ticker, Country, Purchase_Date, Units, 
        Purchase_Price, Purchase_Value as Cost_AUD, 
        Live_Price, Account_Platform
    FROM Investment 
    WHERE Investment_Type = 'ETF'
    ORDER BY Purchase_Date DESC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df  

def color_metric(val):
    if isinstance(val, (int, float)):
        return f'color: {"#d62728" if val < 0 else "#2ca02c"}; font-weight: bold;'
    return ''

# --- 4. PAGE UI SETUP ---
st.set_page_config(page_title="ETF Analytics", layout="wide")
show_sync_status() # Sidebar Green Dot

st.title("📊 ETF Portfolio Analytics")
st.caption("Consolidated Performance Metrics with Live AUD Conversion")

# --- 5. EXECUTION & MATH ---
df_raw = get_consolidated_etf_data()

if not df_raw.empty:
    updater = PortfolioUpdater(DB_PATH)
    rates = updater.get_live_exchange_rates()
    
    # --- AUD CONVERSION ENGINE ---
    df_raw['Rate'] = df_raw['Country'].map(rates).fillna(1.0)
    
    # Value = (Units * Local_Price * FX_Rate)
    df_raw['Current Value AUD'] = (df_raw['Units'] * df_raw['Live_Price']) * df_raw['Rate']
    
    # Profit = Value_AUD - Cost_AUD (DB stores cost in AUD)
    df_raw['Total Return ($)'] = df_raw['Current Value AUD'] - df_raw['Total_Cost_AUD']
    df_raw['Total Return (%)'] = (df_raw['Total Return ($)'] / df_raw['Total_Cost_AUD']) * 100
    df_raw['Avg Price (Local)'] = df_raw['Total_Cost_AUD'] / df_raw['Units'] # Note: This is an AUD cost per local unit
    
    # Growth Calculation
    today = datetime.now()
    df_raw['First_Buy_P'] = pd.to_datetime(df_raw['First_Buy_Date'], dayfirst=True, format='mixed', errors='coerce')
    df_raw['Years_Held'] = (today - df_raw['First_Buy_P']).dt.days / 365.25
    df_raw['Est. Return/Year (%)'] = (((df_raw['Current Value AUD'] / df_raw['Total_Cost_AUD']) ** (1 / df_raw['Years_Held'])) - 1) * 100

    df = fetch_sparklines(df_raw)

    # --- TOP LEVEL METRICS ---
    m1, m2, m3 = st.columns(3)
    m1.metric("Total ETF Value (AUD)", f"${df['Current Value AUD'].sum():,.2f}")
    
    total_prof = df['Total Return ($)'].sum()
    total_cost = df['Total_Cost_AUD'].sum()
    m2.metric("Total ETF Profit (AUD)", f"${total_prof:,.2f}", 
              delta=f"{(total_prof / total_cost * 100):.2f}%")
    m3.metric("Avg Portfolio Growth (CAGR)", f"{df['Est. Return/Year (%)'].mean():.2f}%")
    
    st.divider()

    # --- CONSOLIDATED TABLE ---
    st.subheader("📋 Consolidated ETF Summary (AUD converted)")
    st.dataframe(
        df.style.map(color_metric, subset=['Total Return ($)', 'Total Return (%)', 'Est. Return/Year (%)']),
        column_config={
            "Units": st.column_config.NumberColumn("Units", format="%.0f"),
            "7D Trend": st.column_config.LineChartColumn("7D History", width="medium"),
            "Live_Price": st.column_config.NumberColumn("Price (Local)", format="$%.2f"),
            "Current Value AUD": st.column_config.NumberColumn("Market Value (AUD)", format="$%.2f"),
            "Total Return ($)": st.column_config.NumberColumn("Profit (AUD)", format="$%.2f"),
            "Total Return (%)": st.column_config.NumberColumn("Return %", format="%.2f%%"),
            "Est. Return/Year (%)": st.column_config.NumberColumn("CAGR", format="%.2f%%"),
        },
        column_order=(
            "Ticker", "7D Trend", "Units", "Live_Price", "Current Value AUD",  
            "Total Return ($)", "Total Return (%)", "Est. Return/Year (%)"
        ),
        hide_index=True, use_container_width=True
    )

    # --- DETAILED TRANSACTION HISTORY ---
    st.divider()
    st.subheader("📄 Detailed ETF Transaction History")
    df_details = get_detailed_etf_rows()
    
    if not df_details.empty:
        # Apply FX to details as well
        df_details['Rate'] = df_details['Country'].map(rates).fillna(1.0)
        df_details['Value_AUD'] = (df_details['Units'] * df_details['Live_Price']) * df_details['Rate']
        df_details['Profit_AUD'] = df_details['Value_AUD'] - df_details['Cost_AUD']
        df_details['Growth_%'] = (df_details['Profit_AUD'] / df_details['Cost_AUD']) * 100

        st.dataframe(
            df_details.style.map(color_metric, subset=['Profit_AUD', 'Growth_%']),
            column_config={
                "Purchase_Date": st.column_config.DateColumn("Date"),
                "Units": st.column_config.NumberColumn("Qty", format="%.0f"),
                "Purchase_Price": st.column_config.NumberColumn("Buy (Local)", format="$%.2f"),
                "Cost_AUD": st.column_config.NumberColumn("Cost (AUD)", format="$%.2f"),
                "Value_AUD": st.column_config.NumberColumn("Value (AUD)", format="$%.2f"),
                "Profit_AUD": st.column_config.NumberColumn("P/L", format="$%.2f"),
                "Growth_%": st.column_config.NumberColumn("%", format="%.2f%%"),
            },
            column_order=("Ticker", "Purchase_Date", "Units", "Purchase_Price", "Cost_AUD", "Value_AUD", "Profit_AUD", "Growth_%"),
            hide_index=True, use_container_width=True
        )
else:
    st.info("No ETF data found.")
