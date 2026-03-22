import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import yfinance as yf
from datetime import datetime
from Portfolio_updater import PortfolioUpdater 
from uploadtoGSfromDB import upload_db_to_sheet

# --- 1. DATA FETCHING (Now with Sparkline History) ---
@st.cache_data(ttl=3600) # Cache history for 1 hour to keep the app fast
def get_portfolio_with_history(df):
    """Fetches last 7 days of prices for each ticker to create sparklines."""
    history_sparklines = []
    for _, row in df.iterrows():
        ticker = row['Ticker']
        country = row['Country']
        symbol = f"{ticker}.AX" if country == "AUS" else (f"{ticker}.NS" if country == "IND" else ticker)
        try:
            # Fetch 7 days of history
            h = yf.download(symbol, period="7d", interval="1d", progress=False)['Close']
            # Convert to list for Streamlit's LineChartColumn
            history_sparklines.append(h.tolist())
        except:
            history_sparklines.append([]) 
    df['7D Trend'] = history_sparklines
    return df

def get_investment_data():
    conn = sqlite3.connect("onetrack.db")
    # Updated Query: Summing values to consolidate trades (like SHOP)
    query = """
    SELECT 
        Ticker, 
        Country, 
        SUM(Units) as Units, 
        SUM(Purchase_Value) as Total_Cost_Local,
        MAX(Live_Price) as Live_Price,
        MIN(Purchase_Date) as Oldest_Purchase,
        MAX(Purchase_Date) as Newest_Purchase
    FROM Investment 
    GROUP BY Ticker, Country
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

# --- 2. STYLING HELPERS ---
def color_returns(val):
    """Assigns Red for negative and Green for positive returns."""
    if isinstance(val, (int, float)):
        color = '#d62728' if val < 0 else '#2ca02c'
        return f'color: {color}; font-weight: bold;'
    return ''

# --- 3. DYNAMIC SUMMARY LOGIC ---
def show_performance_summary(df):
    st.subheader("🏢 Regional Performance Summary (in AUD)")
    updater = PortfolioUpdater("onetrack.db")
    rates = updater.get_live_exchange_rates()
    st.caption(f"💱 Live Rates Used: USD/AUD: {rates['USA']:.4f} | INR/AUD: {rates['IND']:.4f}")

    # Apply conversions
    df['Rate'] = df['Country'].map(rates).fillna(1.0)
    df['Cost_AUD'] = df['Total_Cost_Local'] * df['Rate']
    df['Value_AUD'] = (df['Units'] * df['Live_Price']) * df['Rate']
    df['Profit_AUD'] = df['Value_AUD'] - df['Cost_AUD']
    df['Return_Pct'] = (df['Profit_AUD'] / df['Cost_AUD']) * 100
    
    summary = df.groupby('Country').agg({
        'Value_AUD': 'sum',
        'Cost_AUD': 'sum'
    }).reset_index()

    total_val = summary['Value_AUD'].sum()
    total_cost = summary['Cost_AUD'].sum()
    
    summary.columns = ['Region', 'Total Asset Value', 'Total Cost']
    total_row = pd.DataFrame([['TOTAL PORTFOLIO', total_val, total_cost]], columns=summary.columns)
    summary = pd.concat([summary, total_row], ignore_index=True)
    
    summary['Total Return ($)'] = summary['Total Asset Value'] - summary['Total Cost']
    summary['Total Return (%)'] = (summary['Total Return ($)'] / summary['Total Cost']) * 100

    st.table(summary.style.format({
        'Total Asset Value': '${:,.2f}',
        'Total Cost': '${:,.2f}',
        'Total Return ($)': '${:,.2f}',
        'Total Return (%)': '{:.2f}%'
    }))
    return df 

# --- 4. STACKED BAR CHART ---
def show_stacked_growth_bar(df):
    st.divider()
    st.subheader("📊 Ticker Value: Invested vs. Growth (AUD)")
    df_sorted = df.sort_values('Value_AUD', ascending=False)
    fig = go.Figure()
    fig.add_trace(go.Bar(x=df_sorted['Ticker'], y=df_sorted['Cost_AUD'], name='Invested', marker_color='#1f77b4'))
    fig.add_trace(go.Bar(x=df_sorted['Ticker'], y=df_sorted['Profit_AUD'], name='Growth', marker_color='#2ca02c',
                         text=df_sorted['Return_Pct'].round(1).astype(str) + "%", textposition='outside'))
    fig.update_layout(barmode='stack', hovermode="x unified", template="plotly_white", yaxis=dict(tickprefix="$"))
    st.plotly_chart(fig, use_container_width=True)

# --- 5. TICKER LINE CHART ---
def show_ticker_growth_chart(df):
    st.divider()
    st.header("📈 Individual Ticker Growth")
    selected_ticker = st.selectbox("Select a Ticker to View Performance", df['Ticker'].unique())
    ticker_row = df[df['Ticker'] == selected_ticker].iloc[0]
    
    try:
        # Standardise date for yfinance
        #clean_date = pd.to_datetime(ticker_row['Oldest_Purchase'], dayfirst=True).strftime('%Y-%m-%d')
        clean_date = pd.to_datetime(ticker_row['Oldest_Purchase'], dayfirst=True, format='mixed').strftime('%Y-%m-%d')

        country = ticker_row['Country']
        symbol = f"{selected_ticker}.AX" if country == "AUS" else (f"{selected_ticker}.NS" if country == "IND" else selected_ticker)
        
        hist_data = yf.download(symbol, start=clean_date, interval="1d", progress=False)
        if not hist_data.empty:
            hist_data = hist_data['Close'].reset_index()
            hist_data.columns = ['Date', 'Price']
            initial_p = hist_data['Price'].iloc[0]
            hist_data['Growth %'] = ((hist_data['Price'] - initial_p) / initial_p) * 100
            fig = px.line(hist_data, x='Date', y='Growth %', title=f"{selected_ticker} Growth since {clean_date}")
            st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.error(f"Error fetching chart: {e}")

# --- MAIN UI ---
st.title("💰 Net Worth & Investment Tracker")

col1, col2 = st.columns(2)
with col1:
    if st.button("🔄 1. Refresh Local Prices"):
        updater = PortfolioUpdater("onetrack.db")
        with st.spinner("Updating..."):
            updater.refresh_live_prices()
        st.rerun()

with col2:
    if st.button("☁️ 2. Push to Google Sheets"):
        success, message = upload_db_to_sheet()
        if success: st.success(f"Synced {message} rows!")
        else: st.error(f"Failed: {message}")

df_raw = get_investment_data()

if not df_raw.empty:
    # Captures AUD conversions
    df = show_performance_summary(df_raw)

    # Calculate Holding Periods
    today = datetime.now()
    df['Oldest_P'] = pd.to_datetime(df['Oldest_Purchase'], dayfirst=True, errors='coerce', format='mixed')
    df['Newest_P'] = pd.to_datetime(df['Newest_Purchase'], dayfirst=True, errors='coerce', format='mixed')
    df = df.dropna(subset=['Oldest_P', 'Newest_P']) 
    df['Age (Days)'] = (today - df['Oldest_P']).dt.days.astype(str) + " - " + (today - df['Newest_P']).dt.days.astype(str)

    # Fetch Sparklines
    with st.spinner("Fetching 7D Sparklines..."):
        df = get_portfolio_with_history(df)

    st.subheader("📊 Consolidated Portfolio Analytics")
    
    # Styled Dataframe with Heatmap
    styled_df = df.style.applymap(color_returns, subset=['Profit_AUD', 'Return_Pct'])
    
    st.dataframe(
        styled_df,
        column_config={
            "Units": st.column_config.NumberColumn("Held Units", help="Total number of shares/units held", format="%.0f"),
            "7D Trend": st.column_config.LineChartColumn("7D History", width="medium"),
            "Value_AUD": st.column_config.NumberColumn("Value (AUD)", format="$%.2f"),
            "Profit_AUD": st.column_config.NumberColumn("Return $", format="$%.2f"),
            "Return_Pct": st.column_config.NumberColumn("Return %", format="%.2f%%"),
            "Live_Price": st.column_config.NumberColumn("Live Price", format="$%.2f"),
        },
        column_order=("Ticker", "7D Trend", "Units", "Live_Price", "Value_AUD", "Profit_AUD", "Return_Pct", "Age (Days)"),
        hide_index=True,
        use_container_width=True
    )

    show_stacked_growth_bar(df)

    st.subheader("🥧 Asset Distribution")
    st.plotly_chart(px.pie(df, values='Value_AUD', names='Country', hole=0.4), use_container_width=True)

    show_ticker_growth_chart(df)
else:
    st.info("No investment data available.")
