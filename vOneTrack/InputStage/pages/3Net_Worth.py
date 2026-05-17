import streamlit as st
import psycopg2
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import yfinance as yf
from datetime import datetime
from sqlalchemy import create_engine
import urllib.parse
import threading
import os
import sys

# --- 1. SETUP & PATHS ---
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Internal Imports
from Portfolio_updater import PortfolioUpdater 
from uploadtoGSfromDB import upload_db_to_sheet
from utils import show_sync_status, get_db_engine

# --- 2. BACKGROUND SYNC ENGINE ---
if 'sync_started' not in st.session_state:
    updater = PortfolioUpdater()
    # daemon=True ensures the thread closes when the app stops
    thread = threading.Thread(target=updater.run_continuous_sync, args=(300,), daemon=True)
    thread.start()
    st.session_state.sync_started = True

# --- 3. PAGE CONFIG ---
st.set_page_config(page_title="Net Worth Tracker", layout="wide", page_icon="💹")
show_sync_status() 

# --- 4. DATA FETCHING FUNCTIONS ---

def get_engine():
    return get_db_engine()

@st.cache_data(ttl=3600)
def get_portfolio_with_history(df):
    """Fetches 7-day price history for sparkline charts."""
    history_sparklines = []
    for _, row in df.iterrows():
        ticker, country = row['Ticker'], row['Country']
        symbol = f"{ticker}.AX" if country == "AUS" else (f"{ticker}.BO" if country == "IND" else ticker)
        try:
            h = yf.download(symbol, period="7d", interval="1d", progress=False)['Close']
            history_sparklines.append(h.tolist())
        except:
            history_sparklines.append([]) 
    df['7D Trend'] = history_sparklines
    return df

def get_investment_data():
    """Aggregates investment data from SQLite."""
    engine = get_engine()
    query = """
    SELECT "Ticker", "Country", SUM("Units") as "Units", SUM("Purchase_Value") as "Total_Cost_AUD",
           MAX("Live_Price") as "Live_Price", MIN("Purchase_Date") as "Oldest_Purchase",
           MAX("Purchase_Date") as "Newest_Purchase"
    FROM "Investment" 
    WHERE "Remain_Balance" > 0 OR "Remain_Balance" IS NULL
    GROUP BY "Ticker", "Country"
    """
    df = pd.read_sql_query(query, engine)
    return df

def get_latest_super_balance():
    """Fetches the most recent balance for each super fund."""
    engine = get_engine()
    try:
        query = """
        SELECT SUM(value_aud) as "Total_Super" FROM (
            SELECT "value_aud", ROW_NUMBER() OVER (PARTITION BY "super_name" ORDER BY "recorded_date" DESC) as rn
            FROM "Super_Tracking"
        ) WHERE rn = 1
        """
        df = pd.read_sql_query(query, engine)
        return df['Total_Super'].iloc[0] if not df.empty and df['Total_Super'].iloc[0] is not None else 0.0
    except:
        return 0.0

# --- 5. PLOTTING & DISPLAY FUNCTIONS ---

def plot_ticker_performance(ticker, country):
    """Generates the 'Journey' chart showing price trend and purchase points."""
    engine = get_engine() # Use the SQLAlchemy engine
    trades = pd.read_sql(
        'SELECT "Purchase_Date", "Purchase_Price", "Units" FROM "Investment" WHERE "Ticker"=%s ORDER BY "Purchase_Date" ASC', 
        engine, params=(ticker,)
    )

    if trades.empty:
        return None

    trades['Purchase_Date'] = pd.to_datetime(trades['Purchase_Date'])
    start_date = trades['Purchase_Date'].min()
    yahoo_sym = f"{ticker}.AX" if country == "AUS" else ticker

    hist_data = yf.download(yahoo_sym, start=start_date, interval="1d", progress=False)
    if hist_data.empty:
        return None
        
    hist_df = hist_data['Close'].reset_index()
    hist_df.columns = ['Date', 'Close']

    fig = go.Figure()
    # Market Price Line
    fig.add_trace(go.Scatter(x=hist_df['Date'], y=hist_df['Close'], mode='lines', name='Price', line=dict(color='#2ca02c', width=2)))
    # Purchase Points
    fig.add_trace(go.Scatter(
        x=trades['Purchase_Date'], y=trades['Purchase_Price'], mode='markers', name='Buy',
        marker=dict(symbol='triangle-up', size=12, color='#1f77b4', line=dict(width=2, color='white')),
        text=trades['Units'].apply(lambda x: f"Bought {x:.0f} units"),
        hoverinfo="text+x+y"
    ))
    fig.update_layout(title=f"Performance Journey: {ticker}", template="plotly_white", hovermode="x unified")
    return fig

def show_performance_summary(df):
    """Displays the regional subtotal and net worth table."""
    st.subheader("🏢 Regional Performance Summary (in AUD)")
    updater = PortfolioUpdater()
    rates = updater.get_live_exchange_rates()
    
    df['Rate'] = df['Country'].map(rates).fillna(1.0)
    df['Cost_AUD'] = df['Total_Cost_AUD'] 
    df['Value_AUD'] = (df['Units'] * df['Live_Price']) * df['Rate']
    df['Profit_AUD'] = df['Value_AUD'] - df['Cost_AUD']
    df['Return_Pct'] = (df['Profit_AUD'] / df['Cost_AUD']) * 100
    
    summary = df.groupby('Country').agg({'Value_AUD': 'sum', 'Cost_AUD': 'sum'}).reset_index()
    summary.columns = ['Region', 'Total Asset Value', 'Total Cost']

    latest_super = get_latest_super_balance()
    super_row = pd.DataFrame([['SUPERANNUATION', latest_super, latest_super]], columns=summary.columns)
    
    total_val = summary['Total Asset Value'].sum() + latest_super
    total_cost = summary['Total Cost'].sum() + latest_super
    total_row = pd.DataFrame([['TOTAL NET WORTH', total_val, total_cost]], columns=summary.columns)

    summary = pd.concat([summary, super_row, total_row], ignore_index=True)
    summary['Total Return ($)'] = summary['Total Asset Value'] - summary['Total Cost']
    summary['Total Return (%)'] = (summary['Total Return ($)'] / summary['Total Cost']) * 100

    st.table(summary.style.format({
        'Total Asset Value': '${:,.2f}', 'Total Cost': '${:,.2f}',
        'Total Return ($)': '${:,.2f}', 'Total Return (%)': '{:.2f}%'
    }))
    return df

def show_stacked_growth_bar(df):
    """Displays bar chart of Invested vs Growth."""
    st.divider()
    st.subheader("📊 Ticker Value: Invested vs. Growth (AUD)")
    df_sorted = df.sort_values('Value_AUD', ascending=False)
    fig = go.Figure()
    fig.add_trace(go.Bar(x=df_sorted['Ticker'], y=df_sorted['Cost_AUD'], name='Invested', marker_color='#1f77b4'))
    fig.add_trace(go.Bar(x=df_sorted['Ticker'], y=df_sorted['Profit_AUD'], name='Growth', marker_color='#2ca02c',
                        text=df_sorted['Return_Pct'].round(1).astype(str) + "%", textposition='outside'))
    fig.update_layout(barmode='stack', template="plotly_white", yaxis=dict(tickprefix="$"))
    st.plotly_chart(fig, width='stretch')

# --- 6. MAIN EXECUTION & TABS ---

st.title("💰 Net Worth & Portfolio Analytics")

# Define Tabs
tab_overview, tab_analytics = st.tabs(["📊 Portfolio Overview", "📈 Ticker Performance Journey"])

# Data Preparation
df_raw = get_investment_data()

if not df_raw.empty:
    # --- TAB 1: PORTFOLIO OVERVIEW ---
    with tab_overview:
        df = show_performance_summary(df_raw)
        
        # Years Holding Period Calculation
        today = datetime.now()
        df['Oldest_P'] = pd.to_datetime(df['Oldest_Purchase'], errors='coerce')
        df['Age (Years)'] = ((today - df['Oldest_P']).dt.days / 365.25).fillna(0).map(lambda x: f"{x:.1f} years")

        # Get Sparkline Data
        with st.spinner("Loading market trends..."):
            df = get_portfolio_with_history(df)

        st.subheader("📊 Consolidated Portfolio Analytics")
        st.dataframe(
            df.style.map(lambda x: f'color: {"#d62728" if x < 0 else "#2ca02c"}; font-weight: bold;', subset=['Profit_AUD', 'Return_Pct']),
            column_config={
                "Units": st.column_config.NumberColumn("Units", format="%.0f"),
                "Live_Price": st.column_config.NumberColumn("Live Price", format="$%.2f"),
                "7D Trend": st.column_config.LineChartColumn("7D History"),
                "Value_AUD": st.column_config.NumberColumn("Value (AUD)", format="$%.2f"),
                "Profit_AUD": st.column_config.NumberColumn("Profit", format="$%.2f"),
                "Return_Pct": st.column_config.NumberColumn("Return %", format="%.2f%%"),
            },
            column_order=("Ticker", "7D Trend", "Units", "Live_Price", "Value_AUD", "Profit_AUD", "Return_Pct", "Age (Years)"),
            hide_index=True, width='stretch'
        )
        
        show_stacked_growth_bar(df)

    # --- TAB 2: TICKER PERFORMANCE JOURNEY ---
    with tab_analytics:
        st.subheader("🚀 Ticker Performance Journey")
        st.caption("Visualise price movement and purchase points from your first trade.")
        
        all_tickers = df_raw['Ticker'].unique().tolist()

        if all_tickers:
            selected = st.selectbox("Select Ticker to Analyse", all_tickers, key="trend_selector")
            
            # Fetch country for suffix logic
            ticker_info = df_raw[df_raw['Ticker'] == selected].iloc[0]
            
            with st.spinner(f"Fetching journey for {selected}..."):
                fig = plot_ticker_performance(selected, ticker_info['Country'])
            
            if fig:
                st.plotly_chart(fig, width='stretch')
            else:
                st.info(f"Market data for {selected} is currently unavailable.")
else:
    st.warning("No investment data found. Please add assets in the Input Stage.")

# Sidebar Actions
if st.sidebar.button("📤 Manual Sync to Google Sheets"):
    upload_db_to_sheet()
    st.sidebar.success("Sync complete!")
