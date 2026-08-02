import streamlit as st
import pandas as pd
import psycopg2
import pdfplumber
import re
from datetime import datetime
import io
from sqlalchemy import create_engine, text
from pdf2image import convert_from_bytes
import pytesseract
import logging
import sys
import urllib.parse

# --- 1. DATABASE SETUP & UTILITIES ---

# --- Logging Setup ---
# This configures logging to output to the console (stdout), which is visible
# in the terminal locally and in the Streamlit Cloud logs when deployed.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

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
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS "Expenses" (
                "id" SERIAL PRIMARY KEY,
                "expense_date" DATE NOT NULL,
                "vendor" TEXT,
                "category" TEXT,
                "amount" REAL NOT NULL,
                "description" TEXT,
                "created_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))
        # Sync sequences
        conn.execute(text("""
            SELECT setval(pg_get_serial_sequence('public."Expenses"', 'id'), 
                          COALESCE((SELECT MAX("id") FROM "Expenses"), 0) + 1, false);
        """))
        conn.commit()

def save_expense(expense_date, vendor, category, amount, description):
    """Saves a new expense record to the database."""
    engine = get_engine()
    if not engine: return False
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO "Expenses" (expense_date, vendor, category, amount, description)
                VALUES (:date, :vendor, :category, :amount, :desc)
            """), {'date': expense_date, 'vendor': vendor, 'category': category, 'amount': amount, 'desc': description})
            conn.commit()
        return True
    except Exception as e:
        st.error(f"Error saving expense: {e}")
        return False


def extract_expense_from_pdf(file):
    """Extracts total amount and vendor from a PDF receipt, with OCR fallback."""
    extracted_data = {'amount': None, 'vendor': None}
    known_vendors = ["Bunnings", "Woolworths", "Coles", "Officeworks", "AGL", "Telstra", "Optus", "Vodafone", "Amaysim"]
    text = ""
    pdf_bytes = file.getvalue()

    try:
        # --- Method 1: Try text extraction with pdfplumber ---
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        
        logger.info("--- Extracted PDF Text (pdfplumber) ---")

        # --- Method 2: Fallback to OCR if text is minimal/empty ---
        if len(text.strip()) < 20: # Heuristic: if very little text, it's likely an image
            logger.info("Minimal text found. Falling back to OCR.")
            images = convert_from_bytes(pdf_bytes)
            ocr_text = ""
            for img in images:
                ocr_text += pytesseract.image_to_string(img) + "\n"
            text = ocr_text
            logger.info("--- Extracted PDF Text (OCR) ---")

        logger.info(f"--- Final Extracted Text ---\n{text}\n--------------------------")

        # 1. Regex to find 'Total', 'Total Amount', etc., and capture the following number
        match = re.search(r'Total(?: Amount| Price)?[:\s]*\$?([\d,]+\.\d{2})', text, re.IGNORECASE)
        if match:
            extracted_data['amount'] = float(match.group(1).replace(',', ''))

        # 2. Search for a known vendor in the text
        for vendor in known_vendors:
            if re.search(r'\b' + vendor + r'\b', text, re.IGNORECASE):
                extracted_data['vendor'] = vendor
                break
        logger.info(f"Extraction result: {extracted_data}")

    except Exception as e:
        logger.error(f"PDF parsing failed with an exception: {e}", exc_info=True)
        st.error(f"PDF parsing failed: {e}")
    
    return extracted_data

# --- 2. UI & PAGE LOGIC ---

st.set_page_config(page_title="Expense Tracker", layout="wide", page_icon="💳")
st.title("🧾 Expense Logging Console")

# Initialize database tables on first run
init_db_tables()

# --- Expense Tab ---
st.subheader("Scan a Receipt (PDF)")
uploaded_file = st.file_uploader("Upload a receipt PDF to auto-fill the amount", type="pdf")

 # Initialize extracted data
extracted_data = {'amount': 0.0, 'vendor': ""}

if uploaded_file:
    extracted_data = extract_expense_from_pdf(uploaded_file)
    if extracted_data.get('amount'):
        st.info(f"🤖 Amount detected: ${extracted_data['amount']:,.2f}")
    if extracted_data.get('vendor'):
        st.info(f"🤖 Vendor detected: {extracted_data['vendor']}")
    if not extracted_data.get('amount') and not extracted_data.get('vendor'):
        st.warning("Could not automatically detect a vendor or total amount from the PDF. Please enter manually.")

st.subheader("Log an Expense Manually")
with st.form("expense_form"):
    c1, c2, c3 = st.columns(3)
    with c1:
        expense_date = st.date_input("Expense Date", datetime.now())
        vendor = st.text_input("Vendor", value=extracted_data.get('vendor', ''))
    with c2:
        category = st.selectbox("Category", ["Groceries", "Utilities", "Transport", "Dining", "Shopping", "Health", "Other"])
        amount = st.number_input("Amount ($)", value=extracted_data.get('amount', 0.0), min_value=0.0, format="%.2f")
    with c3:
        description = st.text_area("Description (Optional)")

    if st.form_submit_button("➕ Add Expense", use_container_width=True):
        if amount > 0 and vendor:
            if save_expense(expense_date, vendor, category, amount, description):
                st.success(f"Expense from '{vendor}' for ${amount:,.2f} saved!")
                st.rerun()
        else:
            st.warning("Please provide at least a vendor and an amount.")

st.divider()
st.subheader("Recent Expense History")
try:
    df_expenses = pd.read_sql('SELECT expense_date as "Date", vendor as "Vendor", category as "Category", amount as "Amount", description as "Description" FROM "Expenses" ORDER BY expense_date DESC, id DESC LIMIT 20', get_engine())
    st.dataframe(df_expenses.style.format({"Amount": "${:,.2f}"}), use_container_width=True, hide_index=True)
except Exception as e:
    st.info("No expenses logged yet.")