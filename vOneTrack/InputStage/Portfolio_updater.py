import psycopg2
from time import time
import yfinance as yf
import os
import pandas as pd
import streamlit as st

class PortfolioUpdater:
    def __init__(self):
        pass

    def _get_connection(self):
        return psycopg2.connect(**st.secrets["supabase"])

    def refresh_live_prices(self):
        with self._get_connection() as conn:
            with conn.cursor() as cursor:
                # 1. Fetch unique tickers and countries
                cursor.execute('SELECT DISTINCT "Ticker", "Country" FROM "Investment" WHERE "Remain_Balance" > 0') 
                db_rows = cursor.fetchall()
            if not db_rows:
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
            return

        # 3. Update Database
        with self._get_connection() as conn:
            with conn.cursor() as cursor:
                for ticker, yahoo_sym in ticker_to_yahoo.items():
                    current_price = prices.get(yahoo_sym)
                    
                    if current_price and not pd.isna(current_price):
                        cursor.execute("""
                            UPDATE "Investment" 
                            SET "Live_Price" = %s, 
                                "Live_Value" = (%s * "Units" * COALESCE("Exchange_Rate", 1.0)),
                                "Capital_Gain_Value" = (%s * "Units" * COALESCE("Exchange_Rate", 1.0)) - "Purchase_Value",
                                "Capital_Gain_Percent" = (((%s * "Units" * COALESCE("Exchange_Rate", 1.0)) - "Purchase_Value") / NULLIF("Purchase_Value", 0)) * 100
                            WHERE "Ticker" = %s AND "Remain_Balance" > 0
                        """, (float(current_price), float(current_price), float(current_price), float(current_price), ticker))
            conn.commit()



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
