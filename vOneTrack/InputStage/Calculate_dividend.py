import re
import sqlite3
from typing import Dict, List
import yfinance as yf
from datetime import datetime

class DividendCalculator:
    # Default values for fields not provided by yfinance
    DEFAULT_DIVIDEND_VALUES = {
        'franked_amount': 0,
        'unfranked_amount': 0,
        'franking_credits': 0,
        'dividends_reinvested': 0,
        'foreign_withholding_tax': 0,
        'holding_type': None
    }

    def __init__(self, db_path: str = "onetrack.db"):
        self.db_path = db_path
        self.init_database()

    def _query(self, sql: str, params: tuple = ()) -> List[tuple]:
        """Helper: Execute query and return results."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(sql, params)
        result = cursor.fetchall()
        conn.close()
        return result

    def _execute(self, sql: str, params: tuple = ()) -> None:
        """Helper: Execute query and commit (for INSERT/UPDATE/DELETE)."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(sql, params)
        conn.commit()
        conn.close()

    def init_database(self):
        """Create dividend table if it doesn't exist."""
        self._execute('''
            CREATE TABLE IF NOT EXISTS Dividends (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                investment_id INTEGER,
                ticker TEXT NOT NULL,
                payment_date TEXT NOT NULL,
                num_shares INTEGER NOT NULL,
                dividend_per_unit REAL NOT NULL,
                total_dividend REAL NOT NULL,
                franked_amount REAL,
                unfranked_amount REAL,
                franking_credits REAL,
                dividends_reinvested INTEGER DEFAULT 0,
                foreign_withholding_tax REAL DEFAULT 0,
                holding_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (investment_id) REFERENCES Investment(id)
            )
        ''')

    def _normalize_date(self, date_str: str) -> str:
        """Convert any date format to YYYY-MM-DD."""
        try:
            for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%d-%m-%Y', '%m-%d-%Y', 
                       '%Y/%m/%d', '%Y%m%d', '%d.%m.%Y'):
                try:
                    parsed = datetime.strptime(date_str, fmt)
                    return parsed.strftime('%Y-%m-%d')
                except ValueError:
                    continue
            return date_str
        except Exception:
            return date_str

    def extract_trade_data(self, messages: List[Dict]) -> List[Dict]:
        """Parses Gmail messages for buy orders and checks against Investment table."""
        extracted_data = []
        trade_pattern = r"buy\s+(\d+)\s+([A-Z]+)\s+at\s+([\d\.]+)\s+([A-Z]+)"
        date_pattern = r"filled\s+on\s+(\d{2}/\d{2}/\d{4})"
        
        # Use a single connection for the loop for better performance
        conn = sqlite3.connect(self.db_path)
        
        for msg in messages:
            subject = next((h['value'] for h in msg.get('payload', {}).get('headers', []) if h['name'] == 'Subject'), "")
            
            if "Order filled: BUY" in subject:
                body = msg.get('snippet', '')
                trade_match = re.search(trade_pattern, body, re.IGNORECASE)
                date_match = re.search(date_pattern, body, re.IGNORECASE)
                
                if trade_match:
                    ticker = trade_match.group(2).upper()
                    units = float(trade_match.group(1))
                    price = float(trade_match.group(3))
                    currency = trade_match.group(4)
                    
                    raw_date = date_match.group(1) if date_match else datetime.now().strftime('%d/%m/%Y')
                    clean_date = self._normalize_date(raw_date)
                    
                    # Check if exact record exists in Investment table to flag as duplicate
                    query = "SELECT 1 FROM Investment WHERE Ticker=? AND Units=? AND Purchase_Date=?"
                    exists = conn.execute(query, (ticker, units, clean_date)).fetchone()
                    
                    extracted_data.append({
                        "Status": "⚠️ Already Exists" if exists else "✨ New",
                        "Ticker": ticker,
                        "Units": units,
                        "Price": price,
                        "Currency": currency,
                        "Date": clean_date
                    })
        
        conn.close()
        return extracted_data[:5]

    def get_non_ind_tickers(self) -> List[Dict]:
        """Retrieve all non-IND holdings from Investment table."""
        rows = self._query(
            "SELECT id, Ticker, Units, Country, Purchase_Date FROM Investment WHERE Country <> ?",
            ('IND',)
        )
        return [
            {'id': r[0], 'Ticker': r[1], 'Units': r[2], 'Country': r[3], 'Purchase_Date': r[4]}
            for r in rows
        ]

    def dividend_exists(self, investment_id: int, payment_date: str) -> bool:
        """Check if a dividend record already exists."""
        result = self._query(
            "SELECT id FROM Dividends WHERE investment_id = ? AND payment_date = ?",
            (investment_id, payment_date)
        )
        return len(result) > 0

    def store_dividend(self, ticker: str, payment_date: str, num_shares: int,
                      dividend_per_unit: float, investment_id: int = None, **kwargs) -> bool:
        """Store a single dividend record."""
        values = {**self.DEFAULT_DIVIDEND_VALUES, **kwargs}
        total_dividend = num_shares * dividend_per_unit

        self._execute('''
            INSERT INTO dividends 
            (investment_id, ticker, payment_date, num_shares, dividend_per_unit, total_dividend,
             franked_amount, unfranked_amount, franking_credits, dividends_reinvested,
             foreign_withholding_tax, holding_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (investment_id, ticker, payment_date, num_shares, dividend_per_unit, total_dividend,
              values['franked_amount'], values['unfranked_amount'],
              values['franking_credits'], values['dividends_reinvested'],
              values['foreign_withholding_tax'], values['holding_type']))
        return True

    def fetch_dividend_history(self, ticker: str, from_date: str, country: str = 'USA') -> List[Dict]:
        """Fetch dividend history from yfinance."""
        yahoo_ticker = f"{ticker}.AX" if country == 'AUS' else ticker
        from_date = self._normalize_date(from_date)
        
        try:
            dividends = yf.Ticker(yahoo_ticker).dividends
            if dividends.empty:
                return []
            result = []
            for date, amount in dividends.items():
                payment_date = date.strftime('%Y-%m-%d')
                if payment_date >= from_date:
                    result.append({
                        'payment_date': payment_date,
                        'dividend_per_unit': float(amount)
                    })
            return result
        except Exception:
            return []

    def process_and_store_dividends(self) -> Dict[str, int]:
        """Fetch and store dividends for each Investment row."""
        results = {}
        holdings = self.get_non_ind_tickers()
        if not holdings:
            return results

        for holding in holdings:
            ticker = holding['Ticker']
            history = self.fetch_dividend_history(ticker, holding['Purchase_Date'], holding['Country'])
            
            count = 0
            for div in history:
                if not self.dividend_exists(holding['id'], div['payment_date']):
                    if self.store_dividend(ticker, div['payment_date'], holding['Units'], div['dividend_per_unit'], holding['id']):
                        count += 1
            results[ticker] = count
        return results

    def sync_new_dividends_from_db(self) -> Dict[str, int]:
        results = {}
        # 1. Get all holdings from Investment table
        holdings = self._query("SELECT id, Ticker, Units, Country, Purchase_Date FROM Investment")
        
        for h_id, ticker, units, country, p_date in holdings:
            # 2. Find the last dividend date we have for this specific investment
            last_record = self._query(
                "SELECT MAX(payment_date) FROM Dividends WHERE investment_id = ?", (h_id,)
            )
            
            # Start searching from the later of: Purchase Date OR Last Recorded Dividend
            last_date = last_record[0][0]
            search_start = last_date if last_date else p_date
            
            # 3. Fetch from Yahoo Finance
            history = self.fetch_dividend_history(ticker, search_start, country)
            
            count = 0
            for div in history:
                # 4. Only Insert if the date is strictly NEWER than our last record
                if not last_date or div['payment_date'] > last_date:
                    if self.store_dividend(
                        ticker=ticker, 
                        payment_date=div['payment_date'], 
                        num_shares=units, 
                        dividend_per_unit=div['dividend_per_unit'], 
                        investment_id=h_id
                    ):
                        count += 1
            
            if count > 0:
                results[ticker] = count
                
        return results


# --- EXECUTION ---
if __name__ == '__main__':
    import sys
    db_path = sys.argv[1] if len(sys.argv) > 1 else 'onetrack.db'
    calc = DividendCalculator(db_path)
    print(f"🔄 Syncing dividends history...\n")
    results = calc.process_and_store_dividends()
    print(f"\n✅ Done! Total new records: {sum(results.values())}")
