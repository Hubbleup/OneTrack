CREATE TABLE IF NOT EXISTS "Dividends" (
    "id" SERIAL PRIMARY KEY,
    "investment_id" INTEGER,
    "ticker" TEXT NOT NULL,
    "payment_date" TEXT NOT NULL,
    "num_shares" INTEGER NOT NULL,
    "dividend_per_unit" REAL NOT NULL,
    "total_dividend" REAL NOT NULL,
    "franked_amount" REAL,
    "unfranked_amount" REAL,
    "franking_credits" REAL,
    "dividends_reinvested" INTEGER DEFAULT 0,
    "foreign_withholding_tax" REAL DEFAULT 0,
    "holding_type" TEXT,
    "created_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY ("investment_id") REFERENCES "Investment"("id")
);