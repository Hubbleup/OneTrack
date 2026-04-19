import sqlite3
from time import time
import yfinance as yf
import os
import pandas as pd
import streamlit as st

class PortfolioUpdater:
    def __init__(self, db_path):
        self.db_path = db_path
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(f"Database not found at {self.db_path}")

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def refresh_live_prices(self):
        conn = self._get_connection()
        cursor = conn.cursor()
       
        # 1. Fetch unique tickers and countries
        cursor.execute("""SELECT DISTINCT Ticker, Country 
        FROM Investment 
        WHERE Remain_Balance IS NOT NULL 
          AND Remain_Balance > 0""")  # Only update active investments
        db_rows = cursor.fetchall()
        if not db_rows:
            conn.close()
            return

        # 2. Build Ticker Mapping for Yahoo Finance
        symbols = []
        ticker_to_yahoo = {}
        for ticker, country in db_rows:
            if not ticker: continue
            # Suffix logic: .AX for Aus, none for US
            yahoo_sym = f"{ticker}.AX" if country == "AUS" else (f"{ticker}.BO" if country == "IND" else ticker)
            symbols.append(yahoo_sym)
            ticker_to_yahoo[ticker] = yahoo_sym

        try:
            # Download data (fetching 5 days ensures a price even on weekends)
            
            data = yf.download(symbols, period="5d", interval="1d", progress=False)
            
            # Extract the latest 'Close' price for each symbol into a dictionary
            if len(symbols) == 1:
                prices = {symbols[0]: data['Close'].iloc[-1]}
            else:
                prices = data['Close'].ffill().iloc[-1].to_dict()
        except Exception as e:
            print(f"❌ Market Fetch Error: {e}")
            conn.close()
            return

        # 3. Update Database (Handling NULLs with COALESCE)
        for ticker, yahoo_sym in ticker_to_yahoo.items():
            current_price = prices.get(yahoo_sym)
            
            if current_price and not pd.isna(current_price):
                # COALESCE(column, default) prevents the 'Multiplication by NULL' error
                cursor.execute("""
                    UPDATE Investment 
                    SET Live_Price = ?, 
                        Live_Value = (? * Units * COALESCE(Exchange_Rate, 1.0)),
                        Capital_Gain_Value = (? * Units * COALESCE(Exchange_Rate, 1.0)) - Purchase_Value,
                        Capital_Gain_Percent = (
                            ((? * Units * COALESCE(Exchange_Rate, 1.0)) - Purchase_Value) / 
                            NULLIF(Purchase_Value, 0)
                        ) * 100
                    WHERE Ticker = ?
                        AND Remain_Balance > 0
                """, (current_price, current_price, current_price, current_price, ticker))

        conn.commit()
        conn.close()



    def get_live_exchange_rates(self):
        """Fetches dynamic rates. Logic updated to work with or without Streamlit."""
        try:
            # Using history() is often more reliable than .info
            usd = yf.Ticker("USDAUD=X").history(period="1d")['Close'].iloc[-1]
            inr = yf.Ticker("INRAUD=X").history(period="1d")['Close'].iloc[-1]
            
            return {'AUS': 1.0, 'IND': inr, 'USA': usd}
        except Exception as e:
            # Only use st.warning if we are actually in a streamlit app
            msg = f"Using fallback exchange rates: {e}"
            try: st.warning(msg)
            except: print(msg)
            return {'AUS': 1.0, 'IND': 0.0154, 'USA': 1.42}
        
    def run_continuous_sync(self, interval_seconds=300):
        """Runs the price refresh in a loop every X seconds."""
        while True:
            try:
                print(f"🔄 Background Sync Started at {time.strftime('%H:%M:%S')}")
                self.refresh_live_prices()
                # Also sync your AUD rates here if needed

                with open("last_sync.txt", "w") as f:
                    f.write(time.strftime("%H:%M:%S"))
                time.sleep(interval_seconds)
            except Exception as e:
                print(f"❌ Background Sync Error: {e}")
                time.sleep(60) # Wait a bit before retrying if it fails
