import sqlite3
import yfinance as yf
import os
import pandas as pd  # Often needed by yfinance under the hood

class PortfolioUpdater:
    def __init__(self, db_path):
        self.db_path = db_path
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(f"Database not found at {self.db_path}")

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def refresh_live_prices(self):
        """Fetches latest prices with exchange-specific suffixes and updates DB."""
        conn = self._get_connection()
        cursor = conn.cursor()

        # 1. Fetch Ticker, Country, and Currency
        cursor.execute("SELECT DISTINCT Ticker, Country, Currency FROM Investment")
        db_rows = cursor.fetchall()

        if not db_rows:
            print("⚠️ No tickers found in the database.")
            conn.close()
            return

        # 2. Map original tickers to Yahoo Symbols
        ticker_map = {}
        for ticker, country, currency in db_rows:
            if not ticker: continue
            yahoo_symbol = f"{ticker}.AX" if country == "AUS" and currency == "AUD" else ticker
            ticker_map[yahoo_symbol] = ticker

        yahoo_symbols = list(ticker_map.keys())
        print(f"🔄 Syncing prices for: {', '.join(yahoo_symbols)}")

        # 3. Download data (using 5d to ensure we have a fallback if today is empty)
        try:
            # We use 5d/1d to get enough history to find the 'last valid' price
            data = yf.download(yahoo_symbols, period="5d", interval="1d", group_by='ticker', progress=False)
        except Exception as e:
            print(f"❌ Yahoo Finance Error: {e}")
            conn.close()
            return

        updates_count = 0

        for yahoo_symbol, original_ticker in ticker_map.items():
            try:
                # Select the 'Close' column for the specific ticker
                if len(yahoo_symbols) == 1:
                    ticker_series = data['Close']
                else:
                    ticker_series = data[yahoo_symbol]['Close']

                # --- FALLBACK LOGIC ---
                # .ffill() moves the last valid price forward into NaN spots
                # .iloc[-1] then grabs the very last value (today's or the most recent fallback)
                current_price = ticker_series.ffill().iloc[-1]

                if pd.isna(current_price) or current_price == 0:
                    print(f"⚠️ Skipping {original_ticker}: No price data found in last 5 days.")
                    continue

                # 4. Update the DB
                cursor.execute("""
                    UPDATE Investment 
                    SET Live_Price = ?, 
                        Live_Value = ? * Remain_Balance,
                        Capital_Gain_Value = (? * Remain_Balance) - Purchase_Value,
                        Capital_Gain_Percent = CASE 
                            WHEN Purchase_Value > 0 THEN ((? * Remain_Balance - Purchase_Value) * 100.0 / Purchase_Value)
                            ELSE 0
                        END
                    WHERE Ticker = ?
                """, (current_price, current_price, current_price, current_price, original_ticker))
                
                updates_count += 1
                print(f"✅ {original_ticker.ljust(10)} | Price: ${current_price:,.2f}")

            except Exception as e:
                print(f"⚠️ Could not update {original_ticker}: {e}")

        conn.commit()
        conn.close()
        print(f"\n🚀 Success: Updated {updates_count} assets.")

# --- Example Usage ---
if __name__ == "__main__":
    DB_FILE = "/Users/nawinprabhujayaraman/Nawin/projects/OneTrack/vOneTrack/InputStage/onetrack.db"
    updater = PortfolioUpdater(DB_FILE)
    updater.refresh_live_prices()
    