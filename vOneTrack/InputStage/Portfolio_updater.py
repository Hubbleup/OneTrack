import sqlite3
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

        # 1. Fetch Ticker, Country, and Currency
        cursor.execute("SELECT DISTINCT Ticker, Country, Currency FROM Investment")
        db_rows = cursor.fetchall()

        if not db_rows:
            conn.close()
            return

        # 2. Map original tickers to Yahoo Symbols (Handles IND, AUS, USA)
        ticker_map = {}
        for ticker, country, currency in db_rows:
            if not ticker: continue
            if country == "AUS": symbol = f"{ticker}.AX"
            elif country == "IND": symbol = f"{ticker}.NS" # Added India Suffix
            else: symbol = ticker # USA usually needs no suffix
            ticker_map[symbol] = ticker

        symbols = list(ticker_map.keys())
        
        # 3. Download data
        try:
            # We fetch 5d to ensure we don't get an empty 'today' on weekends
            data = yf.download(symbols, period="5d", interval="1d", progress=False)
        except Exception as e:
            print(f"❌ Yahoo Finance Error: {e}")
            conn.close()
            return

        updates_count = 0

        for yahoo_symbol, original_ticker in ticker_map.items():
            try:
                # Handle MultiIndex vs Single Index columns safely
                if len(symbols) > 1:
                    ticker_series = data['Close'][yahoo_symbol]
                else:
                    ticker_series = data['Close']

                current_price = ticker_series.ffill().iloc[-1]

                if pd.isna(current_price) or current_price == 0:
                    continue

                # 4. Update the DB (Ensuring column names match your Net Worth logic)
                cursor.execute("""
                    UPDATE Investment 
                    SET Live_Price = ?, 
                        Live_Value = ? * Units,
                        Capital_Gain_Value = (? * Units) - Purchase_Value
                    WHERE Ticker = ?
                """, (current_price, current_price, current_price, original_ticker))
                
                updates_count += 1
            except Exception as e:
                print(f"⚠️ Error on {original_ticker}: {e}")

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
