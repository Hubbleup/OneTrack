-- This is the SQL query to create the "Liabilities" table in your PostgreSQL database.
-- You can use this file for reference or to manually set up your database schema.

CREATE TABLE IF NOT EXISTS "Liabilities" (
    "id" SERIAL PRIMARY KEY,
    "name" TEXT NOT NULL UNIQUE,
    "type" TEXT NOT NULL,
    "sub_type" TEXT,
    "balance" REAL NOT NULL,
    "offset_balance" REAL DEFAULT 0,
    "redraw_balance" REAL DEFAULT 0,
    "interest_rate" REAL,
    "rate_type" TEXT,
    "loan_term_months" INTEGER,
    "loan_start_date" DATE,
    "next_repayment_date" DATE,
    "repayment_amount" REAL,
    "extra_repayment" REAL DEFAULT 0,
    "repayment_frequency" TEXT,
    "last_updated" DATE NOT NULL,
    "created_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table to store income and expenses related to a specific liability (e.g., a property)
CREATE TABLE IF NOT EXISTS "PropertyTransactions" (
    "id" SERIAL PRIMARY KEY,
    "liability_id" INTEGER NOT NULL,
    "transaction_date" DATE NOT NULL,
    "transaction_type" TEXT NOT NULL, -- 'Income' or 'Expense'
    "category" TEXT,
    "description" TEXT,
    "frequency" TEXT DEFAULT 'One-off', -- e.g., One-off, Monthly, Quarterly, Yearly
    "amount" REAL NOT NULL,
    "created_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY ("liability_id") REFERENCES "Liabilities"("id") ON DELETE CASCADE
);