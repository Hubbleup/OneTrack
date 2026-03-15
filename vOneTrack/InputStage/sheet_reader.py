import sqlite3
import pandas as pd
from googleapi import create_google_service
from Portfolio_updater import PortfolioUpdater

# --- CONFIGURATION (Based on your Sheet & DB) ---
SPREADSHEET_ID = "1BvR7zrAO6JBraoS_jNsmiO6KHnPSbvTzJZJTCPBEg-8"
RANGE_NAME = "'From CSV'!A2:F500" 
DB_PATH = "onetrack.db"

def sync_broker_sheet_to_sqlite():
    """
    Uses the user's preferred 'create_google_service' method to read 
    broker data and populate the local SQLite Investment table.
    """
    
    # 1. Access Google Sheets using your existing method
    # Note: Scope set for reading spreadsheets
    service = create_google_service(
        api_name='sheets', 
        api_version='v4', 
        scopes=['https://www.googleapis.com/auth/spreadsheets']
    )
    
    try:
        # 2. READ DATA
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID, 
            range=RANGE_NAME
        ).execute()
        
        rows = result.get('values', [])
        if not rows:
            return False, "No data found in 'From CSV' tab."

        # 3. DATABASE CONNECTION
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        import_count = 0
        skipped_count = 0

        for row in rows:
            try:
                # Helper to clean currency/commas/spaces
                def clean(v): return str(v).replace(',', '').replace('$', '').strip()

                # MAPPING BASED ON YOUR ORDER:
                # [0]AsxCode, [1]Settlement Date, [2]Avg Price, [3]Price, [4]Quantity, [5]Consideration
                ticker  = clean(row[0]).upper()
                p_date  = clean(row[1])
                p_price = float(clean(row[3]))  # 'Price'
                units   = float(clean(row[4]))  # 'Quantity'
                p_value = float(clean(row[5]))  # 'Consideration'

                # DUPLICATE CHECK (Ticker + Date + Units)
                cursor.execute("""
                    SELECT 1 FROM Investment 
                    WHERE Ticker = ? AND Purchase_Date = ? AND Units = ?
                """, (ticker, p_date, units))
                
                if cursor.fetchone():
                    skipped_count += 1
                    continue

                # Default Logic: AUS for ASX tickers, otherwise USA
                country = "AUS" if len(ticker) <= 4 else "USA"
                currency = "AUD" if country == "AUS" else "USD"

                # 4. INSERT INTO DB
                # Initially setting Live Price/Value to Purchase Price/Value
                cursor.execute("""
                    INSERT INTO Investment (
                        Ticker, Purchase_Date, Units, Purchase_Price, Purchase_Value, 
                        Remain_Balance, Live_Price, Live_Value, Country, Currency
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    ticker, p_date, units, p_price, p_value, 
                    units, p_price, p_value, country, currency
                ))
                import_count += 1
                
            except (IndexError, ValueError):
                # Skip empty or malformed rows
                continue 

        conn.commit()
        conn.close()

        # 5. TRIGGER AUTOMATIC PRICE REFRESH
        print("🔄 Fetching latest market prices...")
        updater = PortfolioUpdater(DB_PATH)
        updater.refresh_live_prices()

        return True, f"✅ Imported {import_count} new trades, skipped {skipped_count} duplicates."

    except Exception as e:
        return False, f"❌ Error during sync: {str(e)}"

if __name__ == "__main__":
    # Test the sync
    success, msg = sync_broker_sheet_to_sqlite()
    print(msg)
