import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import yfinance as yf
from datetime import datetime
import os

# --- 1. CONFIGURATION ---
DB_PATH = "/Users/nawinprabhujayaraman/Nawin/projects/OneTrack/vOneTrack/InputStage/onetrack.db"

# --- 2. LOGIC CLASS (The Brain) ---
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
        """Fetches historical earnings for charts."""
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
        """Fetches the N most recent dividend payments."""
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
            
    def update_dividend_data(self):
        """Fetches live yields/announcements from Yahoo Finance for Investment table."""
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
                    
                    div_yield = info.get('dividendYield', 0) * 100 if info.get('dividendYield') else 0
                    annual_rate = info.get('dividendRate', 0)
                    ex_date = info.get('exDividendDate', None)
                    
                    if annual_rate > 0:
                        cursor.execute("""
                            UPDATE Investment 
                            SET Dividend_Yield = ?, Annual_Dividend = ?, Last_Ex_Date = ?
                            WHERE Ticker = ?
                        """, (div_yield, annual_rate, ex_date, ticker))
                        updated_count += 1
                except Exception as e:
                    st.error(f"Error fetching {ticker}: {e}")
            conn.commit()
            return updated_count

    def get_total_paid(self):
        """Calculates total dividends paid to date."""
        query = "SELECT SUM(total_dividend) FROM Dividends"
        with self._get_connection() as conn:
            result = conn.execute(query).fetchone()
            return result[0] if result and result[0] else 0.0

# --- 3. STREAMLIT UI SETUP (The Face) ---
st.set_page_config(page_title="Dividend Tracker", layout="wide")
st.title("📅 Dividend Income Analytics")

# Initialize the logic class immediately
viz = DividendVisualizer(DB_PATH)

# --- 4. ACTION SECTION (SYNC) ---
st.divider()
col_btn1, col_btn2 = st.columns([1, 2])

with col_btn1:
    if st.button("🔄 Sync Latest Announcements", use_container_width=True):
        with st.spinner("Fetching from Yahoo Finance..."):
            count = viz.update_dividend_data()
            st.success(f"Updated {count} Tickers!")
            st.rerun()

# --- 5. KEY METRICS ---
total_paid = viz.get_total_paid()
m_col1, m_col2 = st.columns(2)
with m_col1:
    st.metric(label="💰 Total Dividends Received (Lifetime)", value=f"${total_paid:,.2f}")

with m_col2:
    # --- NEW FORWARD FORECAST LOGIC ---
    try:
        with viz._get_connection() as conn:
            # Query for Units * Annual_Dividend
            forecast_df = pd.read_sql_query("""
                SELECT (Units * Annual_Dividend) as Annual_Income 
                FROM Investment 
                WHERE Annual_Dividend > 0 AND Units > 0
            """, conn)
            
        total_forecast = forecast_df['Annual_Income'].sum() if not forecast_df.empty else 0.0
        st.metric(label="🔮 Est. Forward Income (Next 12m)", value=f"${total_forecast:,.2f}")
    except:
        st.metric(label="🔮 Est. Forward Income", value="Sync Required")


# --- 6. RECENT ANNOUNCEMENTS TABLE ---
st.subheader("📢 Current Yields & Announcements")
try:
    with viz._get_connection() as conn:
        yield_df = pd.read_sql_query("""
            SELECT Ticker, Dividend_Yield as 'Yield %', Annual_Dividend as 'Div/Share', 
                   date(Last_Ex_Date, 'unixepoch') as 'Last Ex-Date'
            FROM Investment WHERE Annual_Dividend > 0
        """, conn)
        st.dataframe(yield_df, use_container_width=True, hide_index=True)
except Exception:
    st.info("No announcement data found. Click 'Sync' to fetch live yields.")

# --- 7. ANALYTICS SECTION ---
st.divider()
st.subheader("📊 Performance Analytics")

# Input with Unique Key to fix DuplicateElementId Error
user_raw = st.text_input(
    "Filter Tickers or Change Frequency (Q/H/Y)", 
    value="Q", 
    key="div_tracker_search",
    help="Examples: 'VAS VOO Y' for Yearly view, 'Q' for all Quarterly."
)

ticker_list, freq_code = viz.parse_input(user_raw)
group_sql, label = viz.get_time_logic(freq_code)

if st.button("📈 Generate Charts"):
    df = viz.fetch_data(group_sql, ticker_list)

    if df.empty:
        st.warning(f"No dividend records found for: {user_raw}")
    else:
        filter_text = f" ({ticker_list})" if ticker_list else " (Full Portfolio)"
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
            st.dataframe(df, use_container_width=True, hide_index=True)

# --- 8. RECENT PAYMENTS ---
st.divider()
st.subheader("🗓️ Recent Dividend Payments Received")
recent_df = viz.fetch_recent_payments(limit=5)

if not recent_df.empty:
    st.table(recent_df.style.format({
        'Per Share': '${:.4f}',
        'Total': '${:.2f}'
    }))
else:
    st.info("No historical payment records found in the database.")
