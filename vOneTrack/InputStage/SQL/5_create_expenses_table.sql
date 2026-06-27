CREATE TABLE IF NOT EXISTS "Expenses" (
    "id" SERIAL PRIMARY KEY,
    "expense_date" DATE NOT NULL,
    "vendor" TEXT,
    "category" TEXT,
    "amount" REAL NOT NULL,
    "description" TEXT,
    "created_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);