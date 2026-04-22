import sqlite3

# Helper to map SQLite types to PostgreSQL types
def sqlite_to_postgres_type(sqlite_type):
    t = sqlite_type.upper()
    if t in ("INTEGER", "INT"):
        return "INTEGER"
    elif t in ("REAL", "FLOAT", "DOUBLE"):
        return "DOUBLE PRECISION"
    elif t in ("TEXT", "VARCHAR"):
        return "TEXT"
    elif t in ("BLOB", ):
        return "BYTEA"
    elif t in ("NUMERIC", "NUM"):
        return "NUMERIC"
    elif t in ("DATETIME", "DATE", "TIMESTAMP"):
        return "TIMESTAMP"
    else:
        return "TEXT"  # Default fallback

db_path = "onetrack.db"  # Change if your DB file is named differently
conn = sqlite3.connect(db_path)
cur = conn.cursor()

# Get all user table names
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
tables = [row[0] for row in cur.fetchall()]

for table in tables:
    cur.execute(f"PRAGMA table_info({table});")
    columns = cur.fetchall()
    print(f"-- Table: {table}")
    print(f'CREATE TABLE "{table}" (')
    col_defs = []
    pk_cols = []
    for col in columns:
        col_name = col[1]
        col_type = sqlite_to_postgres_type(col[2])
        col_def = f'  "{col_name}" {col_type}'
        if col[5]:  # PK
            pk_cols.append(f'"{col_name}"')
        col_defs.append(col_def)
    print(",\n".join(col_defs))
    if pk_cols:
        print(f',\n  PRIMARY KEY ({', '.join(pk_cols)})')
    print(");\n")

cur.close()
conn.close()