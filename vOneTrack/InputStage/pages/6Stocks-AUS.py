import streamlit as st
import sqlite3
import pandas as pd
import yfinance as yf
from datetime import datetime

# --- CONFIGURATION ---
DB_PATH = "onetrack.db"

def get_aus_stock_data():
    conn = sqlite3.connect(DB_PATH)
    # Filters specifically for AUS and groups by Ticker
    query = """
    SELECT 
        Ticker, 
        SUM(Units) as Units, 
        SUM(Purchase_Value) as Total_Cost,
        MAX(Live_Price) as Live_Price,
        MIN(Purchase_Date) as First_Buy_Date
    FROM Investment 
    WHERE Country = 'AUS' AND Investment_Type <> 'ETF'
    GROUP BY Ticker
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

@st.cache_data(ttl=3600)
def fetch_aus_sparklines(df):
    histories = []
    for ticker in df['Ticker']:
        try:
            h = yf.download(f"{ticker}.AX", period="7d", interval="1d", progress=False)['Close']
            histories.append(h.tolist())
        except:
            histories.append([])
    df['7D Trend'] = histories
    return df

st.set_page_config(page_title="AUS Stocks", layout="wide")
st.title("🇦🇺 Australian Equity Analytics")

df = get_aus_stock_data()

if not df.empty:
    # Calculations (Similar to US Stocks)
    df['Current Value'] = df['Units'] * df['Live_Price']
    df['Total Return ($)'] = df['Current Value'] - df['Total_Cost']
    df['Total Return (%)'] = (df['Total Return ($)'] / df['Total_Cost']) * 100
    df['Avg Price'] = df['Total_Cost'] / df['Units']

    df = fetch_aus_sparklines(df)

    st.dataframe(
        df.style.map(lambda x: f'color: {"#d62728" if x < 0 else "#2ca02c"}; font-weight: bold;', subset=['Total Return ($)', 'Total Return (%)']),
        column_config={
            "7D Trend": st.column_config.LineChartColumn("7D History", width="medium"),
            "Current Value": st.column_config.NumberColumn("Market Value (AUD)", format="$%.0f"),
            "Total Return ($)": st.column_config.NumberColumn("Total Profit", format="$%.2f"),
        },
        column_order=("Ticker", "7D Trend", "Units", "Avg Price", "Live_Price", "Current Value", "Total Return ($)", "Total Return (%)"),
        hide_index=True,
        use_container_width=True
    )
        # --- MATH & GROWTH (AUS STOCKS) ---
    today = datetime.now()
    df['First_Buy_P'] = pd.to_datetime(df['First_Buy_Date'], dayfirst=True, format='mixed')
    df['Years_Held'] = (today - df['First_Buy_P']).dt.days / 365.25
    df['Est. Return/Year (%)'] = (((df['Current Value'] / df['Total_Cost']) ** (1 / df['Years_Held'])) - 1) * 100

    # --- TOP LEVEL METRICS (AUS STOCKS) ---
    st.divider()
    a1, a2, a3 = st.columns(3)
    
    total_val_au = df['Current Value'].sum()
    total_cost_au = df['Total_Cost'].sum()
    total_profit_au = df['Total Return ($)'].sum()
    avg_growth_au = df['Est. Return/Year (%)'].mean()

    a1.metric("Total AUS Portfolio (AUD)", f"${total_val_au:,.2f}")
    
    overall_ret_pct_au = (total_profit_au / total_cost_au * 100) if total_cost_au > 0 else 0
    a2.metric("Total AUS Profit (AUD)", f"${total_profit_au:,.2f}", delta=f"{overall_ret_pct_au:.2f}%")
    
    a3.metric("Avg Annual Growth (CAGR)", f"{avg_growth_au:.2f}%")
    st.divider()

else:
    st.info("No Australian Stock data found.")
