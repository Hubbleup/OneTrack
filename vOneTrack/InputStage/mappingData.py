# mappingdata.py
import psycopg2
import os
import streamlit as st
from sheet_reader import get_specific_tabs_data

# 1. Define the specific tabs you want to read
my_tabs = ["ETFs", "Stocks", "US Stocks", "Managed Funds"]

# 2. Call the function with these tab names
tabs_data = get_specific_tabs_data(my_tabs)

# 3. Database setup (using the absolute path we verified)
try:
    pg_keys = ["host", "port", "database", "user", "password", "options"]
    conn_params = {k: v for k, v in st.secrets["supabase"].items() if k in pg_keys}
    conn = psycopg2.connect(**conn_params)
    cursor = conn.cursor()
except Exception as e:
    print(f"❌ Connection Error: {e}")
    exit()

    
    # mappingdata.py (inside the for tab_name, rows in tabs_data.items(): loop)
PLATFORM_NAME = "CMC"  
for tab_name, rows in tabs_data.items():
    # Skip the headers (Assuming Row 22 is headers, data starts from Row 23)
    data_to_save = rows[1:] 
    
    cleaned_rows = []
    for row in data_to_save:
        # 1. Skip if row is empty or Ticker (index 0) is blank
        if not row or not any(row) or not str(row[0]).strip():
            continue
            
        ticker = str(row[0]).upper()
        asset_type = ""
        country = ""
        currency = ""

        # 2. Logic based on Tab Name and Ticker Content
        if tab_name == "US Stocks":
            asset_type = "Stocks"
            country = "USA"
            currency = "USD"
        
        elif tab_name == "Stocks":
            asset_type = "Stocks"
            country = "AUS"
            currency = "AUD"
            
        elif tab_name == "Managed Funds":
            asset_type = "Stocks"
            country = "IND"
            currency = "INR"
            
        elif tab_name == "ETFs":
            asset_type = "ETF"
            if any(code in ticker for code in ["ASX", ".AX"]):
                country = "AUS"
                currency = "AUD"
            else:
                country = "USA"
                currency = "USD"
        else:
            asset_type = "Other"
            country = "Unknown"
            currency = "Unknown"

        # 3. Padding logic: Ensure the row has exactly 13 original columns
        while len(row) < 13:
            row.append(None)
            
        # 4. Append our 3 new calculated columns (Total 16 columns)
        new_row = row[:13] + [PLATFORM_NAME, currency, country, asset_type]
        cleaned_rows.append(new_row)

    # 5. Update your SQL Query for 16 columns (16 '?' marks)
    query = """
        INSERT INTO "Investment" (
            "Ticker", "Purchase_Date", "Units", "Purchase_Price", "Brokerage", 
            "Sold_Units", "Purchase_Value", "Live_Price", "Live_Value", 
            "Capital_Gain_Value", "Capital_Gain_Percent", "Remain_Balance", "FIFO_CG",
            "Account_Platform", "Currency", "Country", "Investment_Type"
        ) VALUES %s
    """
    
    try:
        if cleaned_rows:
            from psycopg2.extras import execute_values
            # execute_values manages the placeholders automatically
            execute_values(cursor, query, cleaned_rows)
            print(f"💾 Saved {len(cleaned_rows)} rows from '{tab_name}'")
    except Exception as e:
        print(f"❌ Error saving '{tab_name}': {e}")

# --- HEAL SEQUENCES AFTER BATCH IMPORT ---
cursor.execute("""
    SELECT setval(pg_get_serial_sequence('public."Investment"', 'id'), 
                  COALESCE((SELECT MAX("id") FROM "Investment"), 0) + 1, 
                  false);
""")

# Save and close after the loop finishes
conn.commit()
conn.close()
print("\n🚀 All 4 tabs have been synced successfully.")
