import psycopg2
import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
from sqlalchemy import create_engine
import urllib.parse
import sys

class DividendVisualizer:
    def __init__(self):
        pass

    def _get_connection(self):
        pg_keys = ["host", "port", "database", "user", "password", "options"]
        conn_params = {k: v for k, v in st.secrets["supabase"].items() if k in pg_keys}
        return psycopg2.connect(**conn_params)

    def _get_engine(self):
        """Utility to create a SQLAlchemy engine for pandas compatibility."""
        user = urllib.parse.quote_plus(st.secrets['supabase']['user'])
        password = urllib.parse.quote_plus(st.secrets['supabase']['password'])
        host = st.secrets['supabase']['host']
        port = st.secrets['supabase']['port']
        database = st.secrets['supabase']['database']
        db_url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"
        return create_engine(db_url)

    def get_time_logic(self, choice: str):
        """Maps frequency code to SQL grouping logic."""
        if choice == 'Y':
            return "to_char(payment_date::date, 'YYYY')", "Yearly"
        elif choice == 'H':
            return ("to_char(payment_date::date, 'YYYY') || "
                    "(CASE WHEN extract(month from payment_date::date) <= 6 THEN '-H1' ELSE '-H2' END)"), "Half-Yearly"
        else:
            return "to_char(payment_date::date, 'YYYY-\"Q\"Q')", "Quarterly"

    def parse_input(self, user_input):
        """Extracts tickers and frequency from a single input string."""
        parts = user_input.strip().split()
        if not parts:
            return None, 'Q'
        
        # Check if the last word is a frequency code
        last_word = parts[-1].upper()
        if last_word in ['Q', 'H', 'Y']:
            freq = last_word
            tickers = " ".join(parts[:-1]).replace(',', ' ') # Remove frequency from ticker list
        else:
            freq = 'Q' # Default
            tickers = " ".join(parts).replace(',', ' ')
            
        return tickers.strip() if tickers else None, freq

    def fetch_data(self, group_sql, tickers=None):
        where_clause = f"WHERE payment_date <= '{datetime.now().strftime('%Y-%m-%d')}'"
        
        if tickers:
            ticker_list = [t.strip().upper() for t in tickers.split() if t.strip()]
            ticker_str = "','".join(ticker_list)
            where_clause += f" AND \"ticker\" IN ('{ticker_str}')"

        query = f"""
        SELECT 
            \"ticker\" AS \"Ticker\",
            {group_sql} AS Period,
            SUM(\"total_dividend\") AS Earnings
        FROM \"Dividends\"
        {where_clause}
        GROUP BY \"Ticker\", Period
        ORDER BY MIN(payment_date) ASC;
        """
        engine = self._get_engine()
        return pd.read_sql_query(query, engine)

    def run_dashboard(self):
        print("\n📊 Connected to Supabase")
        print("Usage examples: 'AAPL, MSFT H', 'TSLA', 'Q' (for all)")
        
        user_raw = input("Enter Tickers and/or Frequency: ").strip()
        ticker_list, freq_code = self.parse_input(user_raw)
        group_sql, label = self.get_time_logic(freq_code)

        df = self.fetch_data(group_sql, ticker_list)

        if df.empty:
            print(f"⚠️ No records found for your input.")
            return

        # Prepare Titles
        filter_text = f" [Filter: {ticker_list}]" if ticker_list else " [Full Portfolio]"
        
        # Visual 1: Line Graph
        fig_line = px.line(
            df, x='Period', y='Earnings', color='Ticker', markers=True,
            title=f"Dividend Trends {filter_text} - {label} View",
            labels={'Earnings': 'Dividends ($)', 'Period': 'Time'},
            template="plotly_white"
        )
        
        # Visual 2: Bar Chart
        total_df = df.groupby('Period')['Earnings'].sum().reset_index()
        fig_bar = px.bar(
            total_df, x='Period', y='Earnings',
            title=f"Total Earnings {filter_text} - {label} View",
            text_auto='.2f', color_discrete_sequence=['#2ecc71'],
            template="plotly_dark"
        )

        fig_line.show()
        fig_bar.show()

if __name__ == "__main__":
    DEFAULT_DB = "/Users/nawinprabhujayaraman/Nawin/projects/OneTrack/vOneTrack/InputStage/onetrack.db"
    DB_PATH = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB

    try:
        viz = DividendVisualizer()
        viz.run_dashboard()
    except Exception as e:
        print(f"❌ Error: {e}")
