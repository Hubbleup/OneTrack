import streamlit as st
from Portfolio_updater import PortfolioUpdater # Import your existing class

st.title("💰 Net Worth")

if st.button("🔄 Sync Live Prices"):
    updater = PortfolioUpdater("onetrack.db")
    with st.spinner("Updating prices via yfinance..."):
        updater.refresh_live_prices()
    st.success("Portfolio Updated!")
