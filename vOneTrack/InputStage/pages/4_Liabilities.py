import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
from datetime import datetime
import urllib.parse
import plotly.graph_objects as go

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

def init_liabilities_table():
    """Initializes the Liabilities table if it doesn't exist."""
    engine = get_engine()
    if not engine: return

    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS "Liabilities" (
                "id" SERIAL PRIMARY KEY,
                "name" TEXT NOT NULL UNIQUE,
                "type" TEXT NOT NULL,
                "sub_type" TEXT,
                "balance" REAL NOT NULL,
                "offset_balance" REAL DEFAULT 0,                  -- Balance in the linked offset account
                "redraw_balance" REAL DEFAULT 0,                  -- Available redraw amount
                "interest_rate" REAL,
                "rate_type" TEXT,
                "loan_term_months" INTEGER,                       -- Original term in total months
                "loan_start_date" DATE,
                "next_repayment_date" DATE,                       -- The next upcoming payment date
                "repayment_amount" REAL,                          -- Regular repayment amount
                "extra_repayment" REAL DEFAULT 0,                 -- Ongoing extra repayment amount
                "repayment_frequency" TEXT,
                "last_updated" DATE NOT NULL,
                "created_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS "PropertyTransactions" (
                "id" SERIAL PRIMARY KEY,
                "liability_id" INTEGER NOT NULL,
                "transaction_date" DATE NOT NULL,
                "transaction_type" TEXT NOT NULL, -- 'Income' or 'Expense'
                "category" TEXT,
                "description" TEXT,
                "frequency" TEXT DEFAULT 'One-off',               -- e.g., One-off, Monthly, Quarterly, Yearly
                "amount" REAL NOT NULL,
                "created_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY ("liability_id") REFERENCES "Liabilities"("id") ON DELETE CASCADE
            );
        """))
        conn.execute(text("""
            SELECT setval(pg_get_serial_sequence('public."Liabilities"', 'id'), 
                          COALESCE((SELECT MAX("id") FROM "Liabilities"), 0) + 1, false);
        """))
        # --- Add new columns for Gearing Calculation (if they don't exist) ---
        try:
            conn.execute(text('ALTER TABLE "Liabilities" ADD COLUMN "annual_depreciation" REAL DEFAULT 0;'))
        except Exception: # Column likely already exists
            conn.rollback() # Rollback the failed transaction
        try:
            conn.execute(text('ALTER TABLE "Liabilities" ADD COLUMN "marginal_tax_rate" REAL DEFAULT 0;'))
        except Exception: # Column likely already exists
            conn.rollback()
        else:
            conn.commit() # Commit if successful

        conn.commit()

def save_liability(details):
    """Saves a new liability or updates an existing one by name."""
    engine = get_engine()
    if not engine: return False
    try:
        with engine.connect() as conn:
            res = conn.execute(text('SELECT id FROM "Liabilities" WHERE name = :name'), {'name': details['name']}).fetchone()
            if res: # Update
                update_query = text("""
                    UPDATE "Liabilities" SET 
                        type=:type, sub_type=:sub_type, balance=:balance, interest_rate=:interest_rate,
                        rate_type=:rate_type, loan_term_months=:loan_term_months, loan_start_date=:loan_start_date, 
                        next_repayment_date=:next_repayment_date, offset_balance=:offset_balance, redraw_balance=:redraw_balance,
                        repayment_amount=:repayment_amount, extra_repayment=:extra_repayment, repayment_frequency=:repayment_frequency,
                        annual_depreciation=:annual_depreciation, marginal_tax_rate=:marginal_tax_rate,
                        last_updated=:last_updated
                    WHERE id = :id
                """)
                details['id'] = res[0]
                conn.execute(update_query, details)
            else: # Insert
                insert_query = text("""
                    INSERT INTO "Liabilities" (name, type, sub_type, balance, offset_balance, redraw_balance, interest_rate, rate_type, loan_term_months, 
                        loan_start_date, next_repayment_date, repayment_amount, extra_repayment, repayment_frequency, annual_depreciation, marginal_tax_rate, last_updated)
                    VALUES (:name, :type, :sub_type, :balance, :offset_balance, :redraw_balance, :interest_rate, :rate_type, :loan_term_months, 
                        :loan_start_date, :next_repayment_date, :repayment_amount, :extra_repayment, :repayment_frequency, :annual_depreciation, :marginal_tax_rate, :last_updated)
                """)
                conn.execute(insert_query, details)
            conn.commit()
        return True
    except Exception as e:
        st.error(f"Error saving liability: {e}")
        return False

def update_liability_value(name, new_value, column_to_update):
    """Updates a specific column for an existing liability."""
    engine = get_engine()
    if not engine: return False
    try:
        with engine.connect() as conn:
            # Using text() to prevent SQL injection with dynamic column names, but ensure column_to_update is from a safe list.
            safe_columns = ["interest_rate", "balance", "offset_balance", "redraw_balance"]
            if column_to_update not in safe_columns:
                st.error("Invalid column for update.")
                return False

            # Use f-string for the column name and parameterized query for values
            query = text(f'UPDATE "Liabilities" SET "{column_to_update}" = :value, last_updated = :date WHERE name = :name')
            conn.execute(query, {'value': new_value, 'name': name, 'date': datetime.now().date()})
            conn.commit()
        return True
    except Exception as e:
        st.error(f"Error updating liability: {e}")
        return False

def save_property_transaction(details):
    """Saves an income or expense record linked to a liability."""
    engine = get_engine()
    if not engine: return False
    try:
        with engine.connect() as conn:
            query = text("""
                INSERT INTO "PropertyTransactions" (liability_id, transaction_date, transaction_type, category, description, amount, frequency)
                VALUES (:liability_id, :transaction_date, :transaction_type, :category, :description, :amount, :frequency)
            """)
            conn.execute(query, details)
            conn.commit()
        return True
    except Exception as e:
        st.error(f"Error saving transaction: {e}")
        return False

def calculate_amortization(principal, annual_rate, term_months, frequency, regular_payment, extra_payment=0, offset_balance=0):
    """Calculates loan amortization schedule."""
    if frequency == 'Monthly':
        periods_per_year = 12
        total_periods = term_months
    else: # Fortnightly
        periods_per_year = 26
        # Approximate fortnightly periods from total months
        total_periods = int(term_months * (26 / 12))

    rate_per_period = (annual_rate / 100) / periods_per_year
    # Directly use the provided regular_payment and extra_payment.
    # This makes the function's purpose clearer, as it simulates a scenario
    # based on known payment amounts rather than recalculating them.
    total_payment_per_period = (regular_payment or 0) + (extra_payment or 0)

    schedule = []
    # The core of the offset calculation: reduce the principal for interest calculation
    remaining_balance = principal - offset_balance
    period = 0
    # Safety break: max 50 years of periods
    while remaining_balance > 0 and period < (50 * periods_per_year):
        period += 1
        interest_paid = remaining_balance * rate_per_period
        
        # Ensure payment doesn't exceed what's owed
        payment_this_period = min(total_payment_per_period, remaining_balance + interest_paid)
        
        principal_paid = payment_this_period - interest_paid
        remaining_balance -= principal_paid
        
        # Final adjustment to prevent negative balance due to floating point math
        if remaining_balance < 0:
            principal_paid += remaining_balance # Add the negative remainder
            remaining_balance = 0

        schedule.append({
            'Period': period,
            'Principal Paid': principal_paid,
            'Interest Paid': interest_paid,
            'Remaining Balance': remaining_balance
        })
    return pd.DataFrame(schedule)

def annualize_transactions(df):
    """Calculates the annualized amount for each transaction based on its frequency."""
    frequency_multipliers = {
        'Weekly': 52,
        'Fortnightly': 26,
        'Monthly': 12,
        'Quarterly': 4,
        'Yearly': 1,
        'One-off': 1
    }

    def get_annual_amount(row):
        # Only annualize if it's not a one-off transaction within a specific date range (future enhancement)
        # For now, we annualize all recurring costs for a forward-looking P&L.
        return row['amount'] * frequency_multipliers.get(row['frequency'], 1)

    df['annualized_amount'] = df.apply(get_annual_amount, axis=1)
    return df

def get_property_cashflow_summary(df_liabilities):
    """Calculates cash flow for all investment properties."""
    engine = get_engine()
    if not engine: return pd.DataFrame()

    ip_df = df_liabilities[df_liabilities['sub_type'] == 'IP'].copy()
    if ip_df.empty:
        return pd.DataFrame()

    cashflow_data = []
    for _, prop in ip_df.iterrows():
        try:
            transactions_df = pd.read_sql('SELECT * FROM "PropertyTransactions" WHERE liability_id = %(lid)s', engine, params={'lid': int(prop['id'])})
            
            if not transactions_df.empty:
                transactions_df = annualize_transactions(transactions_df)
                annual_income = transactions_df[transactions_df['transaction_type'] == 'Income']['annualized_amount'].sum()
                annual_op_expenses = transactions_df[transactions_df['transaction_type'] == 'Expense']['annualized_amount'].sum()
            else:
                annual_income = 0
                annual_op_expenses = 0

            annual_interest = (prop['balance'] - prop['offset_balance']) * (prop['interest_rate'] / 100)
            total_expenses = annual_op_expenses + annual_interest
            net_cashflow = annual_income - total_expenses
            cashflow_data.append({'Property': prop['name'], 'Annual Income': annual_income, 'Annual Expenses': total_expenses, 'Net Cash Flow': net_cashflow})
        except Exception:
            continue # Skip property if there's an error
    
    return pd.DataFrame(cashflow_data)
# --- 2. UI & PAGE LOGIC ---

st.set_page_config(page_title="Liability Tracker", layout="wide", page_icon="🏦")
st.title("🏦 Liability & Loan Console")

init_liabilities_table()

# Fetch data once at the top for all tabs to use
try:
    df_liabilities = pd.read_sql('SELECT * FROM "Liabilities" ORDER BY name', get_engine())
except Exception:
    df_liabilities = pd.DataFrame() # Initialize empty dataframe on error

tab_dashboard, tab_manage, tab_cashflow = st.tabs(["📊 Dashboard", "📝 Manage Loans", "💸 Property Cash Flow"])

with tab_dashboard:
    st.subheader("Current Liability Overview")
    if not df_liabilities.empty:
        # Calculate Next Repayment Date
        def get_next_repayment(row):
            """Calculates the next upcoming repayment date from today."""
            today = pd.to_datetime(datetime.now().date())
            # Use the user-provided next_repayment_date as the true anchor
            anchor_date = pd.to_datetime(row['next_repayment_date'])

            if pd.isna(anchor_date) or not row['repayment_frequency']:
                return None

            # If the anchor date is in the future, that's the next payment.
            if anchor_date >= today:
                return anchor_date

            if row['repayment_frequency'] == 'Monthly':
                # Find the next month's payment date that is after today
                next_date = anchor_date
                while next_date <= today:
                    next_date += pd.DateOffset(months=1)
                return next_date
            elif row['repayment_frequency'] == 'Fortnightly':
                days_since = (today - anchor_date).days
                periods_passed = days_since // 14
                return anchor_date + pd.DateOffset(days=(periods_passed + 1) * 14)
            
            return None # Should not be reached if frequency is valid
        df_liabilities['Next Repayment'] = df_liabilities.apply(get_next_repayment, axis=1)

        st.dataframe(
            df_liabilities, 
            column_config={
                "balance": st.column_config.NumberColumn("Balance", format="$%.2f"),
                "offset_balance": st.column_config.NumberColumn("Offset Balance", format="$%.2f"),
                "redraw_balance": st.column_config.NumberColumn("Redraw", format="$%.2f"),
                "interest_rate": st.column_config.NumberColumn("Rate %", format="%.2f%%"),
                "repayment_amount": st.column_config.NumberColumn("Repayment", format="$%.2f"),
                "extra_repayment": st.column_config.NumberColumn("Extra Repayment", format="$%.2f"),
            },
            use_container_width=True, hide_index=True
        )

        # --- Investment Property Cash Flow Summary ---
        st.divider()
        st.subheader("🏡 Investment Property Cash Flow Summary (Annualized)")
        cashflow_summary_df = get_property_cashflow_summary(df_liabilities)

        if not cashflow_summary_df.empty:
            st.dataframe(
                cashflow_summary_df.style.format({
                    'Annual Income': '${:,.2f}', 'Annual Expenses': '${:,.2f}', 'Net Cash Flow': '${:,.2f}'
                }).map(lambda x: 'color: red' if x < 0 else 'color: green', subset=['Net Cash Flow']),
                use_container_width=True, hide_index=True
            )
            total_net_cashflow = cashflow_summary_df['Net Cash Flow'].sum()
            st.metric("Total Portfolio Net Cash Flow (Pre-Tax)", f"${total_net_cashflow:,.2f}", delta=f"{total_net_cashflow:,.2f}")
        else:
            st.info("No Investment Properties with cash flow data found. Add transactions in the 'Property Cash Flow' tab.")
    else:
        st.info("No liabilities logged yet.")

    # --- AMORTIZATION & PREDICTION LOGIC ---
    if not df_liabilities.empty:
        st.divider()
        st.subheader("🔮 Loan Payoff Prediction")

        required_cols = ['name', 'balance', 'offset_balance', 'interest_rate', 'loan_term_months', 'repayment_frequency', 'repayment_amount', 'extra_repayment']
        predictable_loans = df_liabilities.dropna(subset=required_cols)

        if not predictable_loans.empty:
            selected_loan_name = st.selectbox("Select a Loan to Analyze", options=predictable_loans['name'].unique())
            
            if selected_loan_name:
                loan_data = predictable_loans[predictable_loans['name'] == selected_loan_name].iloc[0]
                
                simulation_extra_repayment = st.number_input("Simulate Extra Repayment per Period ($)", min_value=0.0, value=float(loan_data['extra_repayment']), step=50.0, key=f"extra_{selected_loan_name}")

                original_schedule = calculate_amortization(loan_data['balance'], loan_data['interest_rate'], loan_data['loan_term_months'], loan_data['repayment_frequency'], loan_data['repayment_amount'], loan_data['extra_repayment'], loan_data['offset_balance'])
                accelerated_schedule = calculate_amortization(loan_data['balance'], loan_data['interest_rate'], loan_data['loan_term_months'], loan_data['repayment_frequency'], loan_data['repayment_amount'], simulation_extra_repayment, loan_data['offset_balance'])
                
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=original_schedule['Period'], y=original_schedule['Remaining Balance'], mode='lines', name='Standard Repayment'))
                fig.add_trace(go.Scatter(x=accelerated_schedule['Period'], y=accelerated_schedule['Remaining Balance'], mode='lines', name=f'With +${simulation_extra_repayment} Extra'))
                
                fig.update_layout(title=f"Loan Payoff Journey for {selected_loan_name}", xaxis_title="Repayment Periods", yaxis_title="Remaining Balance ($)", template="plotly_white")
                st.plotly_chart(fig, use_container_width=True)

                st.metric(label="Original Payoff Time", value=f"{len(original_schedule)} periods")
                st.metric(label="Accelerated Payoff Time", value=f"{len(accelerated_schedule)} periods", delta=f"{len(original_schedule) - len(accelerated_schedule)} periods saved")
        else:
            st.info("No loans with complete data available for prediction.")

with tab_manage:
    st.subheader("Log or Update a Liability")

    # --- Pre-fill form from existing liability ---
    if not df_liabilities.empty:
        # Add a blank option to allow creating a new entry
        liability_options = [""] + df_liabilities['name'].tolist()
        selected_to_edit = st.selectbox("Select an existing liability to edit (optional)", options=liability_options, index=0)

        if selected_to_edit:
            # If a liability is selected, store its data in session state to pre-fill the form
            st.session_state.edit_liability_data = df_liabilities[df_liabilities['name'] == selected_to_edit].iloc[0].to_dict()
        elif 'edit_liability_data' in st.session_state and not selected_to_edit:
             # Clear if user goes back to "new"
            del st.session_state.edit_liability_data

    # Get pre-filled data or set defaults
    prefill = st.session_state.get('edit_liability_data', {})

    with st.form("liability_form", clear_on_submit=True):
        st.info("To create a new liability, leave the dropdown above blank. To update, select a liability to pre-fill the form.")
        
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("##### Core Details")
            name = st.text_input("Liability Name", value=prefill.get('name', ''), placeholder="e.g., Home Mortgage")
            type_options = ["Mortgage", "Car Loan", "Personal Loan", "Credit Card", "Other"]
            l_type = st.selectbox("Type", type_options, index=type_options.index(prefill['type']) if 'type' in prefill else 0)
            sub_type_options = ["", "PPOR", "IP"]
            sub_type = st.selectbox("Sub-Type (for Mortgage)", sub_type_options, index=sub_type_options.index(prefill['sub_type']) if 'sub_type' in prefill else 0, help="Principal Place of Residence or Investment Property")
        with c2:
            st.markdown("##### Financials")
            balance = st.number_input("Current Balance ($)", min_value=0.0, format="%.2f")
            interest_rate = st.number_input("Interest Rate (%)", min_value=0.0, max_value=100.0, format="%.2f")
            rate_type = st.selectbox("Interest Type", ["Variable", "Fixed"])
            offset_balance = 0.0
            redraw_balance = 0.0
            offset_balance = st.number_input("Offset Account Balance ($)", value=prefill.get('offset_balance', 0.0), min_value=0.0, format="%.2f")
            redraw_balance = st.number_input("Redraw Available ($)", value=prefill.get('redraw_balance', 0.0), min_value=0.0, format="%.2f")
            
            annual_depreciation = 0.0
            marginal_tax_rate = 0.0
            if sub_type == 'IP':
                st.markdown("##### Gearing Inputs")
        with c3:
            st.markdown("##### Repayments & Dates")
            repayment_amount = st.number_input("Repayment Amount ($)", value=prefill.get('repayment_amount', 0.0), min_value=0.0, format="%.2f")
            freq_options = ["Fortnightly", "Monthly"]
            repayment_frequency = st.selectbox("Repayment Frequency", freq_options, index=freq_options.index(prefill['repayment_frequency']) if 'repayment_frequency' in prefill else 0)
            extra_repayment = st.number_input("Ongoing Extra Repayment ($)", value=prefill.get('extra_repayment', 0.0), min_value=0.0, format="%.2f", help="A recurring extra amount to pay each period.")
            
            # Handle date pre-filling carefully
            next_repayment_date = pd.to_datetime(prefill.get('next_repayment_date')).date() if 'next_repayment_date' in prefill and pd.notna(prefill.get('next_repayment_date')) else datetime.now().date()
            loan_start_date = pd.to_datetime(prefill.get('loan_start_date')).date() if 'loan_start_date' in prefill and pd.notna(prefill.get('loan_start_date')) else datetime.now().date()
            
            st.date_input("Next Repayment Date", value=next_repayment_date)
            st.date_input("Loan Start Date", value=loan_start_date)
            updated_date = st.date_input("Balance as of", datetime.now()) # Always default to today for updates
            if sub_type == 'IP':
                annual_depreciation = st.number_input("Annual Depreciation Claim ($)", value=prefill.get('annual_depreciation', 0.0), min_value=0.0, format="%.2f", help="From a quantity surveyor's report.")
                marginal_tax_rate = st.number_input("Owner's Marginal Tax Rate (%)", value=prefill.get('marginal_tax_rate', 0.0), min_value=0.0, max_value=100.0, format="%.1f", help="Your personal income tax rate.")

        st.markdown("###### Original Loan Term")
        t_col1, t_col2, t_col3 = st.columns([2,2,8])
        with t_col1:
            loan_years = st.number_input("Years", min_value=0, max_value=50, value=30)
        with t_col2:
            loan_months = st.number_input("Months", min_value=0, max_value=11, value=0)

        if st.form_submit_button("💾 Save Liability", use_container_width=True, type="primary"):
            if name and balance > 0:
                liability_details = {
                    "name": name, "type": l_type, "sub_type": sub_type, "balance": balance, "offset_balance": offset_balance, "redraw_balance": redraw_balance,
                    "interest_rate": interest_rate, "rate_type": rate_type, "loan_term_months": (loan_years * 12) + loan_months,
                    "loan_start_date": loan_start_date, "next_repayment_date": next_repayment_date, "repayment_amount": repayment_amount, "extra_repayment": extra_repayment,
                    "repayment_frequency": repayment_frequency, "annual_depreciation": annual_depreciation, "marginal_tax_rate": marginal_tax_rate,
                    "last_updated": updated_date
                }
                if save_liability(liability_details):
                    st.success(f"Liability '{name}' saved successfully!")
                    st.rerun()
            else:
                st.warning("Please provide a name and balance.")

    # --- Quick Actions for Existing Liabilities ---
    if not df_liabilities.empty:
        with st.expander("⚡ Quick Actions & Updates"):
            q_col1, q_col2, q_col3 = st.columns(3)
            with q_col1:
                with st.form("update_rate_form"):
                    st.markdown("###### Update Interest Rate")
                    selected_loan_rate = st.selectbox("Select Loan", options=df_liabilities['name'], key="rate_loan")
                    new_rate = st.number_input("New Interest Rate (%)", min_value=0.0, format="%.2f")
                    if st.form_submit_button("Update Rate", use_container_width=True):
                        if update_liability_value(selected_loan_rate, new_rate, "interest_rate"):
                            st.success(f"Interest rate for '{selected_loan_rate}' updated to {new_rate}%.")
                            st.rerun()
            with q_col2:
                with st.form("one_off_payment_form"):
                    st.markdown("###### Log One-Off Extra Payment")
                    selected_loan_payment = st.selectbox("Select Loan", options=df_liabilities['name'], key="payment_loan")
                    one_off_amount = st.number_input("One-Off Payment Amount ($)", min_value=0.0, format="%.2f")
                    if st.form_submit_button("Apply Payment", use_container_width=True):
                        current_balance = pd.read_sql('SELECT balance FROM "Liabilities" WHERE name = %(name)s', get_engine(), params={'name': selected_loan_payment}).iloc[0,0]
                        new_balance = current_balance - one_off_amount
                        if update_liability_value(selected_loan_payment, new_balance, "balance"):
                            st.success(f"One-off payment of ${one_off_amount:,.2f} applied to '{selected_loan_payment}'.")
                            st.rerun()
            with q_col3:
                mortgage_loans = df_liabilities[df_liabilities['type'] == 'Mortgage']
                if not mortgage_loans.empty:
                    with st.form("update_offset_form"):
                        st.markdown("###### Update Offset Balance")
                        selected_loan_offset = st.selectbox("Select Mortgage", options=mortgage_loans['name'], key="offset_loan")
                        new_offset_balance = st.number_input("New Offset Balance ($)", min_value=0.0, format="%.2f")
                        if st.form_submit_button("Update Offset", use_container_width=True):
                            if update_liability_value(selected_loan_offset, new_offset_balance, "offset_balance"):
                                st.success(f"Offset balance for '{selected_loan_offset}' updated.")
                                st.rerun()

with tab_cashflow:
    st.subheader("🏡 Property Cash Flow")
    if not df_liabilities.empty:
        mortgage_df = df_liabilities[df_liabilities['type'] == 'Mortgage']
        if not mortgage_df.empty:
            selected_property_name = st.selectbox("Select a Property to Manage", options=mortgage_df['name'].unique())
            
            if selected_property_name:
                property_data = mortgage_df[mortgage_df['name'] == selected_property_name].iloc[0]
                liability_id = property_data['id']

                # --- Add Transaction Form ---
                with st.expander("➕ Add Income or Expense for this Property"):
                    # This widget must be OUTSIDE the form to trigger an immediate rerun on change.
                    # We use the liability_id in the key to keep it unique per property.
                    trans_type = st.selectbox("Transaction Type", ["Income", "Expense"], key=f"trans_type_{liability_id}")

                    with st.form("property_transaction_form", clear_on_submit=True):
                        t_c1, t_c2, t_c3, t_c4 = st.columns(4)
                        with t_c1:
                            trans_date = st.date_input("Date", datetime.now())
                            trans_amount = st.number_input("Amount ($)", min_value=0.01, format="%.2f", key=f"amount_{liability_id}")
                        with t_c2:
                            # This logic now correctly re-evaluates when trans_type changes.
                            if trans_type == "Income":
                                category_options = ["Rent"]
                            else:
                                category_options = ["Council Rates", "Water Bill", "Land Tax", "Management Fee", "Repairs", "Insurance", "Body Corporate", "Other"]
                            trans_cat = st.selectbox("Category", category_options)
                            trans_freq = st.selectbox("Frequency", ["One-off", "Weekly", "Fortnightly", "Monthly", "Quarterly", "Yearly"])
                        with t_c3:
                            trans_desc = st.text_area("Description (Optional)")
                        with t_c4:
                            pass # Spacer column
                        
                        if st.form_submit_button(f"Log {trans_type}", use_container_width=True):
                            trans_details = {
                                "liability_id": int(liability_id), "transaction_date": trans_date, "transaction_type": trans_type, "frequency": trans_freq,
                                "category": trans_cat, "description": trans_desc, "amount": trans_amount
                            }
                            if save_property_transaction(trans_details):
                                st.success(f"{trans_type} of ${trans_amount:,.2f} logged for {selected_property_name}.")
                                st.rerun()

                # --- Display Transactions & Yield ---
                st.markdown("---")
                st.markdown(f"##### Cash Flow for {selected_property_name}")
                
                try:
                    transactions_df = pd.read_sql('SELECT * FROM "PropertyTransactions" WHERE liability_id = %(lid)s ORDER BY transaction_date DESC', get_engine(), params={'lid': int(liability_id)})
                    
                    if not transactions_df.empty:
                        # --- Annual P&L Calculation for IP properties ---
                        if property_data['sub_type'] == 'IP':
                            # Annualize all transactions
                            transactions_df = annualize_transactions(transactions_df)

                            # Separate into income and expenses
                            income_df = transactions_df[transactions_df['transaction_type'] == 'Income']
                            expense_df = transactions_df[transactions_df['transaction_type'] == 'Expense']

                            # Calculate totals from recurring transactions
                            annual_income = income_df['annualized_amount'].sum()
                            annual_op_expenses = expense_df['annualized_amount'].sum()

                            # Calculate annual interest expense
                            annual_interest = (property_data['balance'] - property_data['offset_balance']) * (property_data['interest_rate'] / 100)
                            
                            # Create a DataFrame for the P&L summary
                            pnl_data = []
                            pnl_data.append({'Category': 'Rental Income', 'Type': 'Income', 'Annual Amount': annual_income})
                            pnl_data.append({'Category': 'Interest Expense (Calculated)', 'Type': 'Expense', 'Annual Amount': -annual_interest})
                            for _, row in expense_df.iterrows():
                                pnl_data.append({'Category': row['category'], 'Type': 'Expense', 'Annual Amount': -row['annualized_amount']})
                            
                            pnl_df = pd.DataFrame(pnl_data)
                            total_annual_expenses = annual_op_expenses + annual_interest
                            net_cash_flow = annual_income - total_annual_expenses
                            
                            # --- Gearing Calculation ---
                            st.markdown("##### Gearing & After-Tax Summary")
                            depreciation = property_data.get('annual_depreciation', 0)
                            tax_rate = property_data.get('marginal_tax_rate', 0) / 100

                            taxable_income = net_cash_flow - depreciation
                            tax_effect = -taxable_income * tax_rate
                            final_cash_position = net_cash_flow + tax_effect

                            gearing_data = {
                                "Description": ["Gross Rental Income", "Cash Expenses (incl. Interest)", "Net Cash Flow (Pre-Tax)", "Depreciation (Non-Cash)", "Total Taxable Income/(Loss)", "Tax Refund/(Payable)", "Final Cash Position (After Tax)"],
                                "Amount": [annual_income, -total_annual_expenses, net_cash_flow, -depreciation, taxable_income, tax_effect, final_cash_position]
                            }
                            gearing_df = pd.DataFrame(gearing_data)

                            st.dataframe(
                                gearing_df.style.format({'Amount': '${:,.2f}'}).map(
                                    lambda x: 'color: red' if x < 0 else 'color: green', subset=pd.IndexSlice[[2, 4, 6], ['Amount']]
                                ),
                                use_container_width=True, hide_index=True
                            )

                            st.markdown("---")
                            st.markdown("##### Recurring Transactions (Annualized)")
                            st.dataframe(pnl_df.style.format({'Annual Amount': '${:,.2f}'}), use_container_width=True, hide_index=True, column_config={"Type": None})

                        st.markdown("---")
                        st.markdown("##### Transaction Log")
                        st.dataframe(transactions_df.drop(columns=['annualized_amount'], errors='ignore'), use_container_width=True, hide_index=True, 
                                     column_config={"amount": st.column_config.NumberColumn("Amount", format="$%.2f")})
                    else:
                        st.info("No income or expense records found for this property yet.")
                except Exception as e:
                    st.error(f"Could not load property transactions: {e}")
        else:
            st.info("No mortgage-type liabilities found. Add one in the 'Manage Loans' tab to track property cash flow.")
    else:
        st.info("No liabilities found. Add one in the 'Manage Loans' tab.")