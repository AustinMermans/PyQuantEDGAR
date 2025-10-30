import sqlite3

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

if __name__ == "__main__":
    initialize_database()
