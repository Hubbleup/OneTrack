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
    SELECT "Ticker", "Country", SUM("Units") as "Units", SUM("Purchase_Value" * COALESCE("Exchange_Rate", 1.0)) as "Total_Cost_AUD",
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
    
    # Ensure IND rate is handled (approx fallback if updater missing it)
    if 'IND' not in rates:
        rates['IND'] = 0.018 # 1 INR ≈ 0.018 AUD

    df['Rate'] = df['Country'].map(rates).fillna(1.0)
    df['Cost_AUD'] = df['Total_Cost_AUD'] 
    df['Value_AUD'] = (df['Units'] * df['Live_Price']) * df['Rate']
    df['Profit_AUD'] = df['Value_AUD'] - df['Cost_AUD']
    df['Return_Pct'] = (df['Profit_AUD'] / df['Cost_AUD']) * 100
    
    # Calculate regional sums for investments
    investment_regional_summary = df.groupby('Country').agg(
        Total_Asset_Value=('Value_AUD', 'sum'),
        Total_Cost=('Cost_AUD', 'sum')
    ).reset_index()
    investment_regional_summary.rename(columns={'Country': 'Region'}, inplace=True)

    # Initialize list to hold all summary rows
    summary_rows_list = []

    # Add AUS and USA individual rows
    aus_usa_df = investment_regional_summary[investment_regional_summary['Region'].isin(['AUS', 'USA'])].copy()
    if not aus_usa_df.empty:
        summary_rows_list.append(aus_usa_df)

    # Add AUD + USD Total
    aud_usd_total_value = aus_usa_df['Total_Asset_Value'].sum()
    aud_usd_total_cost = aus_usa_df['Total_Cost'].sum()
    summary_rows_list.append(pd.DataFrame([['AUD + USD Total', aud_usd_total_value, aud_usd_total_cost]], 
                                     columns=['Region', 'Total Asset Value', 'Total Cost']))

    # Add IND Total
    ind_df = investment_regional_summary[investment_regional_summary['Region'] == 'IND'].copy()
    if not ind_df.empty:
        ind_total_value = ind_df['Total_Asset_Value'].sum()
        ind_total_cost = ind_df['Total_Cost'].sum()
        summary_rows_list.append(pd.DataFrame([['IND Total', ind_total_value, ind_total_cost]], 
                                         columns=['Region', 'Total Asset Value', 'Total Cost']))
    
    # Add Superannuation
    latest_super = get_latest_super_balance()
    summary_rows_list.append(pd.DataFrame([['SUPERANNUATION', latest_super, latest_super]], 
                                     columns=['Region', 'Total Asset Value', 'Total Cost']))

    # Concatenate all parts into the final display summary
    display_summary = pd.concat(summary_rows_list, ignore_index=True)

    # Calculate Grand Total Net Worth from the base df and super
    total_net_worth_value = df['Value_AUD'].sum() + latest_super
    total_net_worth_cost = df['Cost_AUD'].sum() + latest_super
    
    total_net_worth_row = pd.DataFrame([['TOTAL NET WORTH', total_net_worth_value, total_net_worth_cost]], 
                                       columns=['Region', 'Total Asset Value', 'Total Cost'])
    display_summary = pd.concat([display_summary, total_net_worth_row], ignore_index=True)

    # Calculate returns for all rows in display_summary
    display_summary['Total Return ($)'] = display_summary['Total Asset Value'] - display_summary['Total Cost']
    # Avoid division by zero for Total Cost
    display_summary['Total Return (%)'] = (display_summary['Total Return ($)'] / display_summary['Total Cost'].replace(0, pd.NA)) * 100
    display_summary['Total Return (%)'] = display_summary['Total Return (%)'].fillna(0) # Fill NA with 0 for cases where Total Cost is 0 (e.g., new super)


    st.table(display_summary.style.format({
        'Total Asset Value': '${:,.2f}', 'Total Cost': '${:,.2f}',
        'Total Return ($)': '${:,.2f}', 'Total Return (%)': '{:.2f}%'
    }))
    return df
