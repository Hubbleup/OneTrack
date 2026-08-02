import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
import time
from sqlalchemy import create_engine, text
import urllib.parse
import yfinance as yf
from utils import get_db_engine as get_engine

def send_email_alert(subject, body, to_email=None):
    """Sends an email alert using credentials from Streamlit secrets."""
    if to_email is None:
        to_email = st.secrets["email"]["recipient_email"]
    try:
        # Get email credentials from secrets
        sender_email = st.secrets["email"]["sender_email"]
        sender_password = st.secrets["email"]["sender_password"]
        smtp_server = st.secrets["email"]["smtp_server"]
        smtp_port = st.secrets["email"]["smtp_port"]

        # Create the email
        msg = MIMEText(body, 'html') # Set body type to HTML
        msg['Subject'] = subject
        msg['From'] = sender_email
        msg['To'] = to_email

        # Send the email
        with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, [to_email], msg.as_string())
        st.toast(f"Alert sent for: {subject}")
        print(f"Email alert sent to {to_email} for: {subject}")
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        st.error(f"Failed to send email alert: {e}")
        return False

def init_price_alerts_table():
    """Initializes the PriceAlerts table if it doesn't exist."""
    engine = get_engine()
    if not engine: return

    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS "PriceAlerts" (
                "id" SERIAL PRIMARY KEY,
                "ticker" TEXT NOT NULL,
                "condition" TEXT NOT NULL, -- 'above' or 'below'
                "target_price" REAL NOT NULL,
                "status" TEXT DEFAULT 'active', -- 'active', 'triggered'
                "created_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                "triggered_at" TIMESTAMP
            );
        """))
        conn.commit()

def check_stock_price_alerts():
    """
    Checks active price alerts against live stock prices and sends notifications.
    This function is designed to be run in a background thread.
    """
    engine = get_engine()
    if not engine:
        print("Price Alert Check: Could not get DB engine.")
        return

    try:
        # 1. Get all active alerts
        alerts_df = pd.read_sql('SELECT * FROM "PriceAlerts" WHERE status = \'active\'', engine)
        if alerts_df.empty:
            return # No active alerts to check

        # 2. Get live prices for the tickers in the alerts
        tickers_to_check = alerts_df['ticker'].unique().tolist()
        prices_df = pd.read_sql('SELECT "Ticker", "Live_Price" FROM "Investment" WHERE "Ticker" = ANY(%(tickers)s)', engine, params={'tickers': tickers_to_check})
        live_prices = prices_df.set_index('Ticker')['Live_Price'].to_dict()

        # 3. Check each alert
        for _, alert in alerts_df.iterrows():
            live_price = live_prices.get(alert['ticker'])
            if live_price is None:
                continue

            condition_met = (alert['condition'] == 'above' and live_price > alert['target_price']) or \
                            (alert['condition'] == 'below' and live_price < alert['target_price'])

            if condition_met:
                subject = f"🚀 Price Alert Triggered for {alert['ticker']}!"
                body = f"Heads up! Your price alert for {alert['ticker']} has been triggered.\n\n- Target: {alert['condition'].capitalize()} ${alert['target_price']:,.2f}\n- Current Price: ${live_price:,.2f}\n\nThis alert has now been deactivated."
                send_email_alert(subject, body)
                # Deactivate the alert to prevent spam
                engine.execute(text('UPDATE "PriceAlerts" SET status = \'triggered\', triggered_at = NOW() WHERE id = :id'), {'id': alert['id']})
    except Exception as e:
        print(f"Error in check_stock_price_alerts: {e}")

def check_website_for_events():
    """
    Scrapes a target website for events and sends alerts.
    NOTE: This is a template. The URL, tags, and logic must be
    customized for the specific website you want to scrape.
    """
    # --- CONFIGURATION (NEEDS CUSTOMIZATION) ---
    # Example: DailyFX economic calendar. You must inspect the target
    # website's HTML to find the correct tags and structure.
    URL = "https://www.dailyfx.com/economic-calendar"
    # This is a hypothetical class name. You need to find the real one.
    EVENT_ROW_CLASS = "event-row-class-name" 
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'}
        response = requests.get(URL, headers=headers)
        response.raise_for_status() # Raise an exception for bad status codes

        soup = BeautifulSoup(response.content, 'html.parser')

        # Find all event rows. This selector is an EXAMPLE.
        events = soup.find_all("div", class_=EVENT_ROW_CLASS)
        
        today_str = datetime.now().strftime("%Y-%m-%d")

        for event in events:
            # EXAMPLE: Extract text. You will need to adjust these selectors.
            event_date = event.find("span", class_="date-class").text
            event_name = event.find("span", class_="event-name-class").text
            
            # Check if the event is today and contains a keyword of interest
            if today_str in event_date and "CPI" in event_name.upper():
                subject = f"Economic Event Alert: {event_name}"
                body = f"An important economic event is scheduled for today:\n\nEvent: {event_name}\nDate: {event_date}\n\nSource: {URL}"
                send_email_alert(subject, body)

    except Exception as e:
        print(f"Failed to scrape or process website events: {e}")

def send_daily_stock_summary():
    """
    Fetches the previous day's performance for all stocks and sends a summary email.
    """
    engine = get_engine()
    if not engine:
        print("Daily Summary: Could not get DB engine.")
        return

    try:
        # 1. Get all unique tickers from the portfolio
        holdings_df = pd.read_sql('SELECT DISTINCT "Ticker", "Country" FROM "Investment" WHERE "Units" > 0', engine)
        if holdings_df.empty:
            print("Daily Summary: No holdings found to summarize.")
            return

        # 2. Prepare ticker symbols for yfinance
        symbols = []
        for _, row in holdings_df.iterrows():
            symbol = f"{row['Ticker']}.AX" if row['Country'] == 'AUS' else row['Ticker']
            symbols.append(symbol)

        # 3. Fetch previous day's data
        # Using period='2d' to safely get the last trading day's data
        data = yf.download(symbols, period="2d", group_by='ticker', progress=False)
        if data.empty:
            print("Daily Summary: Could not download market data.")
            return

        # 4. Build the HTML table for the email
        summary_rows = ""
        for ticker, country in holdings_df.values:
            symbol = f"{ticker}.AX" if country == 'AUS' else ticker
            
            # yfinance returns a multi-level column index when group_by is used
            stock_data = data[symbol] if len(symbols) > 1 else data
            
            if not stock_data.empty and len(stock_data) > 1:
                prev_day = stock_data.iloc[-1]
                day_before = stock_data.iloc[-2]

                open_price = prev_day['Open']
                close_price = prev_day['Close']
                change_pct = ((close_price - day_before['Close']) / day_before['Close']) * 100
                
                color = "green" if change_pct >= 0 else "red"
                
                summary_rows += f"""
                <tr>
                    <td><b>{ticker}</b></td>
                    <td style="color:{color};">{change_pct:+.2f}%</td>
                    <td>${open_price:,.2f}</td>
                    <td>${close_price:,.2f}</td>
                </tr>
                """
        
        html_body = f"<html><body><h2>📈 Daily Market Summary</h2><table border='1' cellpadding='5' cellspacing='0' style='border-collapse: collapse;'><tr><th>Stock</th><th>Change</th><th>Open</th><th>Close</th></tr>{summary_rows}</table></body></html>"
        send_email_alert("Your Daily Portfolio Summary", html_body)

    except Exception as e:
        print(f"Error in send_daily_stock_summary: {e}")
