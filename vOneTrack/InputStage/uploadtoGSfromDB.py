from datetime import datetime
import sqlite3
import pandas as pd
from googleapi import create_google_service

def get_all_investment_data():
    conn = sqlite3.connect("onetrack.db")
    # Fetching all columns from the Investment table
    df = pd.read_sql_query("SELECT * FROM Investment", conn)
    conn.close()
    return df

def upload_db_to_sheet():
    # 1. Read from SQLite
    df = get_all_investment_data()
    

    # 2. Format for Google Sheets (Headers + Rows)
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    df.insert(0, 'Sync_Timestamp', current_time)
    df = df.astype(str) 
    
    headers = df.columns.tolist()
    data_rows = df.values.tolist()
    all_values = [headers] + data_rows
    
    # 3. Connect to Sheets API
    service = create_google_service(
        api_name='sheets', 
        api_version='v4', 
        scopes=['https://www.googleapis.com/auth/spreadsheets']
    )
    spreadsheet_id = "1BvR7zrAO6JBraoS_jNsmiO6KHnPSbvTzJZJTCPBEg-8"
    
    # 4. Update the "Source" sheet (starting at A1)
    try:
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range="Source!A1",
            valueInputOption="USER_ENTERED",
            body={'values': all_values}
        ).execute()
        return True, len(df)
    except Exception as e:
        return False, str(e)    
    