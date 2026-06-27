CREATE TABLE IF NOT EXISTS "Super_Tracking" (
    "row_id" SERIAL PRIMARY KEY,
    "super_name" TEXT NOT NULL,
    "recorded_date" DATE NOT NULL,
    "value_aud" REAL NOT NULL,
    "created_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);