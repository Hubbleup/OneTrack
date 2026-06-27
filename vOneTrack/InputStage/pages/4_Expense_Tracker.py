import streamlit as st
import pandas as pd
import psycopg2
import pdfplumber
import re
from datetime import datetime
import io
from sqlalchemy import create_engine
import urllib.parse

# --- 1. DATABASE SETUP & UTILITIES ---

def get_engine():
    """Creates a SQLAlchemy engine from Streamlit secrets."""
    try:
        user = urllib.parse.quote_plus(st.secrets['supabase']['user'])
        password = urllib.parse.quote_plus(st.secrets['supabase']['password'])
        host = st.secrets['supabase']['host']
        port = st.secrets['supabase']['port']
        database = st.secrets['supabase']['database']
        db_url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"
        return create_engine(db_url)
    except Exception as e:
        st.error(f"DB Connection Error: {e}")
        return None

def init_db_tables():
    """Initializes the Liabilities and Expenses tables if they don't exist."""
    engine = get_engine()
    if not engine: return

    with engine.connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS "Liabilities" (
                "id" SERIAL PRIMARY KEY,
                "name" TEXT NOT NULL,
                "type" TEXT NOT NULL,
                "balance" REAL NOT NULL,
                "last_updated" DATE NOT NULL,
                "created_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS "Expenses" (
                "id" SERIAL PRIMARY KEY,
                "expense_date" DATE NOT NULL,
                "vendor" TEXT,
                "category" TEXT,
                "amount" REAL NOT NULL,
                "description" TEXT,
                "created_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # Sync sequences
        conn.execute("""
            SELECT setval(pg_get_serial_sequence('public."Liabilities"', 'id'), 
                          COALESCE((SELECT MAX("id") FROM "Liabilities"), 0) + 1, false);
        """)
        conn.execute("""
            SELECT setval(pg_get_serial_sequence('public."Expenses"', 'id'), 
                          COALESCE((SELECT MAX("id") FROM "Expenses"), 0) + 1, false);
        """)

def save_liability(name, l_type, balance, updated_date):
    """Saves a new liability or updates an existing one by name."""
    engine = get_engine()
    if not engine: return False
    try:
        with engine.connect() as conn:
            # Check if liability with this name exists
            res = conn.execute('SELECT id FROM "Liabilities" WHERE name = %s', (name,)).fetchone()
            if res: # Update
                conn.execute('UPDATE "Liabilities" SET balance = %s, last_updated = %s WHERE id = %s', (balance, updated_date, res[0]))
            else: # Insert
                conn.execute('INSERT INTO "Liabilities" (name, type, balance, last_updated) VALUES (%s, %s, %s, %s)',
                             (name, l_type, balance, updated_date))
        return True
    except Exception as e:
        st.error(f"Error saving liability: {e}")
        return False

def extract_expense_from_pdf(file):
    """Extracts total amount from a PDF receipt using regex."""
    try:
        with pdfplumber.open(io.BytesIO(file.getvalue())) as pdf:
            text = ""
            for page in pdf.pages:
                text += page.extract_text()

            # Regex to find 'Total', 'Total Amount', etc., and capture the following number
            match = re.search(r'Total(?: Amount)?[:\s]*\$?([\d,]+\.\d{2})', text, re.IGNORECASE)
            if match:
                amount = float(match.group(1).replace(',', ''))
                return amount
    except Exception as e:
        st.error(f"PDF parsing failed: {e}")
    return None

# --- 2. UI & PAGE LOGIC ---

st.set_page_config(page_title="Expense Tracker", layout="wide", page_icon="💳")
st.title("💳 Expense & Liability Console")

# Initialize database tables on first run
init_db_tables()

tab_liability, tab_expense = st.tabs(["🏦 Liabilities (Mortgage, Loans)", "🧾 Expense Logging"])

# --- Liability Tab ---
with tab_liability:
    st.subheader("Log or Update a Liability")
    with st.form("liability_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            name = st.text_input("Liability Name", placeholder="e.g., Home Mortgage")
            l_type = st.selectbox("Type", ["Mortgage", "Car Loan", "Personal Loan", "Credit Card", "Other"])
        with c2:
            balance = st.number_input("Current Balance ($)", min_value=0.0, format="%.2f")
        with c3:
            updated_date = st.date_input("Balance as of", datetime.now())

        if st.form_submit_button("💾 Save Liability", use_container_width=True):
            if name and balance > 0:
                if save_liability(name, l_type, balance, updated_date):
                    st.success(f"Liability '{name}' saved successfully!")
                    st.rerun()
            else:
                st.warning("Please provide a name and balance.")

    st.divider()
    st.subheader("Current Liabilities")
    try:
        df_liabilities = pd.read_sql('SELECT name as "Name", type as "Type", balance as "Balance", last_updated as "Last Updated" FROM "Liabilities" ORDER BY name', get_engine())
        st.dataframe(df_liabilities.style.format({"Balance": "${:,.2f}"}), use_container_width=True, hide_index=True)
    except Exception as e:
        st.info("No liabilities logged yet.")

# --- Expense Tab ---
with tab_expense:
    st.subheader("Scan a Receipt (PDF)")
    uploaded_file = st.file_uploader("Upload a receipt PDF to auto-fill the amount", type="pdf")

    extracted_amount = 0.0
    if uploaded_file:
        extracted_amount = extract_expense_from_pdf(uploaded_file)
        if extracted_amount:
            st.info(f"🤖 Amount detected: ${extracted_amount:,.2f}")

    st.subheader("Log an Expense Manually")
    with st.form("expense_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            expense_date = st.date_input("Expense Date", datetime.now())
            vendor = st.text_input("Vendor")
        with c2:
            category = st.selectbox("Category", ["Groceries", "Utilities", "Transport", "Dining", "Shopping", "Health", "Other"])
            amount = st.number_input("Amount ($)", value=extracted_amount, min_value=0.0, format="%.2f")
        with c3:
            description = st.text_area("Description (Optional)")

        if st.form_submit_button("➕ Add Expense", use_container_width=True):
            st.warning("Expense logging is currently a UI demonstration and does not save to the database yet.")
            # To complete this, you would create a save_expense() function similar to save_liability()
            # and call it here.
            st.success("Expense form submitted (demo).")