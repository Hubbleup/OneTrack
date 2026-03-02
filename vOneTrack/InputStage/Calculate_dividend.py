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

    def __init__(self, db_path: str = "dividends.db"):
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

    def store_dividend(self, ticker: str, payment_date: str, num_shares: int,
                      dividend_per_unit: float, investment_id: int = None, **kwargs) -> bool:
        """Store a single dividend record.
        
        Args:
            ticker: Stock ticker symbol
            payment_date: Date dividend was paid (YYYY-MM-DD)
            num_shares: Number of shares held
            dividend_per_unit: Dividend amount per share
            investment_id: Foreign key to Investment table (optional)
            **kwargs: Optional franked_amount, unfranked_amount, etc.
        """
        # Merge provided kwargs with defaults
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

    def get_non_ind_tickers(self) -> List[Dict]:
        """Retrieve all non-IND holdings from Investment table.
        
        Returns each row separately (not consolidated) so dividends can be
        calculated based on individual purchase dates.
        """
        rows = self._query(
            "SELECT id, Ticker, Units, Country, Purchase_Date FROM Investment WHERE Country <> ?",
            ('IND',)
        )
        return [
            {'id': r[0], 'Ticker': r[1], 'Units': r[2], 'Country': r[3], 'Purchase_Date': r[4]}
            for r in rows
        ]

    def _normalize_date(self, date_str: str) -> str:
        """Convert any date format to YYYY-MM-DD."""
        try:
            # Try common date formats (order matters - try specific formats first)
            for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%d-%m-%Y', '%m-%d-%Y', 
                       '%Y/%m/%d', '%Y%m%d', '%d.%m.%Y'):
                try:
                    parsed = datetime.strptime(date_str, fmt)
                    return parsed.strftime('%Y-%m-%d')
                except ValueError:
                    continue
            # If no format matched, print warning and return as-is
            print(f"    WARNING: Could not parse date '{date_str}' - verify database format")
            return date_str
        except Exception as e:
            print(f"    WARNING: Date error for '{date_str}': {e}")
            return date_str

    def dividend_exists(self, investment_id: int, payment_date: str) -> bool:
        """Check if a dividend record already exists for this investment and date."""
        result = self._query(
            "SELECT id FROM Dividends WHERE investment_id = ? AND payment_date = ?",
            (investment_id, payment_date)
        )
        return len(result) > 0

    def fetch_dividend_history(self, ticker: str, from_date: str, country: str = 'USA') -> List[Dict]:
        """Fetch dividend history from yfinance, filtered by purchase date.
        
        Args:
            ticker: Stock ticker
            from_date: Only return dividends on or after this date (YYYY-MM-DD)
            country: Country code (USA, AUS, etc.) to apply correct ticker suffix
        """
        # Apply country-specific suffixes for Yahoo Finance
        yahoo_ticker = ticker
        if country == 'AUS':
            yahoo_ticker = f"{ticker}.AX"
        # Add more country-specific suffixes as needed
        # elif country == 'IND':
        #     yahoo_ticker = f"{ticker}.NS"
        
        # Normalize the purchase date to YYYY-MM-DD format
        from_date = self._normalize_date(from_date)
        print(f"    DEBUG: Filtering dividends from {from_date} onwards (using ticker: {yahoo_ticker})")
        
        try:
            dividends = yf.Ticker(yahoo_ticker).dividends
            if dividends.empty:
                print(f"    DEBUG: No dividends found in yfinance for {yahoo_ticker}")
                return []
            result = []
            for date, amount in dividends.items():
                payment_date = date.strftime('%Y-%m-%d')
                # Only include dividends on or after purchase date
                if payment_date >= from_date:
                    result.append({
                        'payment_date': payment_date,
                        'dividend_per_unit': float(amount)
                    })
                else:
                    print(f"    DEBUG: Filtered out {payment_date} (before {from_date})")
            print(f"    DEBUG: Found {len(result)} dividends after {from_date}")
            return result
        except Exception as e:
            print(f"ERROR fetching {yahoo_ticker}: {e}")
            return []

    def process_and_store_dividends(self) -> Dict[str, int]:
        """Fetch and store dividends for each Investment row.
        
        Processes each Investment entry separately, using its purchase date
        to filter which dividends apply.
        """
        results = {}
        no_dividend_tickers = []  # Track tickers with no dividends
        processed_tickers = []     # Track all processed tickers
        
        holdings = self.get_non_ind_tickers()

        if not holdings:
            print("No non-IND holdings found.")
            return results

        print(f"\nFound {len(holdings)} holdings to process...\n")

        for holding in holdings:
            investment_id = holding['id']
            ticker = holding['Ticker']
            units = holding['Units']
            country = holding['Country']
            purchase_date_raw = holding['Purchase_Date']
            purchase_date = self._normalize_date(str(purchase_date_raw))
            
            processed_tickers.append(ticker)
            print(f"Processing {ticker} (ID: {investment_id}, {units} units, {country})")
            print(f"  Raw date from DB: {purchase_date_raw} -> Normalized: {purchase_date}")

            # Fetch only dividends from purchase date onwards
            dividends = self.fetch_dividend_history(ticker, purchase_date, country)
            if not dividends:
                print(f"  ⚠ No dividends found from {purchase_date}")
                no_dividend_tickers.append(ticker)
                continue

            count = 0
            for div in dividends:
                if self.dividend_exists(investment_id, div['payment_date']):
                    print(f"  Skipping {div['payment_date']} (already stored)")
                    continue

                self.store_dividend(
                    investment_id=investment_id,
                    ticker=ticker,
                    payment_date=div['payment_date'],
                    num_shares=units,
                    dividend_per_unit=div['dividend_per_unit']
                )
                count += 1
                print(f"  Stored {div['payment_date']} (${div['dividend_per_unit']:.4f}/unit)")

            key = f"{ticker} (ID:{investment_id}, {purchase_date})"
            results[key] = count

        # Summary
        print("\n" + "="*60)
        print("SUMMARY")
        print("="*60)
        print(f"Total holdings processed: {len(processed_tickers)}")
        print(f"Tickers processed: {', '.join(sorted(set(processed_tickers)))}")
        print(f"\nTickers with NO dividends from yfinance ({len(no_dividend_tickers)}):")
        if no_dividend_tickers:
            print(f"  {', '.join(sorted(set(no_dividend_tickers)))}")
        print(f"\nTotal dividend records stored: {sum(results.values())}")

        return results


if __name__ == '__main__':
    import sys

    db_path = sys.argv[1] if len(sys.argv) > 1 else 'onetrack.db'
    calc = DividendCalculator(db_path)

    print(f"Fetching and storing dividend history from yfinance...\n")
    results = calc.process_and_store_dividends()

    print(f"\nTotal records stored: {sum(results.values())}")
