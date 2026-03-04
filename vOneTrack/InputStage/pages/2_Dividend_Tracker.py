import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
from datetime import datetime
import os

# CONFIGURATION
DB_PATH = "/Users/nawinprabhujayaraman/Nawin/projects/OneTrack/vOneTrack/InputStage/onetrack.db"

class DividendVisualizer:
    def __init__(self, db_path):
        self.db_path = db_path

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def get_time_logic(self, choice: str):
        """Maps frequency code to SQL grouping logic."""
        if choice == 'Y':
            return "strftime('%Y', payment_date)", "Yearly"
        elif choice == 'H':
            return ("strftime('%Y', payment_date) || '-H' || "
                    "(CASE WHEN strftime('%m', payment_date) <= '06' THEN '1' ELSE '2' END)"), "Half-Yearly"
        else:
            return ("strftime('%Y', payment_date) || '-Q' || "
                    "((strftime('%m', payment_date) - 1) / 3 + 1)"), "Quarterly"

    def parse_input(self, user_input):
        """Extracts tickers and frequency from the web text box."""
        parts = user_input.strip().split()
        if not parts:
            return None, 'Q'
        
        last_word = parts[-1].upper()
        if last_word in ['Q', 'H', 'Y']:
            freq = last_word
            tickers = " ".join(parts[:-1]).replace(',', ' ')
        else:
            freq = 'Q'
            tickers = " ".join(parts).replace(',', ' ')
            
        return (tickers.strip() if tickers else None), freq

    def fetch_data(self, group_sql, tickers=None):
        where_clause = f"WHERE payment_date <= '{datetime.now().strftime('%Y-%m-%d')}'"
        
        if tickers:
            ticker_list = [t.strip().upper() for t in tickers.split() if t.strip()]
            ticker_str = "','".join(ticker_list)
            where_clause += f" AND Ticker IN ('{ticker_str}')"

        query = f"""
        SELECT 
            ticker AS Ticker,
            {group_sql} AS Period,
            SUM(total_dividend) AS Earnings
        FROM Dividends
        {where_clause}
        GROUP BY Ticker, Period
        ORDER BY payment_date ASC;
        """
        with self._get_connection() as conn:
            return pd.read_sql_query(query, conn)
        
    def fetch_recent_payments(self, limit=5):
            """Fetches the N most recent dividend payments from the database."""
            query = f"""
            SELECT 
                ticker AS Ticker, 
                payment_date AS 'Pay Date', 
                num_shares AS Shares, 
                dividend_per_unit AS 'Per Share', 
                total_dividend AS Total
            FROM Dividends
            ORDER BY payment_date DESC
            LIMIT {limit};
            """
            with self._get_connection() as conn:
                return pd.read_sql_query(query, conn)
# --- STREAMLIT UI ---
st.set_page_config(page_title="Dividend Tracker", layout="wide")
st.title("📅 Dividend Income Analytics")

# 1. Input Section (Replacing the Terminal Prompt)
col1, col2 = st.columns([3, 1])
with col1:
    user_raw = st.text_input(
        "Enter Tickers and/or Frequency", 
        value="Q", 
        help="Examples: 'AAPL MSFT H', 'TSLA', 'Y' (for all yearly)"
    )

viz = DividendVisualizer(DB_PATH)
ticker_list, freq_code = viz.parse_input(user_raw)
group_sql, label = viz.get_time_logic(freq_code)

# 2. Calculation & Display
if st.button("📊 Generate Charts"):
    df = viz.fetch_data(group_sql, ticker_list)

    if df.empty:
        st.warning(f"No dividend records found for: {user_raw}")
    else:
        # Preparation for Titles
        filter_text = f" ({ticker_list})" if ticker_list else " (Full Portfolio)"
        
        # Dashboard Layout
        tab1, tab2, tab3 = st.tabs(["📈 Trends", "📊 Totals", "📄 Data Table"])

        with tab1:
            fig_line = px.line(
                df, x='Period', y='Earnings', color='Ticker', markers=True,
                title=f"Dividend Income by Ticker {filter_text} - {label}",
                labels={'Earnings': 'Amount ($)', 'Period': 'Timeline'},
                template="plotly_white"
            )
            st.plotly_chart(fig_line, use_container_width=True)

        with tab2:
            total_df = df.groupby('Period')['Earnings'].sum().reset_index()
            fig_bar = px.bar(
                total_df, x='Period', y='Earnings',
                title=f"Total Portfolio Earnings {filter_text} - {label}",
                text_auto='.2f', color_discrete_sequence=['#2ecc71']
            )
            st.plotly_chart(fig_bar, use_container_width=True)
            
        with tab3:
            st.dataframe(df, use_container_width=True)
st.divider()
st.subheader("🗓️ Recent Dividend Payments")

# Fetch the last 5 payments
recent_df = viz.fetch_recent_payments(limit=5)

if not recent_df.empty:
    # Display as a clean table
    st.table(recent_df.style.format({
        'Per Share': '${:.4f}',
        'Total': '${:.2f}'
    }))
else:
    st.info("No recent payments found in the database.")


