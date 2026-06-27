CREATE TABLE IF NOT EXISTS "Investment" (
    "id" SERIAL PRIMARY KEY,
    "Ticker" TEXT,
    "Units" REAL,
    "Purchase_Price" REAL,
    "Avg_Purchase_Price" REAL,
    "Purchase_Value" REAL,
    "Purchase_Date" TEXT,
    "Country" TEXT,
    "Currency" TEXT,
    "Exchange_Rate" REAL,
    "Remain_Balance" REAL,
    "Account_Platform" TEXT,
    "Live_Price" REAL,
    "Live_Value" REAL,
    "Capital_Gain_Value" REAL,
    "Capital_Gain_Percent" REAL,
    "Investment_Type" TEXT
);