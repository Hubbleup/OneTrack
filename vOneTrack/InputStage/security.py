"""
security.py - Google Sheets API Authentication and Configuration
Handles secure credential loading and sheet access setup
"""

import os
import json
import streamlit as st

from google.oauth2 import service_account
from googleapiclient.discovery import build


def get_sheet_service():
    """
    Initialize and return Google Sheets API service with credentials.
    
    Returns:
        googleapiclient.discovery.Resource: Authenticated sheets service
        
    Raises:
        FileNotFoundError: If credential or config files are not found
    """
    Scope = ['https://www.googleapis.com/auth/spreadsheets']
    
    # Check if running on Streamlit Cloud using secrets
    if "gcp_service_account" in st.secrets:
        creds_info = dict(st.secrets["gcp_service_account"])
        credentials = service_account.Credentials.from_service_account_info(creds_info, scopes=Scope)
    else:
        # Fallback for local development
        base_dir = os.path.dirname(__file__)
        service_account_file = os.path.join(base_dir, "gcpkey.json")
        credentials = service_account.Credentials.from_service_account_file(
            service_account_file, 
            scopes=Scope
        )
    
    # Build and return the service
    service = build('sheets', 'v4', credentials=credentials)
    return service


def get_sheet_id():
    """
    Load the Google Sheet ID from config.json.
    
    Returns:
        str: The Google Sheet ID
        
    Raises:
        FileNotFoundError: If config.json is not found
        KeyError: If 'googlesheetId' key is missing from config
    """
    base_dir = os.path.dirname(__file__)
    config_path = os.path.join(base_dir, "config.json")
    
    with open(config_path, 'r') as f:
        config_data = json.load(f)
    
    return config_data["googlesheetId"]


if __name__ == "__main__":
    # Test authentication
    try:
        service = get_sheet_service()
        sheet_id = get_sheet_id()
        print(f"✓ Authentication successful!")
        print(f"✓ Sheet ID loaded: {sheet_id}")
    except FileNotFoundError as e:
        print(f"✗ Error: {e}")
    except Exception as e:
        print(f"✗ Authentication failed: {e}")
