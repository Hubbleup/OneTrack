import streamlit as st
import sqlite3
import pandas as pd
import yfinance as yf
from datetime import datetime

# --- CONFIGURATION ---
DB_PATH = "onetrack.db"

# --- 1. DATA FETCHING & CONSOLIDATION (Ref: A2:N11) ---
def get_consolidated_etf_data():
    conn = sqlite3.connect(DB_PATH)
    query = """
    SELECT 
        Ticker, 
        Country, 
        SUM(Units) as Units, 
        SUM(Purchase_Value) as Total_Cost,
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

# --- 2. DETAILED DATA FETCHING (Ref: A22:N67) ---
def get_detailed_etf_rows():
    conn = sqlite3.connect(DB_PATH)
    query = """
    SELECT 
        Ticker, 
        Purchase_Date, 
        Units, 
        Purchase_Price, 
        Purchase_Value, 
        Live_Price, 
        Live_Value, 
        Account_Platform
    FROM Investment 
    WHERE Investment_Type = 'ETF'
    ORDER BY Purchase_Date DESC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    if not df.empty:
        # Calculate these on the fly in Python to avoid NULLs
        df['Capital_Gain_Value'] = (df['Live_Price'] - df['Purchase_Price']) * df['Units']
        df['Capital_Gain_Percent'] = ((df['Live_Price'] - df['Purchase_Price']) / df['Purchase_Price']) * 100
        
    return df  

# --- 3. STYLING HELPERS ---
def color_metric(val):
    if isinstance(val, (int, float)):
        color = '#d62728' if val < 0 else '#2ca02c'
        return f'color: {color}; font-weight: bold;'
    return ''

# --- 4. PAGE UI ---
st.set_page_config(page_title="ETF Analytics", layout="wide")
st.title("📊 ETF Portfolio Analytics")
st.caption("Consolidated Performance Metrics (e.g. IVV, VAS)")

df = get_consolidated_etf_data()

if not df.empty:
    # --- MATH ENGINE ---
    df['Current Value'] = df['Units'] * df['Live_Price']
    df['Total Return ($)'] = df['Current Value'] - df['Total_Cost']
    df['Total Return (%)'] = (df['Total Return ($)'] / df['Total_Cost']) * 100
    df['Avg Price'] = df['Total_Cost'] / df['Units']
    
    today = datetime.now()
    df['First_Buy_P'] = pd.to_datetime(df['First_Buy_Date'], dayfirst=True, format='mixed')
    df['Years_Held'] = (today - df['First_Buy_P']).dt.days / 365.25
    df['Est. Return/Year (%)'] = (((df['Current Value'] / df['Total_Cost']) ** (1 / df['Years_Held'])) - 1) * 100

    df = fetch_sparklines(df)

    # --- TOP LEVEL METRICS ---
    m1, m2, m3 = st.columns(3)
    m1.metric("Total ETF Value", f"${df['Current Value'].sum():,.2f}")
    m2.metric("Total ETF Profit", f"${df['Total Return ($)'].sum():,.2f}", 
              delta=f"{(df['Total Return ($)'].sum() / df['Total_Cost'].sum() * 100):.2f}%")
    m3.metric("Avg Portfolio Growth (CAGR)", f"{df['Est. Return/Year (%)'].mean():.2f}%")
    st.divider()

    # --- CONSOLIDATED TABLE (A2:N11) ---
    st.subheader("📋 Consolidated ETF Summary")
    styled_df = df.style.map(color_metric, subset=['Total Return ($)', 'Total Return (%)', 'Est. Return/Year (%)'])

    st.dataframe(
        styled_df,
        column_config={
            "7D Trend": st.column_config.LineChartColumn("7D History", width="medium"),
            "Units": st.column_config.NumberColumn("Held Units", format="%.0f"),
            "Avg Price": st.column_config.NumberColumn("Avg Price", format="$%.2f"),
            "Live_Price": st.column_config.NumberColumn("Live Price", format="$%.2f"),
            "Current Value": st.column_config.NumberColumn("Market Value", format="$%.2f"),
            "Total Return ($)": st.column_config.NumberColumn("Total Profit", format="$%.2f"),
            "Total Return (%)": st.column_config.NumberColumn("Return %", format="%.2f%%"),
            "Est. Return/Year (%)": st.column_config.NumberColumn("Est. Return/Year", format="%.2f%%"),
        },
        column_order=(
            "Ticker", "7D Trend", "Units", "Avg Price", "Live_Price", 
            "Current Value", "Total Return ($)", "Total Return (%)", "Est. Return/Year (%)"
        ),
        hide_index=True,
        use_container_width=True
    )

    # --- DETAILED TRANSACTION HISTORY (A22:N67) ---
    st.divider()
    st.subheader("📄 Detailed ETF Transaction History")
    df_details = get_detailed_etf_rows()
    
    if not df_details.empty:
        styled_details = df_details.style.map(color_metric, subset=['Capital_Gain_Value', 'Capital_Gain_Percent'])
        st.dataframe(
            styled_details,
            column_config={
                "Purchase_Date": st.column_config.DateColumn("Trade Date"),
                "Units": st.column_config.NumberColumn("Qty", format="%.0f"),
                "Purchase_Price": st.column_config.NumberColumn("Buy Price", format="$%.2f"),
                "Capital_Gain_Value": st.column_config.NumberColumn("P/L ($)", format="$%.2f"),
                "Capital_Gain_Percent": st.column_config.NumberColumn("Growth (%)", format="%.2f%%"),
            },
            hide_index=True,
            use_container_width=True
        )

else:
    st.info("No ETF data found. Check your database categories.")
