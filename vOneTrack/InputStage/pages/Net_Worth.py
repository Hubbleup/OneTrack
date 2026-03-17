import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import yfinance as yf
from datetime import datetime
from Portfolio_updater import PortfolioUpdater 
from uploadtoGSfromDB import upload_db_to_sheet

# 1. FETCH DATA (Updated to Aggregate multiple purchases of the same ticker)
def get_investment_data():
    conn = sqlite3.connect("onetrack.db")
    # Using SQL to sum units and average prices so 1 ticker = 1 row in the app
    query = """
    SELECT 
        Ticker, 
        Country, 
        SUM(Units) as Units, 
        AVG(Purchase_Price) as Purchase_Price, 
        AVG(Live_Price) as Live_Price,
        SUM(Live_Value) as Live_Value,
        MIN(Purchase_Date) as Purchase_Date
    FROM Investment 
    GROUP BY Ticker, Country
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

# 2. DYNAMIC SUMMARY LOGIC
def show_performance_summary(df):
    st.subheader("🏢 Regional Performance Summary (in AUD)")
    
    updater = PortfolioUpdater("onetrack.db")
    rates = updater.get_live_exchange_rates()
    
    st.caption(f"💱 Live Rates Used: USD/AUD: {rates['USA']:.4f} | INR/AUD: {rates['IND']:.4f}")

    # Apply conversions to the aggregated totals
    df['Rate'] = df['Country'].map(rates).fillna(1.0)
    df['Cost_AUD'] = (df['Units'] * df['Purchase_Price']) * df['Rate']
    df['Value_AUD'] = df['Live_Value'] * df['Rate']
    df['Profit_AUD'] = df['Value_AUD'] - df['Cost_AUD']
    
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

# 3. STACKED BAR CHART (Corrected with Tooltip Formatting)
def show_stacked_growth_bar(df):
    st.divider()
    st.subheader("📊 Ticker Value: Invested vs. Growth (AUD)")
    
    # Sort by value to make the chart look cleaner
    df = df.sort_values('Value_AUD', ascending=False)
    
    fig = go.Figure()
    
    # Base: Amount Invested
    fig.add_trace(go.Bar(
        x=df['Ticker'], y=df['Cost_AUD'],
        name='Amount Invested', marker_color='#1f77b4',
        hovertemplate='Invested: $%{y:,.2f}<extra></extra>'
    ))
    
    # Top: Profit/Growth
    fig.add_trace(go.Bar(
        x=df['Ticker'], y=df['Profit_AUD'],
        name='Amount Grown', marker_color='#2ca02c',
        # Adding a % label that appears on the bar
        text=((df['Profit_AUD'] / df['Cost_AUD']) * 100).round(1).astype(str) + "%",
        textposition='outside',
        hovertemplate='Growth: $%{y:,.2f}<extra></extra>'
    ))

    fig.update_layout(
        barmode='stack',
        xaxis_title="Ticker",
        yaxis_title="Total Value (AUD)",
        hovermode="x unified",
        template="plotly_white",
        yaxis=dict(tickprefix="$", tickformat=",.0f")
    )
    st.plotly_chart(fig, use_container_width=True)

# 4. INDIVIDUAL TICKER LINE CHART
def show_ticker_growth_chart(df):
    st.divider()
    st.header("📈 Individual Ticker Growth")
    ticker_options = df['Ticker'].unique()
    selected_ticker = st.selectbox("Select a Ticker to View Performance", ticker_options)
    
    # Since df is aggregated, iloc[0] now correctly represents the ticker's combined data
    ticker_row = df[df['Ticker'] == selected_ticker].iloc[0]
    # 2. Extract and Convert the date to YYYY-MM-DD
    raw_date = ticker_row['Purchase_Date']
    try:
        # dayfirst=True tells Pandas your format is dd/MM/YYYY
        purchase_date_str = pd.to_datetime(raw_date, dayfirst=True).strftime('%Y-%m-%d')
    except Exception:
        # Fallback if the date is already in the correct format or is 'None'
        purchase_date_str = raw_date 
    
    try:
        country = ticker_row['Country']
        symbol = f"{selected_ticker}.AX" if country == "AUS" else (f"{selected_ticker}.NS" if country == "IND" else selected_ticker)
        
        hist_data = yf.download(symbol, start=purchase_date_str, interval="1d", progress=False)
        
        if not hist_data.empty:
            hist_data = hist_data['Close'].reset_index()
            hist_data.columns = ['Date', 'Price']
            initial_price = hist_data['Price'].iloc[0]
            hist_data['Growth %'] = ((hist_data['Price'] - initial_price) / initial_price) * 100
            
            fig = px.line(hist_data, x='Date', y='Growth %', 
                          title=f"Growth of {selected_ticker} since {purchase_date_str}",
                          template="plotly_white")
            fig.add_hline(y=0, line_dash="dash", line_color="red")
            st.plotly_chart(fig, use_container_width=True)
            
            # Show current vs initial price
            st.metric(label=f"Current {selected_ticker} Price", 
                      value=f"${hist_data['Price'].iloc[-1]:,.2f}", 
                      delta=f"{hist_data['Growth %'].iloc[-1]:.2f}% since purchase")
    except Exception as e:
        st.error(f"Error fetching historical data: {e}")

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

df = get_investment_data()

if not df.empty:
    df = show_performance_summary(df)

    st.subheader("📊 Detailed Portfolio")
    st.dataframe(df, use_container_width=True)

    show_stacked_growth_bar(df)

    st.subheader("🥧 Asset Distribution")
    fig_pie = px.pie(df, values='Value_AUD', names='Country', hole=0.4,
                     title='Portfolio Allocation (AUD)')
    st.plotly_chart(fig_pie, use_container_width=True)

    show_ticker_growth_chart(df)
else:
    st.info("No investment data available.")
