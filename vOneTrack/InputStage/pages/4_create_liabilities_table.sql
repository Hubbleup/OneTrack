CREATE TABLE IF NOT EXISTS "Liabilities" (
    "id" SERIAL PRIMARY KEY,
    "name" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "balance" REAL NOT NULL,
    "last_updated" DATE NOT NULL,
    "created_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);