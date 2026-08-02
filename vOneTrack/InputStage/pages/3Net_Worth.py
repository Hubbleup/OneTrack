import streamlit as st
import psycopg2
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import yfinance as yf
from datetime import datetime
from sqlalchemy import create_engine, text
import urllib.parse
import threading
import os
import time as time_module
import sys

# --- 1. SETUP & PATHS ---
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

# Internal Imports
from Portfolio_updater import PortfolioUpdater 
from uploadtoGSfromDB import upload_db_to_sheet # This import seems unused here, but we'll leave it.
from event_alerter import check_stock_price_alerts, init_price_alerts_table, send_daily_stock_summary
from utils import show_sync_status, get_db_engine

# --- 2. BACKGROUND SYNC ENGINE ---
if 'sync_started' not in st.session_state:
    updater = PortfolioUpdater()
    # daemon=True ensures the thread closes when the app stops
    thread = threading.Thread(target=updater.run_continuous_sync, args=(300,), daemon=True)
    thread.start()
    st.session_state.sync_started = True

if 'event_sync_started' not in st.session_state:
    def run_scheduled_checks():
        """
        Runs checks at scheduled times.
        - Daily Summary: Runs once a day in the morning.
        - Price Target Alerts: Runs twice a day (morning and evening).
        """
        today = datetime.now().date()
        morning_check_done = False
        evening_check_done = False
        daily_summary_sent = False
        while True:
            now = datetime.now()
            current_date = now.date()

            # Reset daily flags if it's a new day
            if current_date > today:
                today = current_date
                morning_check_done = False
                evening_check_done = False
                daily_summary_sent = False

            # --- Morning Checks (around 9 AM) ---
            if now.hour == 9 and not morning_check_done:
                # Send the main daily summary email
                if not daily_summary_sent:
                    print("--- Sending Daily Portfolio Summary Email ---")
                    send_daily_stock_summary()
                    daily_summary_sent = True

                # Check for specific price target alerts
                print("--- Running Morning Price Target Alert Check ---")
                check_stock_price_alerts()
                morning_check_done = True
            
            # --- Evening Price Target Alert Check (around 5 PM) ---
            if now.hour == 17 and now.minute == 40 and not evening_check_done:
                print("--- Running Evening Price Target Alert Check ---")
                # Also send the daily summary in the evening
                send_daily_stock_summary()
                check_stock_price_alerts()
                evening_check_done = True

            time_module.sleep(60) # Sleep for 1 minute before checking the time again

    alert_thread = threading.Thread(target=run_scheduled_checks, daemon=True)
    alert_thread.start()
    st.session_state.event_sync_started = True

# --- 3. PAGE CONFIG ---
st.set_page_config(page_title="Net Worth Tracker", layout="wide", page_icon="💹")
show_sync_status() 

# --- 4. DATA FETCHING FUNCTIONS ---

@st.cache_data(ttl=3600)
def get_portfolio_with_history(df):
    """Fetches 7-day price history for sparkline charts."""
    history_sparklines = []
    for _, row in df.iterrows():
        ticker, country = row['Ticker'], row['Country']
        symbol = f"{ticker}.AX" if country == "AUS" else (f"{ticker}.BO" if country == "IND" else ticker)
        try:
            h = yf.download(symbol, period="7d", interval="1d", progress=False)['Close']
            history_sparklines.append(h.tolist())
        except:
            history_sparklines.append([]) 
    df['7D Trend'] = history_sparklines
    return df

def get_investment_data():
    """Aggregates investment data from SQLite."""
    engine = get_db_engine()
    # Fetch raw data to apply conditional logic in Python for historical conversions
    query = """
    SELECT "Ticker", "Country", "Units", "Purchase_Value", "Exchange_Rate", "Live_Price", "Purchase_Date"
    FROM "Investment" 
    WHERE "Remain_Balance" > 0 OR "Remain_Balance" IS NULL
    """
    df_raw = pd.read_sql_query(query, engine)
    
    def calculate_cost_aud(row):
        rate = row['Exchange_Rate']
        # Logic: If IND and rate is 1.0/None, it's an unconverted INR value. Apply 0.018 fallback.
        if row['Country'] == 'IND' and (pd.isna(rate) or rate == 1.0):
            return row['Purchase_Value'] * 0.018
        return row['Purchase_Value'] * (rate if not pd.isna(rate) else 1.0)

    df_raw['Total_Cost_AUD'] = df_raw.apply(calculate_cost_aud, axis=1)

    # Re-aggregate to the format expected by the UI
    summary = df_raw.groupby(['Ticker', 'Country']).agg(
        Units=('Units', 'sum'), Total_Cost_AUD=('Total_Cost_AUD', 'sum'),
        Live_Price=('Live_Price', 'max'), Oldest_Purchase=('Purchase_Date', 'min'),
        Newest_Purchase=('Purchase_Date', 'max')
    ).reset_index()
    return summary

def get_latest_super_balance():
    """Fetches the most recent balance for each super fund."""
    engine = get_db_engine()
    try:
        query = """
        SELECT SUM(value_aud) as "Total_Super" FROM (
            SELECT "value_aud", ROW_NUMBER() OVER (PARTITION BY "super_name" ORDER BY "recorded_date" DESC) as rn
            FROM "Super_Tracking"
        ) WHERE rn = 1
        """
        df = pd.read_sql_query(query, engine)
        return df['Total_Super'].iloc[0] if not df.empty and df['Total_Super'].iloc[0] is not None else 0.0
    except:
        return 0.0

def get_total_liabilities():
    """Fetches the sum of all liability balances."""
    engine = get_db_engine()
    try:
        # Ensure the Liabilities table exists before querying
        query = 'SELECT SUM("balance") as "Total_Liabilities" FROM "Liabilities"'
        df = pd.read_sql_query(query, engine)
        return df['Total_Liabilities'].iloc[0] if not df.empty and df['Total_Liabilities'].iloc[0] is not None else 0.0
    except Exception:
        # This will happen if the table doesn't exist yet, which is fine.
        return 0.0

# --- 5. PLOTTING & DISPLAY FUNCTIONS ---

def plot_ticker_performance(ticker, country):
    """Generates the 'Journey' chart showing price trend and purchase points."""
    engine = get_db_engine() # Use the SQLAlchemy engine
    trades = pd.read_sql(
        'SELECT "Purchase_Date", "Purchase_Price", "Units" FROM "Investment" WHERE "Ticker"=%s ORDER BY "Purchase_Date" ASC', 
        engine, params=(ticker,)
    )

    if trades.empty:
        return None

    trades['Purchase_Date'] = pd.to_datetime(trades['Purchase_Date'])
    start_date = trades['Purchase_Date'].min()
    yahoo_sym = f"{ticker}.AX" if country == "AUS" else ticker

    hist_data = yf.download(yahoo_sym, start=start_date, interval="1d", progress=False)
    if hist_data.empty:
        return None
        
    hist_df = hist_data['Close'].reset_index()
    hist_df.columns = ['Date', 'Close']

    fig = go.Figure()
    # Market Price Line
    fig.add_trace(go.Scatter(x=hist_df['Date'], y=hist_df['Close'], mode='lines', name='Price', line=dict(color='#2ca02c', width=2)))
    # Purchase Points
    fig.add_trace(go.Scatter(
        x=trades['Purchase_Date'], y=trades['Purchase_Price'], mode='markers', name='Buy',
        marker=dict(symbol='triangle-up', size=12, color='#1f77b4', line=dict(width=2, color='white')),
        text=trades['Units'].apply(lambda x: f"Bought {x:.0f} units"),
        hoverinfo="text+x+y"
    ))
    fig.update_layout(title=f"Performance Journey: {ticker}", template="plotly_white", hovermode="x unified")
    return fig

def show_performance_summary(df):
    """Displays the regional subtotal and net worth table."""
    st.subheader("🏢 Regional Performance Summary (in AUD)")
    updater = PortfolioUpdater()
    rates = updater.get_live_exchange_rates()
    
    # Ensure IND rate is handled (approx fallback if updater missing it)
    if 'IND' not in rates:
        rates['IND'] = 0.018 # 1 INR ≈ 0.018 AUD

    # Calculate current values
    df['Rate'] = df['Country'].map(rates).fillna(1.0)
    df['Cost_AUD'] = df['Total_Cost_AUD'] 
    df['Value_AUD'] = (df['Units'] * df['Live_Price']) * df['Rate']
    df['Profit_AUD'] = df['Value_AUD'] - df['Cost_AUD']
    df['Return_Pct'] = (df['Profit_AUD'] / df['Cost_AUD']) * 100
    
    # 1. Base regional aggregation with consistent column names
    investment_regional_summary = df.groupby('Country').agg(
        Total_Asset_Value=('Value_AUD', 'sum'),
        Total_Cost=('Cost_AUD', 'sum')
    ).reset_index()
    investment_regional_summary.columns = ['Region', 'Total Asset Value', 'Total Cost']

    summary_rows_list = []

    # 2. Add individual AUS and USA rows
    aus_usa_df = investment_regional_summary[investment_regional_summary['Region'].isin(['AUS', 'USA'])].copy()
    if not aus_usa_df.empty:
        summary_rows_list.append(aus_usa_df)

    # 3. Add AUD + USD Total
    aud_usd_total_value = aus_usa_df['Total Asset Value'].sum()
    aud_usd_total_cost = aus_usa_df['Total Cost'].sum()
    summary_rows_list.append(pd.DataFrame([['AUD + USD Total', aud_usd_total_value, aud_usd_total_cost]], 
                                     columns=['Region', 'Total Asset Value', 'Total Cost']))

    # 4. Add IND Total
    ind_df = investment_regional_summary[investment_regional_summary['Region'] == 'IND'].copy()
    if not ind_df.empty:
        summary_rows_list.append(pd.DataFrame([['IND Total', ind_df['Total Asset Value'].sum(), ind_df['Total Cost'].sum()]], 
                                         columns=['Region', 'Total Asset Value', 'Total Cost']))
    
    # 5. Add Superannuation
    latest_super = get_latest_super_balance()
    summary_rows_list.append(pd.DataFrame([['SUPERANNUATION', latest_super, latest_super]], 
                                     columns=['Region', 'Total Asset Value', 'Total Cost']))
    
    # 6. Add Liabilities (as a negative value)
    total_liabilities = get_total_liabilities()
    summary_rows_list.append(pd.DataFrame([['LIABILITIES (Loans/Mortgage)', -total_liabilities, 0]],
                                     columns=['Region', 'Total Asset Value', 'Total Cost']))

    display_summary = pd.concat(summary_rows_list, ignore_index=True)

    # 7. Calculate Grand Total Net Worth
    total_net_worth_value = df['Value_AUD'].sum() + latest_super - total_liabilities
    total_net_worth_cost = df['Cost_AUD'].sum() + latest_super
    
    total_net_worth_row = pd.DataFrame([['TOTAL NET WORTH', total_net_worth_value, total_net_worth_cost]], 
                                       columns=['Region', 'Total Asset Value', 'Total Cost'])
    display_summary = pd.concat([display_summary, total_net_worth_row], ignore_index=True)

    # Calculate returns for all rows in display_summary
    display_summary['Total Return ($)'] = display_summary['Total Asset Value'] - display_summary['Total Cost']
    # Avoid division by zero for Total Cost
    display_summary['Total Return (%)'] = (display_summary['Total Return ($)'] / display_summary['Total Cost'].replace(0, pd.NA)) * 100
    display_summary['Total Return (%)'] = display_summary['Total Return (%)'].fillna(0) # Fill NA with 0 for cases where Total Cost is 0 (e.g., new super)


    st.table(display_summary.style.format({
        'Total Asset Value': '${:,.2f}', 'Total Cost': '${:,.2f}',
        'Total Return ($)': '${:,.2f}', 'Total Return (%)': '{:.2f}%'
    }))
    return df

def show_stacked_growth_bar(df):
    """Displays bar chart of Invested vs Growth."""
    st.divider()
    st.subheader("📊 Ticker Value: Invested vs. Growth (AUD)")
    df_sorted = df.sort_values('Value_AUD', ascending=False)
    fig = go.Figure()
    fig.add_trace(go.Bar(x=df_sorted['Ticker'], y=df_sorted['Cost_AUD'], name='Invested', marker_color='#1f77b4'))
    fig.add_trace(go.Bar(x=df_sorted['Ticker'], y=df_sorted['Profit_AUD'], name='Growth', marker_color='#2ca02c',
                        text=df_sorted['Return_Pct'].round(1).astype(str) + "%", textposition='outside'))
    fig.update_layout(barmode='stack', template="plotly_white", yaxis=dict(tickprefix="$"))
    st.plotly_chart(fig, width='stretch')

# --- 6. MAIN EXECUTION & TABS ---

st.title("💰 Net Worth & Portfolio Analytics")

# Define Tabs
tab_overview, tab_analytics, tab_alerts = st.tabs(["📊 Portfolio Overview", "📈 Ticker Performance Journey", "🔔 Price Alerts"])

# Data Preparation
df_raw = get_investment_data()

if not df_raw.empty:
    # --- TAB 1: PORTFOLIO OVERVIEW ---
    with tab_overview:
        df = show_performance_summary(df_raw)
        
        # Years Holding Period Calculation
        today = datetime.now()
        df['Oldest_P'] = pd.to_datetime(df['Oldest_Purchase'], errors='coerce')
        df['Age (Years)'] = ((today - df['Oldest_P']).dt.days / 365.25).fillna(0).map(lambda x: f"{x:.1f} years")

        # Get Sparkline Data
        with st.spinner("Loading market trends..."):
            df = get_portfolio_with_history(df)

        st.subheader("📊 Consolidated Portfolio Analytics")
        st.dataframe(
            df.style.map(lambda x: f'color: {"#d62728" if x < 0 else "#2ca02c"}; font-weight: bold;', subset=['Profit_AUD', 'Return_Pct']),
            column_config={
                "Units": st.column_config.NumberColumn("Units", format="%.0f"),
                "Live_Price": st.column_config.NumberColumn("Live Price", format="$%.2f"),
                "7D Trend": st.column_config.LineChartColumn("7D History"),
                "Value_AUD": st.column_config.NumberColumn("Value (AUD)", format="$%.2f"),
                "Profit_AUD": st.column_config.NumberColumn("Profit", format="$%.2f"),
                "Return_Pct": st.column_config.NumberColumn("Return %", format="%.2f%%"),
            },
            column_order=("Ticker", "7D Trend", "Units", "Live_Price", "Value_AUD", "Profit_AUD", "Return_Pct", "Age (Years)"),
            hide_index=True, width='stretch'
        )
        
        show_stacked_growth_bar(df)

    # --- TAB 2: TICKER PERFORMANCE JOURNEY ---
    with tab_analytics:
        st.subheader("🚀 Ticker Performance Journey")
        st.caption("Visualise price movement and purchase points from your first trade.")
        
        all_tickers = df_raw['Ticker'].unique().tolist()

        if all_tickers:
            selected = st.selectbox("Select Ticker to Analyse", all_tickers, key="trend_selector")
            
            # Fetch country for suffix logic
            ticker_info = df_raw[df_raw['Ticker'] == selected].iloc[0]
            
            with st.spinner(f"Fetching journey for {selected}..."):
                fig = plot_ticker_performance(selected, ticker_info['Country'])
            
            if fig:
                st.plotly_chart(fig, width='stretch')
            else:
                st.info(f"Market data for {selected} is currently unavailable.")
else:
    st.warning("No investment data found. Please add assets in the Input Stage.")

# --- TAB 3: PRICE ALERTS ---
with tab_alerts:
    st.subheader("🔔 Manage Stock Price Alerts")
    init_price_alerts_table() # Ensure table exists

    # The form is now always available, regardless of whether the portfolio is empty.
    with st.form("add_alert_form", clear_on_submit=True):
        st.markdown("##### Create a New Alert")
        c1, c2, c3 = st.columns(3)
        with c1:
            # Changed to a text input to allow any stock ticker.
            alert_ticker = st.text_input("Enter Ticker Symbol", placeholder="e.g., NVDA or CBA.AX")
        with c2:
            alert_condition = st.selectbox("Condition", ["Price goes ABOVE", "Price goes BELOW"])
        with c3:
            alert_price = st.number_input("Target Price ($)", min_value=0.01, format="%.2f")

        if st.form_submit_button("💾 Set Alert", use_container_width=True, type="primary"):
            if alert_ticker and alert_price > 0:
                ticker_to_save = alert_ticker.strip().upper()
                condition = "above" if "ABOVE" in alert_condition else "below"
                try:
                    engine = get_db_engine()
                    with engine.connect() as conn:
                        conn.execute(text("""
                            INSERT INTO "PriceAlerts" (ticker, condition, target_price)
                            VALUES (:ticker, :condition, :price)
                        """), {'ticker': ticker_to_save, 'condition': condition, 'price': alert_price})
                        conn.commit()
                    st.success(f"Alert set for {ticker_to_save} to trigger when price goes {condition} ${alert_price:,.2f}!")
                except Exception as e:
                    st.error(f"Failed to save alert: {e}")
            else:
                st.warning("Please provide a ticker and a target price.")

    st.divider()
    st.markdown("##### Current & Past Alerts")
    try:
        alerts_history_df = pd.read_sql('SELECT ticker, condition, target_price, status, created_at, triggered_at FROM "PriceAlerts" ORDER BY created_at DESC', get_db_engine())
        st.dataframe(alerts_history_df.style.format({'target_price': '${:,.2f}'}),
                     column_config={
                        "created_at": st.column_config.DatetimeColumn("Set On", format="D MMM YYYY, h:mm A"),
                        "triggered_at": st.column_config.DatetimeColumn("Triggered On", format="D MMM YYYY, h:mm A"),
                     },
                     use_container_width=True, hide_index=True)
    except Exception as e:
        st.info(f"No alerts have been set yet. Error: {e}")

    # --- Test Email Button ---
    st.divider()
    st.markdown("##### 📧 Email Configuration Test")
    if st.button("Send Test Email", help="This will send a test email using the credentials in your secrets file."):
        from event_alerter import send_email_alert
        subject = "OneTrack - Test Email"
        body = "<html><body>This is a test email to confirm your SMTP settings are correct. If you received this, your alerts are working!</body></html>"
        send_email_alert(subject, body)

# Sidebar Actions
if st.sidebar.button("📤 Manual Sync to Google Sheets"):
    upload_db_to_sheet()
    st.sidebar.success("Sync complete!")
