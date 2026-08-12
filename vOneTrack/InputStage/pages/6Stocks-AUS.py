import streamlit as st
import psycopg2
import pandas as pd
import yfinance as yf
from datetime import datetime
from sqlalchemy import create_engine
import urllib.parse
import os
import sys

# --- 1. PATH SETUP ---
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from auth import check_auth, logout
check_auth()
logout()
from utils import show_sync_status
from Portfolio_updater import PortfolioUpdater

# --- 2. CONFIGURATION ---

# --- 3. DATA FETCHING ---
def get_engine():
    """Utility to create a SQLAlchemy engine to resolve Pandas UserWarnings."""
    user = urllib.parse.quote_plus(st.secrets['supabase']['user'])
    password = urllib.parse.quote_plus(st.secrets['supabase']['password'])
    host = st.secrets['supabase']['host']
    port = st.secrets['supabase']['port']
    database = st.secrets['supabase']['database']
    db_url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"
    return create_engine(db_url)

def get_aus_stock_data():
    engine = get_engine()
    query = """
    SELECT "Ticker", SUM("Units") as "Units", SUM("Purchase_Value") as "Total_Cost_AUD",
           MAX("Live_Price") as "Live_Price", MIN("Purchase_Date") as "First_Buy_Date"
    FROM "Investment" 
    WHERE "Country" = 'AUS' AND "Investment_Type" <> 'ETF'
    GROUP BY "Ticker"
    """
    df = pd.read_sql_query(query, engine)
    return df

@st.cache_data(ttl=3600)
def fetch_aus_sparklines(df):
    histories = []
    for ticker in df['Ticker']:
        try:
            # Suffix .AX for Australian Yahoo Finance tickers
            h = yf.download(f"{ticker}.AX", period="7d", interval="1d", progress=False)['Close']
            histories.append(h.tolist())
        except:
            histories.append([])
    df['7D Trend'] = histories
    return df

def color_metric(val):
    if isinstance(val, (int, float)):
        return f'color: {"#d62728" if val < 0 else "#2ca02c"}; font-weight: bold;'
    return ''

def get_detailed_aus_stock_rows():
    engine = get_engine()
    query = """
    SELECT "Ticker", "Purchase_Date", "Units", 
           "Purchase_Price", "Purchase_Value" as "Cost_AUD", 
           "Live_Price", "Account_Platform"
    FROM "Investment" 
    WHERE "Country" = 'AUS' AND "Investment_Type" <> 'ETF'
    ORDER BY "Purchase_Date" DESC
    """
    df = pd.read_sql_query(query, engine)
    return df

# --- 4. PAGE UI SETUP ---
st.set_page_config(page_title="AUS Stocks", layout="wide")
show_sync_status() # Sidebar Green Dot

st.title("🇦🇺 Australian Equity Analytics")
st.caption("Individual ASX Holdings performance in AUD")

# --- 5. EXECUTION & MATH ENGINE ---
df_raw = get_aus_stock_data()

if not df_raw.empty:
    # Math logic (Rate is 1.0 for AUD/AUD)
    df_raw['Current Value AUD'] = df_raw['Units'] * df_raw['Live_Price']
    df_raw['Total Return AUD ($)'] = df_raw['Current Value AUD'] - df_raw['Total_Cost_AUD']
    df_raw['Total Return (%)'] = (df_raw['Total Return AUD ($)'] / df_raw['Total_Cost_AUD']) * 100
    df_raw['Avg Price'] = df_raw['Total_Cost_AUD'] / df_raw['Units']
    
    # Growth Stats (CAGR)
    today = datetime.now()
    df_raw['First_Buy_P'] = pd.to_datetime(df_raw['First_Buy_Date'], dayfirst=True, format='mixed', errors='coerce')
    df_raw['Years_Held'] = (today - df_raw['First_Buy_P']).dt.days / 365.25
    df_raw['Est. Return/Year (%)'] = (((df_raw['Current Value AUD'] / df_raw['Total_Cost_AUD']) ** (1 / df_raw['Years_Held'])) - 1) * 100

    df = fetch_aus_sparklines(df_raw)

    # --- TOP LEVEL METRICS ---
    m1, m2, m3 = st.columns(3)
    
    total_val_au = df['Current Value AUD'].sum()
    total_cost_au = df['Total_Cost_AUD'].sum()
    total_profit_au = df['Total Return AUD ($)'].sum()
    
    m1.metric("Total AUS Portfolio (AUD)", f"${total_val_au:,.2f}")
    
    overall_ret_pct = (total_profit_au / total_cost_au * 100) if total_cost_au > 0 else 0
    m2.metric("Total AUS Profit (AUD)", f"${total_profit_au:,.2f}", delta=f"{overall_ret_pct:.2f}%")
    
    m3.metric("Avg Annual Growth (CAGR)", f"{df['Est. Return/Year (%)'].mean():.2f}%")
    st.divider()

    # --- DATA TABLE ---
    st.dataframe(
        df.style.map(color_metric, subset=['Total Return AUD ($)', 'Total Return (%)', 'Est. Return/Year (%)']),
        column_config={
            "7D Trend": st.column_config.LineChartColumn("7D History", width="medium"),
            "Units": st.column_config.NumberColumn("Units", format="%.0f"),
            "Live_Price": st.column_config.NumberColumn("Live Price", format="$%.2f"),
            "Current Value AUD": st.column_config.NumberColumn("Market Value (AUD)", format="$%.2f"),
            "Total Return AUD ($)": st.column_config.NumberColumn("Profit (AUD)", format="$%.2f"),
            "Total Return (%)": st.column_config.NumberColumn("Return %", format="%.2f%%"),
            "Est. Return/Year (%)": st.column_config.NumberColumn("CAGR", format="%.2f%%"),
        },
        column_order=(
            "Ticker", "7D Trend", "Units", "Avg Price", "Live_Price", 
            "Current Value AUD", "Total Return AUD ($)", "Total Return (%)", "Est. Return/Year (%)"
        ),
        hide_index=True,
        width='stretch'
    )

    st.divider()
st.subheader("📄 Detailed Australian Transaction History")
df_details = get_detailed_aus_stock_rows()

if not df_details.empty:
    # No FX conversion needed for AUS stocks
    df_details['Value_AUD'] = df_details['Units'] * df_details['Live_Price']
    df_details['Profit_AUD'] = df_details['Value_AUD'] - df_details['Cost_AUD']
    df_details['Growth_%'] = (df_details['Profit_AUD'] / df_details['Cost_AUD']) * 100

    st.dataframe(
        df_details.style.map(color_metric, subset=['Profit_AUD', 'Growth_%']),
        column_config={
            "Purchase_Date": st.column_config.DateColumn("Date"),
            "Units": st.column_config.NumberColumn("Qty", format="%.0f"),
            "Purchase_Price": st.column_config.NumberColumn("Buy Price", format="$%.2f"),
            "Cost_AUD": st.column_config.NumberColumn("Cost (AUD)", format="$%.2f"),
            "Value_AUD": st.column_config.NumberColumn("Value (AUD)", format="$%.2f"),
            "Profit_AUD": st.column_config.NumberColumn("P/L", format="$%.2f"),
            "Growth_%": st.column_config.NumberColumn("%", format="%.2f%%"),
        },
        column_order=("Ticker", "Purchase_Date", "Units", "Purchase_Price", "Cost_AUD", "Value_AUD", "Profit_AUD", "Growth_%"),
        hide_index=True, width='stretch'
    )
else:
    st.info("No Australian Stock data found.")
