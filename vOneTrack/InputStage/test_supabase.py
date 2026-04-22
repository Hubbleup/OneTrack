import streamlit as st
import psycopg2
import pandas as pd

st.set_page_config(page_title="Supabase Diagnostic", page_icon="🔌")
st.title("🔌 Supabase Connection Diagnostic")

def test_connection():
    try:
        # Attempt to connect using secrets
        conn = psycopg2.connect(**st.secrets["supabase"])
        st.success("✅ Successfully connected to Supabase!")
        
        # 1. Check for Tables
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
            """)
            tables = [row[0] for row in cur.fetchall()]
            st.write(f"**Found Tables:** {', '.join(tables)}")
            
            # 2. Check row counts for key tables
            for table in ['investment', 'dividends']:
                if table in tables:
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    count = cur.fetchone()[0]
                    st.metric(f"Row count in '{table}'", count)
                else:
                    st.warning(f"⚠️ Table '{table}' not found. Check if name is lowercase in Supabase.")
                    
        conn.close()
    except Exception as e:
        st.error(f"❌ Connection failed: {e}")
        st.info("Ensure your `.streamlit/secrets.toml` or Streamlit Cloud Secrets are configured.")

if __name__ == "__main__":
    test_connection()