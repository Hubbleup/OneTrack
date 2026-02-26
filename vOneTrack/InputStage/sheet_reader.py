"""
sheet_reader.py - Google Sheets Data Reader
Handles reading and processing data from Google Sheets after authentication
"""

from security import get_sheet_service, get_sheet_id


# sheet_reader.py

# sheet_reader.py

def get_specific_tabs_data(target_tabs):
    service = get_sheet_service()
    sheetId = get_sheet_id()
    
    all_tab_results = {}

    for tab in target_tabs:
        try:
            # The single quotes '{tab}' handle "US Stocks" and "Managed Funds" correctly
            range_name = f"'{tab}'!A22:P500" 
            
            result = service.spreadsheets().values().get(
                spreadsheetId=sheetId, 
                range=range_name
            ).execute()
            
            rows = result.get('values', [])
            
            if rows:
                all_tab_results[tab] = rows
                print(f"✅ Successfully read {len(rows)} rows from: {tab}")
            else:
                print(f"⚠️ Tab '{tab}' has no data from Row 22 onwards.")
                
        except Exception as e:
            print(f"❌ Error reading tab '{tab}': {e}")
            
    return all_tab_results





# # (Ensure your imports for get_sheet_service, etc. are at the top)

# def get_rows_from_sheets():
#     service = get_sheet_service()
#     sheetId = get_sheet_id()
    
#     sheet = service.spreadsheets()
#     # Fetch the data
#     result = sheet.values().get(spreadsheetId=sheetId, range="Stocks!A23:M23").execute()
    
#     # Get the values
#     rows = result.get('values', [])
#     print("Data from Sheet:", rows)
#     return rows  # This is the "hand-off" to the next file
