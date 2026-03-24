import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import yfinance as yf
from datetime import datetime
import threading
import time
import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Internal Imports (Ensure these files exist in your folder)
from Portfolio_updater import PortfolioUpdater 
from uploadtoGSfromDB import upload_db_to_sheet
from utils import show_sync_status  # From your new InputStage/pages/utils.py

# --- 1. BACKGROUND SYNC ENGINE ---
if 'sync_started' not in st.session_state:
    updater = PortfolioUpdater("onetrack.db")
    # daemon=True ensures the thread closes when the app stops
    thread = threading.Thread(target=updater.run_continuous_sync, args=(300,), daemon=True)
    thread.start()
    st.session_state.sync_started = True

# --- 2. PAGE CONFIG & UI STATUS ---
st.set_page_config(page_title="Net Worth Tracker", layout="wide")
show_sync_status() # Displays the Green Dot in Sidebar

# --- 3. DATA FETCHING ---
@st.cache_data(ttl=3600)
def get_portfolio_with_history(df):
    """Fetches last 7 days of prices for sparklines."""
    history_sparklines = []
    for _, row in df.iterrows():
        ticker = row['Ticker']
        country = row['Country']
        symbol = f"{ticker}.AX" if country == "AUS" else (f"{ticker}.BO" if country == "IND" else ticker)
        try:
            h = yf.download(symbol, period="7d", interval="1d", progress=False)['Close']
            history_sparklines.append(h.tolist())
        except:
            history_sparklines.append([]) 
    df['7D Trend'] = history_sparklines
    return df

def get_investment_data():
    conn = sqlite3.connect("onetrack.db")
    query = """
    SELECT 
        Ticker, 
        Country, 
        SUM(Units) as Units, 
        SUM(Purchase_Value) as Total_Cost_AUD,
        MAX(Live_Price) as Live_Price,
        MIN(Purchase_Date) as Oldest_Purchase,
        MAX(Purchase_Date) as Newest_Purchase
    FROM Investment 
    GROUP BY Ticker, Country
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

# --- 4. CALCULATION & STYLING ---
def color_returns(val):
    if isinstance(val, (int, float)):
        return f'color: {"#d62728" if val < 0 else "#2ca02c"}; font-weight: bold;'
    return ''

def show_performance_summary(df):
    st.subheader("🏢 Regional Performance Summary (in AUD)")
    updater = PortfolioUpdater("onetrack.db")
    rates = updater.get_live_exchange_rates()
    st.caption(f"💱 Live Rates Used: USD/AUD: {rates.get('USA', 1.54):.4f} | INR/AUD: {rates.get('IND', 0.018):.4f}")

    # --- MATH ENGINE (Updates the main df) ---
    df['Rate'] = df['Country'].map(rates).fillna(1.0)
    df['Cost_AUD'] = df['Total_Cost_AUD'] 
    df['Value_AUD'] = (df['Units'] * df['Live_Price']) * df['Rate']
    
    # These two columns MUST be added to df here
    df['Profit_AUD'] = df['Value_AUD'] - df['Cost_AUD']
    df['Return_Pct'] = (df['Profit_AUD'] / df['Cost_AUD']) * 100
    
    # 1. Create the small Summary Table for the Top of the page
    summary = df.groupby('Country').agg({'Value_AUD': 'sum', 'Cost_AUD': 'sum'}).reset_index()
    summary.columns = ['Region', 'Total Asset Value', 'Total Cost']

    # 2. Subtotal & Grand Total Rows
    ex_ind_mask = summary['Region'].isin(['AUS', 'USA'])
    sub_val, sub_cost = summary.loc[ex_ind_mask, 'Total Asset Value'].sum(), summary.loc[ex_ind_mask, 'Total Cost'].sum()
    sub_row = pd.DataFrame([['SUBTOTAL (AUS + USA)', sub_val, sub_cost]], columns=summary.columns)
    
    tot_val, tot_cost = summary['Total Asset Value'].sum(), summary['Total Cost'].sum()
    tot_row = pd.DataFrame([['TOTAL PORTFOLIO', tot_val, tot_cost]], columns=summary.columns)

    summary = pd.concat([summary, sub_row, tot_row], ignore_index=True)
    summary['Total Return ($)'] = summary['Total Asset Value'] - summary['Total Cost']
    summary['Total Return (%)'] = (summary['Total Return ($)'] / summary['Total Cost']) * 100

    st.table(summary.style.format({
        'Total Asset Value': '${:,.2f}', 'Total Cost': '${:,.2f}',
        'Total Return ($)': '${:,.2f}', 'Total Return (%)': '{:.2f}%'
    }))
    
    return df # This ensures Profit_AUD and Return_Pct are passed back out

# --- 5. VISUALS ---
def show_stacked_growth_bar(df):
    st.divider()
    st.subheader("📊 Ticker Value: Invested vs. Growth (AUD)")
    df_sorted = df.sort_values('Value_AUD', ascending=False)
    fig = go.Figure()
    fig.add_trace(go.Bar(x=df_sorted['Ticker'], y=df_sorted['Cost_AUD'], name='Invested', marker_color='#1f77b4'))
    #fig.add_trace(go.Bar(x=df_sorted['Ticker'], y=df_sorted['Profit_AUD'], name='Growth', marker_color='#2ca02c'))
    fig.add_trace(go.Bar(x=df_sorted['Ticker'], y=df_sorted['Profit_AUD'], name='Growth', marker_color='#2ca02c',
                         text=df_sorted['Return_Pct'].round(1).astype(str) + "%", textposition='outside'))
    fig.update_layout(barmode='stack', template="plotly_white", yaxis=dict(tickprefix="$"))
    st.plotly_chart(fig, use_container_width=True)

# --- MAIN UI ---
st.title("💰 Net Worth & Investment Tracker")

c1, c2 = st.columns(2)
with c1:
    if st.button("🔄 Refresh Local Prices"):
        with st.spinner("Syncing..."):
            updater.refresh_live_prices()
        st.rerun()
with c2:
    if st.button("☁️ Push to Google Sheets"):
        success, msg = upload_db_to_sheet()
        st.success(msg) if success else st.error(msg)

df_raw = get_investment_data()

if not df_raw.empty:
    df = show_performance_summary(df_raw)

    # Date Logic
    today = datetime.now()
    df['Oldest_P'] = pd.to_datetime(df['Oldest_Purchase'], dayfirst=True, format='mixed', errors='coerce')
    df['Newest_P'] = pd.to_datetime(df['Newest_Purchase'], dayfirst=True, format='mixed', errors='coerce')

    # Calculate years as a decimal
    df['Age_Years'] = (today - df['Oldest_P']).dt.days / 365.25

    # Format for display (e.g., "1.4 years")
    df['Age (Years)'] = df['Age_Years'].map(lambda x: f"{x:.1f} years" if pd.notnull(x) else "N/A")

    df = get_portfolio_with_history(df)

    st.subheader("📊 Consolidated Portfolio Analytics")
    st.dataframe(
        df.style.applymap(color_returns, subset=['Profit_AUD', 'Return_Pct']),
        column_config={
            "7D Trend": st.column_config.LineChartColumn("7D History", width="medium"),
            "Live_Price": st.column_config.NumberColumn("Live Price (Local)", format="$%.2f"),
            "Value_AUD": st.column_config.NumberColumn("Market Value (AUD)", format="$%.2f"),
            "Profit_AUD": st.column_config.NumberColumn("Profit (AUD)", format="$%.2f"),
            "Return_Pct": st.column_config.NumberColumn("Return %", format="%.2f%%"),
            "Age (Years)": st.column_config.TextColumn("Holding Period", help="Years since first purchase"),
        },
        column_order=("Ticker", "7D Trend", "Units", "Live_Price", "Value_AUD", "Profit_AUD", "Return_Pct", "Age (Years)"),
        hide_index=True, use_container_width=True
    )

    show_stacked_growth_bar(df)
    
    st.subheader("🥧 Asset Distribution")
    st.plotly_chart(px.pie(df, values='Value_AUD', names='Country', hole=0.4), use_container_width=True)
else:
    st.info("No data found.")
