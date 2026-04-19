import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import yfinance as yf
from datetime import datetime
import os
from Calculate_dividend import DividendCalculator

# --- 1. CONFIGURATION ---
DB_PATH = "/Users/nawinprabhujayaraman/Nawin/projects/OneTrack/vOneTrack/InputStage/onetrack.db"

# --- 2. INITIALIZE LOGIC ---
calc = DividendCalculator(DB_PATH)

class DividendVisualizer:
    def __init__(self, db_path):
        self.db_path = db_path

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def get_time_logic(self, choice: str):
        if choice == 'Y':
            return "strftime('%Y', payment_date)", "Yearly"
        elif choice == 'H':
            return ("strftime('%Y', payment_date) || '-H' || "
                    "(CASE WHEN strftime('%m', payment_date) <= '06' THEN '1' ELSE '2' END)"), "Half-Yearly"
        else:
            return ("strftime('%Y', payment_date) || '-Q' || "
                    "((strftime('%m', payment_date) - 1) / 3 + 1)"), "Quarterly"

    def parse_input(self, user_input):
        parts = user_input.strip().split()
        if not parts: return None, 'Q'
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

        query = f"SELECT ticker AS Ticker, {group_sql} AS Period, SUM(total_dividend) AS Earnings " \
                f"FROM Dividends {where_clause} GROUP BY Ticker, Period ORDER BY payment_date ASC;"
        with self._get_connection() as conn:
            return pd.read_sql_query(query, conn)
        
    def fetch_recent_payments(self, limit=5):
        query = f"SELECT ticker AS Ticker, payment_date AS 'Pay Date', num_shares AS Shares, " \
                f"dividend_per_unit AS 'Per Share', total_dividend AS Total FROM Dividends " \
                f"ORDER BY payment_date DESC LIMIT {limit};"
        with self._get_connection() as conn:
            return pd.read_sql_query(query, conn)
            
    def update_dividend_data(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT Ticker, Country FROM Investment")
            stocks = cursor.fetchall()
            updated_count = 0
            for ticker, country in stocks:
                symbol = f"{ticker}.AX" if country == "AUS" else (f"{ticker}.NS" if country == "IND" else ticker)
                try:
                    stock = yf.Ticker(symbol)
                    info = stock.info
                    raw_yield = info.get('dividendYield', 0)
                    if raw_yield:
                        # If the yield is less than 1 (e.g. 0.04), it's a decimal, so multiply by 100
                        if raw_yield < 1:
                            div_yield = raw_yield * 100
                        else:
                            # If it's already a whole number (e.g. 4.5), keep it as is
                            div_yield = raw_yield
                    else:
                        div_yield = 0
                    annual_rate = info.get('dividendRate', 0)
                    ex_date = info.get('exDividendDate', None)
                    if annual_rate > 0:
                        cursor.execute("UPDATE Investment SET Dividend_Yield = ?, Annual_Dividend = ?, Last_Ex_Date = ? WHERE Ticker = ?", 
                                       (div_yield, annual_rate, ex_date, ticker))
                        updated_count += 1
                except Exception as e:
                    st.error(f"Error fetching {ticker}: {e}")
            conn.commit()
            return updated_count

    def get_total_paid(self):
        query = "SELECT SUM(total_dividend) FROM Dividends"
        with self._get_connection() as conn:
            result = conn.execute(query).fetchone()
            return result[0] if result and result[0] else 0.0

# --- 3. STREAMLIT UI SETUP ---
st.set_page_config(page_title="Dividend Tracker", layout="wide")
st.title("📅 Dividend Income Analytics")
viz = DividendVisualizer(DB_PATH)

# --- 4. ACTION SECTION ---
st.divider()
st.subheader("⚙️ Data Management")
col_sync1, col_sync2 = st.columns(2)

with col_sync1:
    if st.button("📈 Update Yields & Forecasts", use_container_width=True, help="Update live yields for your current holdings."):
        with st.spinner("Fetching live yields..."):
            count = viz.update_dividend_data()
            st.success(f"Updated {count} Tickers!")
            st.rerun()

with col_sync2:
    if st.button("📥 Backfill Historical Payments", use_container_width=True, help="Scan for past payments based on your purchase dates."):
        with st.spinner("Checking for missing payments..."):
            new_records = calc.sync_new_dividends_from_db()
            if new_records:
                st.success(f"Added {sum(new_records.values())} new records!")
                st.rerun()
            else:
                st.info("Dividend history is up to date.")

# --- 5. KEY METRICS ---
st.divider()
total_paid = viz.get_total_paid()
m_col1, m_col2 = st.columns(2)
with m_col1:
    st.metric(label="💰 Total Dividends Received (Lifetime)", value=f"${total_paid:,.2f}")

with m_col2:
    try:
        with viz._get_connection() as conn:
            forecast_df = pd.read_sql_query("SELECT (Units * Annual_Dividend) as Annual_Income FROM Investment WHERE Annual_Dividend > 0 AND Units > 0", conn)
        total_forecast = forecast_df['Annual_Income'].sum() if not forecast_df.empty else 0.0
        st.metric(label="🔮 Est. Forward Income (Next 12m)", value=f"${total_forecast:,.2f}")
    except:
        st.metric(label="🔮 Est. Forward Income", value="Sync Required")

# --- 6. ANNOUNCEMENTS TABLE ---
st.subheader("📢 Current Yields & Announcements")
try:
    with viz._get_connection() as conn:
        yield_df = pd.read_sql_query("SELECT Ticker, Dividend_Yield as 'Yield %', Annual_Dividend as 'Div/Share', date(Last_Ex_Date, 'unixepoch') as 'Last Ex-Date' FROM Investment WHERE Annual_Dividend > 0", conn)
        st.dataframe(yield_df, use_container_width=True, hide_index=True)
except:
    st.info("No announcement data found. Run 'Update Yields' to fetch.")

# --- 7. ANALYTICS SECTION ---
st.divider()
st.subheader("📊 Performance Analytics")
user_raw = st.text_input("Filter Tickers or Change Frequency (Q/H/Y)", value="Q", key="div_tracker_search")

ticker_list, freq_code = viz.parse_input(user_raw)
group_sql, label = viz.get_time_logic(freq_code)

if st.button("📈 Generate Charts"):
    df = viz.fetch_data(group_sql, ticker_list)
    if df.empty:
        st.warning("No dividend records found for this selection.")
    else:
        tab1, tab2, tab3 = st.tabs(["📈 Trends", "📊 Totals", "📄 Data Table"])
        with tab1:
            st.plotly_chart(px.line(df, x='Period', y='Earnings', color='Ticker', markers=True, title=f"Trend - {label}", template="plotly_white"), use_container_width=True)
        with tab2:
            total_df = df.groupby('Period')['Earnings'].sum().reset_index()
            st.plotly_chart(px.bar(total_df, x='Period', y='Earnings', title=f"Total Earnings - {label}", text_auto='.2f', color_discrete_sequence=['#2ecc71']), use_container_width=True)
        with tab3:
            st.dataframe(df, use_container_width=True, hide_index=True)

# --- 8. RECENT PAYMENTS ---
st.divider()
st.subheader("🗓️ Recent Dividend Payments Received")
recent_df = viz.fetch_recent_payments(limit=5)
if not recent_df.empty:
    st.table(recent_df.style.format({'Per Share': '${:.0f}', 'Total': '${:.2f}'}))
else:
    st.info("No historical payments found.")
