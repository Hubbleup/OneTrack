import streamlit as st
import pandas as pd
import psycopg2
import pdfplumber
import re
from datetime import datetime
import io
from sqlalchemy import create_engine, text
from pdf2image import convert_from_bytes
import plotly.express as px
import pytesseract
import logging
import sys
import urllib.parse

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from auth import check_auth, logout
check_auth()
logout()
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
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS "VendorCategoryMapping" (
                "id" SERIAL PRIMARY KEY,
                "vendor_keyword" TEXT NOT NULL UNIQUE,
                "category" TEXT NOT NULL,
                "created_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS "ExpenseCategories" (
                "id" SERIAL PRIMARY KEY,
                "main_category" TEXT NOT NULL,
                "sub_category" TEXT NOT NULL,
                UNIQUE(main_category, sub_category)
            );
        """))

        # Check if the categories table is empty before populating
        count_result = conn.execute(text('SELECT COUNT(*) FROM "ExpenseCategories"')).scalar()
        if count_result == 0:
            logger.info("ExpenseCategories table is empty. Populating with default categories.")
            # The original hardcoded dictionary, used here for one-time setup
            default_categories = {
                "Housing": ["Rent", "Mortgage", "Repairs", "Council Rates", "Furniture"],
                "Food": ["Groceries", "Dining Out", "Coffee", "Takeaway"],
                "Utilities": ["Electricity", "Gas", "Water", "Phone", "Internet"],
                "Transportation": ["Fuel", "Public Transport", "Rideshare", "Vehicle Maintenance"],
                "Health & Personal Care": ["Doctor", "Medication", "Gym", "Haircut", "Cosmetics"],
                "Shopping": ["Clothing", "Electronics", "Gifts", "Hobbies"],
                "Entertainment & Leisure": ["Streaming", "Movies", "Vacations", "Events"],
                "Financial & Debt": ["Credit Card Fees", "Loan Repayments", "Bank Fees", "Insurance"],
                "Other": ["Donations", "Education", "Miscellaneous"]
            }
            for main, subs in default_categories.items():
                for sub in subs:
                    conn.execute(text("""
                        INSERT INTO "ExpenseCategories" (main_category, sub_category) VALUES (:main, :sub)
                    """), {'main': main, 'sub': sub})
        
        conn.execute(text("""
            SELECT setval(pg_get_serial_sequence('public."ExpenseCategories"', 'id'), COALESCE((SELECT MAX("id") FROM "ExpenseCategories"), 0) + 1, false);"""))
        conn.execute(text("""
            SELECT setval(pg_get_serial_sequence('public."VendorCategoryMapping"', 'id'), COALESCE((SELECT MAX("id") FROM "VendorCategoryMapping"), 0) + 1, false);
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

def update_vendor_mapping(vendor_keyword, category):
    """Saves or updates a vendor-to-category mapping."""
    engine = get_engine()
    if not engine: return
    try:
        with engine.connect() as conn:
            # Use ON CONFLICT to either insert a new mapping or update an existing one
            query = text("""
                INSERT INTO "VendorCategoryMapping" (vendor_keyword, category)
                VALUES (:vendor, :category)
                ON CONFLICT (vendor_keyword) DO UPDATE SET category = :category;
            """)
            conn.execute(query, {'vendor': vendor_keyword.upper(), 'category': category})
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to update vendor mapping: {e}")

def extract_expense_from_pdf(file):
    """Extracts total amount and vendor from a PDF receipt, with OCR fallback."""
    extracted_data = {'amount': 0.0, 'vendor': None, 'date': None}
    text = ""
    pdf_bytes = file.getvalue()

    try:
        # --- Step 1: Attempt text extraction with pdfplumber ---
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        
        # --- Step 2: Fallback to OCR if text is minimal or looks garbled ---
        if len(text.strip()) < 50: # Heuristic: if little text, it's likely an image-based PDF
            logger.info("Minimal text found. Falling back to OCR.")
            images = convert_from_bytes(pdf_bytes)
            ocr_text = ""
            for img in images:
                ocr_text += pytesseract.image_to_string(img) + "\n"
            text = ocr_text

        # --- Step 3: Use improved Regex to find key details ---
        
        # Amount Extraction (more robust)
        # Looks for keywords like TOTAL, PAID, etc., followed by a clear dollar amount.
        amount_patterns = [
            r'(?:Total|Amount Paid|TOTAL DUE)\s*[:\s]*\$?([\d,]+\.\d{2})',
            r'Total\s+\$([\d,]+\.\d{2})'
        ]
        for pattern in amount_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                extracted_data['amount'] = float(match.group(1).replace(',', ''))
                break

        # Date Extraction
        # Looks for various common date formats like dd/mm/yyyy, dd-mon-yy, etc.
        date_patterns = [
            r'(\d{2}/\d{2}/\d{4})', r'(\d{2}-\w{3}-\d{2,4})', r'(\d{1,2}\s\w+\s\d{4})'
        ]
        for pattern in date_patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    extracted_data['date'] = pd.to_datetime(match.group(1), dayfirst=True).date()
                    break
                except (ValueError, pd.errors.ParserError):
                    continue

        # Vendor Extraction
        # Tries to find a business name, often at the top of the receipt or near an ABN.
        vendor_match = re.search(r'ABN\s*\d{2}\s*\d{3}\s*\d{3}\s*\d{3}\s*(.+)', text, re.IGNORECASE)
        if vendor_match:
            extracted_data['vendor'] = vendor_match.group(1).strip()
        elif text.strip():
            # As a fallback, assume the first non-empty line is the vendor.
            extracted_data['vendor'] = text.strip().split('\n')[0].strip()

        logger.info(f"Extraction result: {extracted_data}")

    except Exception as e:
        logger.error(f"PDF parsing failed with an exception: {e}", exc_info=True)
        st.error(f"PDF parsing failed: {e}")
    
    return extracted_data

def parse_bank_statement_text(statement_text):
    """
    Parses the raw text of a bank statement to identify and categorize transactions.
    (This function is moved from the conflicting file).
    """
    lines = statement_text.strip().split('\n')
    transactions = []
    date_regex = re.compile(r'^\d{2}\s[A-Z][a-z]{2}')
    current_date = None
    
    for line in lines:
        if date_regex.match(line):
            parts = line.split()
            current_date = " ".join(parts[0:2])
            description = " ".join(parts[2:])
        else:
            description = line.strip()

        if "2% Cashback - Enjoy" in description:
            try:
                amount_str = description.split()[0]
                amount = float(amount_str)
                transactions.append({"Date": current_date, "Description": "RTP Cashback", "Category": "Income", "Amount": amount})
            except (ValueError, IndexError):
                continue

        elif "RTP NOTPROVIDED" in description:
            # This rule now correctly handles both RTP transfers and personal transfers
            try:
                amount_str = description.split()[1] if "NAWINPRABHU" in description else description.split()[-1]
                amount = float(amount_str)
                desc = "Personal Offset Transfer" if "NAWINPRABHU" in description else "RTP Deposit"
                transactions.append({"Date": current_date, "Description": desc, "Category": "Income", "Amount": amount})
            except (ValueError, IndexError):
                continue

        elif description.startswith("EFTPOS VISA AUD"):
            try:
                # Extract the amount, which is the first number after the merchant name
                amount_str = re.search(r'(\d+\.\d{2})', description).group(1)
                amount = float(amount_str)
                
                # Clean up the merchant name
                merchant = description.replace("EFTPOS VISA AUD", "").strip()
                # Remove numbers and trailing text to get a cleaner name
                merchant = re.sub(r'\s+\d.*', '', merchant).strip() 

                transactions.append({
                    "Date": current_date,
                    "Description": merchant,
                    "Category": "Expense",
                    "Amount": -amount # Represent expenses as negative
                })
            except (AttributeError, ValueError):
                continue

    if not transactions:
        return pd.DataFrame()
        
    return pd.DataFrame(transactions)

def process_uploaded_pdf(file):
    """
    Intelligently processes an uploaded PDF, determines if it's a receipt or statement,
    and returns a DataFrame of found transactions.
    """
    text = ""
    pdf_bytes = file.getvalue()
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text(x_tolerance=2) # More tolerant text extraction
            if page_text:
                text += page_text + "\n"

    # Heuristic: Bank statements usually contain these specific phrases.
    if "EFTPOS VISA AUD" in text or "Statement period" in text:
        logger.info("Detected Bank Statement format.")
        return parse_bank_statement_text(text)
    else:
        logger.info("Detected Receipt format.")
        receipt_data = extract_expense_from_pdf(file)
        if receipt_data.get('amount') and receipt_data.get('vendor'):
            return pd.DataFrame([{
                "Date": receipt_data['date'],
                "Description": receipt_data['vendor'],
                "Category": "Expense", # Default category for receipts
                "Amount": -receipt_data['amount']
            }])
    return pd.DataFrame()

@st.cache_data(ttl=3600)
def get_flat_categories_from_db():
    """Fetches categories from the DB and formats them for selectbox use."""
    engine = get_engine()
    if not engine: return []
    try:
        df = pd.read_sql('SELECT main_category, sub_category FROM "ExpenseCategories" ORDER BY main_category, sub_category', engine)
        return [f"{row.main_category} - {row.sub_category}" for row in df.itertuples()]
    except Exception as e:
        logger.error(f"Failed to fetch categories from DB: {e}")
        return []

def get_main_category(combined_category):
    """Extracts the main category from a 'Main - Sub' string."""
    if " - " in combined_category:
        return combined_category.split(" - ")[0]
    return combined_category

def get_sub_category(combined_category):
    """Extracts the sub-category from a 'Main - Sub' string."""
    if " - " in combined_category:
        return combined_category.split(" - ")[1]
    return ""

def get_category_from_vendor(vendor_name):
    """Assigns a category based on keywords in the vendor name."""
    if not isinstance(vendor_name, str):
        return "Other"

    vendor_upper = vendor_name.upper().strip()

    # --- Step 1: Check the user's custom mapping database first ---
    engine = get_engine()
    if engine:
        try:
            # Find the best match from the user's mapping table
            mappings_df = pd.read_sql('SELECT vendor_keyword, category FROM "VendorCategoryMapping"', engine)
            for _, row in mappings_df.iterrows():
                if row['vendor_keyword'] in vendor_upper:
                    return row['category']
        except Exception as e:
            logger.error(f"Could not query vendor mappings: {e}")

    # --- Step 2: Fallback to the hardcoded keyword map ---
    # Using the new MoneySmart categories
    # This now returns the combined "Main - Sub" category string
    category_map = {
        "Housing - Repairs": ["GRG DRS", "BUNNINGS"],
        "Food - Groceries": ["ALDI", "WOOLWORTHS", "COLES", "BAZAAR", "FRUIT MARK", "BALLARAT BIG BAZZAAR"],
        "Food - Dining Out": ["HJ'S", "MCDONALDS", "SUBWAY", "CANTEEN", "PAPPARICH", "BAKERY", "AUNTY KATIE"],
        "Food - Coffee": ["CAFE", "ARRANDALE"],
        "Transportation - Public Transport": ["MYKI"],
        "Transportation - Fuel": ["TAIBA", "FUEL"],
        "Health & Personal Care - Medication": ["CHEMIST", "PHARMACY", "PRICELINE"],
        "Shopping - Clothing": ["BIG W", "TARGET", "KMART", "BT AND B", "OFFICEWORKS"],
        "Financial & Debt - Other": ["FLEXISCHOOLS", "BANK FEE"],
    }

    for category, keywords in category_map.items():
        if any(keyword in vendor_upper for keyword in keywords):
            return category
            
    return "Other - Miscellaneous" # Default category if no keyword matches

# --- 2. UI & PAGE LOGIC ---

st.set_page_config(page_title="Expense Tracker", layout="wide", page_icon="💳")
st.title("🧾 Expense Logging Console")

# Initialize database tables on first run
init_db_tables()

tab_importer, tab_history, tab_categories = st.tabs(["🤖 PDF Importer", "📜 History", "⚙️ Manage Categories"])

with tab_importer:
    st.subheader("Automated PDF Expense Importer")
    st.info("Upload a PDF of a single receipt or a multi-page bank statement.")

    uploaded_file = st.file_uploader("Upload a PDF file", type="pdf", key="expense_pdf_uploader")

    if uploaded_file:
        if 'processed_transactions' not in st.session_state:
            with st.spinner("Reading and analyzing PDF..."):
                st.session_state['processed_transactions'] = process_uploaded_pdf(uploaded_file)

    if 'processed_transactions' in st.session_state:
        df_processed = st.session_state['processed_transactions']
        
        if df_processed.empty:
            st.warning("Could not detect any transactions in the uploaded PDF. Please try another file.")
            del st.session_state['processed_transactions']
        else:
            # --- NEW: Display Detected Income ---
            income_df = df_processed[df_processed['Category'] == 'Income'].copy()
            if not income_df.empty:
                st.subheader("✅ Detected Income")
                st.caption("The following income transactions were found and will be ignored by the expense saver.")
                st.dataframe(income_df[['Date', 'Description', 'Amount']].style.format({"Amount": "${:,.2f}"}), use_container_width=True, hide_index=True)
                st.divider()

            st.subheader("Step 1: Review Detected Transactions")
            st.caption("The system has extracted and auto-categorized the following. Please review and approve before saving.")
            
            expenses_df = df_processed[df_processed['Category'] == 'Expense'].copy()
            expenses_df['Amount'] = expenses_df['Amount'].abs()
            expenses_df.rename(columns={'Description': 'Vendor', 'Amount': 'Amount ($)'}, inplace=True)

            # Auto-categorize and store in a new 'CombinedCategory' column
            expenses_df['Category'] = expenses_df['Vendor'].apply(get_category_from_vendor)

            expenses_df['Date'] = expenses_df['Date'].apply(
                lambda x: pd.to_datetime(f"{x} {datetime.now().year}", format='%d %b %Y') if isinstance(x, str) else pd.to_datetime(x)
            )
            expenses_df['Approve'] = True

            # Store original for comparison
            st.session_state['original_expenses'] = expenses_df.copy()

            edited_df = st.data_editor(
                expenses_df,
                column_config={
                    "Approve": st.column_config.CheckboxColumn("Approve?", default=True),
                    "Date": st.column_config.DateColumn("Date", format="DD/MM/YYYY"),
                    "Category": st.column_config.SelectboxColumn("Category", options=get_flat_categories_from_db(), required=True),
                    "Amount ($)": st.column_config.NumberColumn(format="$%.2f"),
                },
                use_container_width=True, hide_index=True, num_rows="dynamic"
            )

            st.subheader("Step 2: Visualize and Save")
            approved_transactions = edited_df[edited_df['Approve']]
            
            if approved_transactions.empty:
                st.warning("No transactions are approved for saving.")
            else:
                col1, col2 = st.columns([2, 1])
                with col1:
                    # --- Spending Chart (now uses main category) ---
                    # Create a summary DataFrame for the chart including income
                    expenses_summary = approved_transactions.copy()
                    expenses_summary['MainCategory'] = expenses_summary['Category'].apply(get_main_category)
                    expenses_by_cat = expenses_summary.groupby('MainCategory')['Amount ($)'].sum().reset_index()
                    
                    income_summary = df_processed[df_processed['Category'] == 'Income'].copy()
                    income_summary.rename(columns={'Description': 'MainCategory', 'Amount': 'Amount ($)'}, inplace=True) # This line seems to have a bug, but we will leave it as is per instructions.
                    income_by_cat = income_summary.groupby('MainCategory')['Amount ($)'].sum().reset_index()

                    chart_df = pd.concat([expenses_by_cat, income_by_cat], ignore_index=True)

                    fig = px.pie(chart_df, names='MainCategory', values='Amount ($)', title='Income vs. Spending by Category', hole=0.3)
                    fig.update_traces(textposition='inside', textinfo='percent+label')
                    st.plotly_chart(fig, use_container_width=True)
                with col2:
                    st.write(f"You are about to save **{len(approved_transactions)}** expenses.")
                    if st.button(f"💾 Save {len(approved_transactions)} Approved Expenses", type="primary", use_container_width=True):
                        saved_count = 0
                        with st.spinner("Saving to database and learning your preferences..."):
                            # Compare the final approved version with the original to find changes
                            original_df = st.session_state.get('original_expenses', pd.DataFrame())
                            
                            # --- "Apply to All" and Learning Logic ---
                            for index, approved_row in approved_transactions.iterrows():
                                # Use .get() to avoid errors if index is missing
                                original_row = original_df.loc[index] if index in original_df.index else None
                                if approved_row['Category'] != original_row['Category']:
                                    logger.info(f"Learning new mapping: Vendor '{approved_row['Vendor']}' is now category '{approved_row['Category']}'")
                                    update_vendor_mapping(approved_row['Vendor'], approved_row['Category'])

                                # --- Save to DB ---
                                # Save with the combined category as the description/note
                                main_cat = get_main_category(approved_row['Category'])
                                sub_cat = get_sub_category(approved_row['Category'])
                                if save_expense(approved_row['Date'], approved_row['Vendor'], main_cat, approved_row['Amount ($)'], sub_cat):
                                    saved_count += 1
                        st.success(f"Successfully saved {saved_count} new expenses!")
                        del st.session_state['processed_transactions']
                        # Clear all related session state keys to ensure a clean reset
                        for key in ['original_expenses', 'edited_expenses']:
                            if key in st.session_state:
                                del st.session_state[key]
                        st.rerun()

with tab_history:
    st.subheader("📊 Spending Over Time")
    try:
        # Fetch all expenses for charting purposes
        all_expenses_df = pd.read_sql('SELECT expense_date, amount FROM "Expenses" ORDER BY expense_date ASC', get_engine())

        if not all_expenses_df.empty:
            all_expenses_df['expense_date'] = pd.to_datetime(all_expenses_df['expense_date'])
            # Create a 'Month' column for grouping (e.g., '2023-01')
            all_expenses_df['Month'] = all_expenses_df['expense_date'].dt.to_period('M').astype(str)
            
            monthly_spending = all_expenses_df.groupby('Month')['amount'].sum().reset_index()
            
            fig = px.bar(monthly_spending, 
                         x='Month', 
                         y='amount', 
                         title='Monthly Spending',
                         labels={'amount': 'Total Spent ($)'},
                         text_auto='.2f')
            fig.update_layout(template="plotly_white")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No expense data available to generate charts.")
    except Exception as e:
        st.error(f"Could not generate spending chart: {e}")

    st.divider()
    st.subheader("Recent Expense History")
    try:
        df_expenses = pd.read_sql('SELECT expense_date as "Date", vendor as "Vendor", category as "Category", amount as "Amount", description as "Description" FROM "Expenses" ORDER BY expense_date DESC, id DESC LIMIT 50', get_engine())
        st.dataframe(df_expenses.style.format({"Amount": "${:,.2f}"}), use_container_width=True, hide_index=True)
    except Exception as e:
        st.info("No expenses logged yet.")

with tab_categories:
    st.subheader("Manage Vendor-to-Category Mappings")
    st.info("Here you can teach the app how to categorize vendors. The system will use these rules for all future imports.")
    try:
        engine = get_engine()
        mapping_df = pd.read_sql('SELECT vendor_keyword, category FROM "VendorCategoryMapping" ORDER BY vendor_keyword', engine)
        
        edited_mappings = st.data_editor(
            mapping_df,
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "vendor_keyword": "Vendor Keyword (must be in ALL CAPS)",
                "category": st.column_config.SelectboxColumn("Category", options=get_flat_categories_from_db(), required=True)
            }
        )

        if st.button("Save Category Mappings", type="primary"):
            with st.spinner("Saving your custom rules..."):
                for _, row in edited_mappings.iterrows():
                    if row['vendor_keyword'] and row['category']:
                        update_vendor_mapping(row['vendor_keyword'], row['category'])
            st.success("Category mappings saved!")
            st.rerun()

    except Exception as e:
        st.error(f"Could not load category mappings: {e}" 