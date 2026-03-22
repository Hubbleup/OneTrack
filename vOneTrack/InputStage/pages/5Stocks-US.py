import streamlit as st
import sqlite3
import pandas as pd
import yfinance as yf
from datetime import datetime

# --- CONFIGURATION ---
DB_PATH = "onetrack.db"

def get_us_stock_data():
    conn = sqlite3.connect(DB_PATH)
    # Filters specifically for USA and groups by Ticker
    query = """
    SELECT 
        Ticker, 
        SUM(Units) as Units, 
        SUM(Purchase_Value) as Total_Cost,
        MAX(Live_Price) as Live_Price,
        MIN(Purchase_Date) as First_Buy_Date
    FROM Investment 
    WHERE Country = 'USA' AND Investment_Type <> 'ETF'
    GROUP BY Ticker
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

@st.cache_data(ttl=3600)
def fetch_us_sparklines(df):
    histories = []
    for ticker in df['Ticker']:
        try:
            h = yf.download(ticker, period="7d", interval="1d", progress=False)['Close']
            histories.append(h.tolist())
        except:
            histories.append([])
    df['7D Trend'] = histories
    return df

st.set_page_config(page_title="US Stocks", layout="wide")
st.title("🇺🇸 US Equity Analytics")

df = get_us_stock_data()

if not df.empty:
    # Calculations
    df['Current Value'] = df['Units'] * df['Live_Price']
    df['Total Return ($)'] = df['Current Value'] - df['Total_Cost']
    df['Total Return (%)'] = (df['Total Return ($)'] / df['Total_Cost']) * 100
    df['Avg Price'] = df['Total_Cost'] / df['Units']
    
    # Growth Stats
    today = datetime.now()
    df['First_Buy_P'] = pd.to_datetime(df['First_Buy_Date'], dayfirst=True, format='mixed')
    df['Years_Held'] = (today - df['First_Buy_P']).dt.days / 365.25
    df['Est. Return/Year (%)'] = (((df['Current Value'] / df['Total_Cost']) ** (1 / df['Years_Held'])) - 1) * 100

    df = fetch_us_sparklines(df)

    # Styling and Table
    def color_metric(val):
        color = '#d62728' if val < 0 else '#2ca02c'
        return f'color: {color}; font-weight: bold;'

    styled_df = df.style.map(color_metric, subset=['Total Return ($)', 'Total Return (%)', 'Est. Return/Year (%)'])

    st.dataframe(
        styled_df,
        column_config={
            "7D Trend": st.column_config.LineChartColumn("7D History", width="medium"),
            "Units": st.column_config.NumberColumn("Held Units", format="%.0f"),
            "Avg Price": st.column_config.NumberColumn("Avg Price (USD)", format="$%.2f"),
            "Live_Price": st.column_config.NumberColumn("Live Price", format="$%.2f"),
            "Current Value": st.column_config.NumberColumn("Market Value", format="$%.2f"),
            "Total Return ($)": st.column_config.NumberColumn("Total Profit", format="$%.2f"),
            "Total Return (%)": st.column_config.NumberColumn("Return %", format="%.2f%%"),
        },
        column_order=("Ticker", "7D Trend", "Units", "Avg Price", "Live_Price", "Current Value", "Total Return ($)", "Total Return (%)"),
        hide_index=True,
        use_container_width=True
    )

         # --- TOP LEVEL METRICS (US STOCKS) ---
    st.divider()
    m1, m2, m3 = st.columns(3)
    
    total_val_us = df['Current Value'].sum()
    total_cost_us = df['Total_Cost'].sum()
    total_profit_us = df['Total Return ($)'].sum()
    avg_growth_us = df['Est. Return/Year (%)'].mean()

    m1.metric("Total US Portfolio (USD)", f"${total_val_us:,.2f}")
    
    # Calculate overall % return for the delta
    overall_ret_pct = (total_profit_us / total_cost_us * 100) if total_cost_us > 0 else 0
    m2.metric("Total US Profit (USD)", f"${total_profit_us:,.2f}", delta=f"{overall_ret_pct:.2f}%")
    
    m3.metric("Avg Annual Growth (CAGR)", f"{avg_growth_us:.2f}%")
    st.divider()

else:
    st.info("No US Stock data found.")
