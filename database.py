import sqlite3
import pandas as pd
import requests

DB_FILE = "edgar_data.db"

CREATE_COMPANIES_TABLE = """
CREATE TABLE IF NOT EXISTS companies (
    cik TEXT PRIMARY KEY,
    ticker TEXT,
    name TEXT
);
"""

CREATE_FACTS_TABLE = """
CREATE TABLE IF NOT EXISTS financial_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_cik TEXT,
    metric TEXT,
    value REAL,
    period_end_date TEXT,
    fiscal_year INTEGER,
    fiscal_quarter INTEGER,
    form_type TEXT,
    filing_date TEXT,
    FOREIGN KEY(company_cik) REFERENCES companies(cik)
);
"""

def initialize_database():
    """Initializes the database and creates the companies and financial_facts tables."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(CREATE_COMPANIES_TABLE)
    cursor.execute(CREATE_FACTS_TABLE)
    conn.close()
    print("Database and tables initialized.")

def insert_financial_facts(facts):
    """Inserts a list of financial fact dictionaries into the database."""
    if not facts:
        return 0

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    rows = [
        (
            fact.get("company_cik"),
            fact.get("metric"),
            fact.get("value"),
            fact.get("period_end_date"),
            fact.get("fiscal_year"),
            fact.get("fiscal_quarter"),
            fact.get("form_type"),
            fact.get("filing_date"),
        )
        for fact in facts
    ]

    cursor.executemany(
        """
        INSERT INTO financial_facts (
            company_cik,
            metric,
            value,
            period_end_date,
            fiscal_year,
            fiscal_quarter,
            form_type,
            filing_date
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    conn.close()

    return len(rows)

def query_facts_by_ticker(ticker: str) -> pd.DataFrame:
    """
    Queries the database for all facts for a given ticker
    and returns them as a pandas DataFrame.
    """
    print(f"\nQuerying database for ticker: {ticker.upper()}...")

    # We need the CIK for the ticker
    # (This is a bit redundant, but simple for a test)
    try:
        response = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers={"User-Agent": "PyQuantEDGAR Contact@example.com"}
        )
        response.raise_for_status()
        data = response.json()
        cik_map = {row['ticker'].lower(): f"{row['cik_str']:010d}" for row in data.values()}
        cik = cik_map.get(ticker.lower())

        if not cik:
            print(f"Ticker {ticker} not found in CIK map.")
            return pd.DataFrame() # Return empty DataFrame
    except Exception as e:
        print(f"Error fetching CIK map: {e}")
        return pd.DataFrame()

    # Now, query the database
    try:
        conn = sqlite3.connect(DB_FILE)
        # Use pandas to read the SQL query directly into a DataFrame
        df = pd.read_sql_query(
            f"SELECT * FROM financial_facts WHERE company_cik = '{cik}' ORDER BY period_end_date DESC", 
            conn
        )
        return df
    except Exception as e:
        print(f"Error querying database: {e}")
        return pd.DataFrame()
    finally:
        if 'conn' in locals() and conn:
            conn.close()

if __name__ == "__main__":
    initialize_database()
