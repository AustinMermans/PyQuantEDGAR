---
date created: 2025-10-29
tags: 
---


# XBRL Ground Truth Pipeline

---

## 1. Project Title
PyQuantEDGAR - Stage 1: XBRL Ground Truth Pipeline

---

## 2. Project Motivation
The goal of this project is to build a robust, open-source Python data pipeline that creates a 100% accurate, queryable database of historical financials for publicly traded US companies.

This pipeline will **exclusively target modern (post-~2009), XBRL-tagged SEC filings**. The resulting SQLite database will serve as the "ground truth"—a clean, reliable dataset essential for quantitative analysis and for training a potential "Stage 2" AI-based historical data-filling model.

---

## 3. Core Features & Scope (Version 1.0)

##### ✅ **In-Scope:**
* **CIK-Ticker Mapping:** A module to resolve company tickers (e.g., `AAPL`) or names (e.g., `Apple Inc.`) to their CIK numbers.
* **Filing Indexing:** Download a company's filing history (`10-K`, `10-Q`) from the `data.sec.gov` JSON endpoints.
* **XBRL Identification:** The tool **must** identify which filings contain structured XBRL data by reading the `isXBRL` and `isInlineXBRL` flags from the SEC's JSON data.
* **XBRL-Only Parsing:** The parser will *only* process filings flagged as XBRL. It will download the associated `.xml` files and parse them.
* **Metric Extraction:** The parser will be configured to extract a specific list of financial metrics (see section 4).
* **Database Storage:** All extracted, structured data will be saved into a local **SQLite** database.
* **CLI Interface:** The project will be run on-demand via a command-line interface (e.g., `python main.py --tickers AAPL,MSFT`).

##### ❌ **Out-of-Scope (Critical Boundaries):**
* **No Text/HTML Parsing:** This project will **not** attempt to parse `.txt` or `.htm` files. All regex and/or LLM parsing is deferred to Stage 2.
* **No Legacy Data:** Filings without an XBRL flag (primarily pre-~2009) will be **skipped**.
* **No Other Forms:** We will focus exclusively on `10-K` and `10-Q` forms. `8-K`, `13F`, etc., are not in scope.
* **No Web API:** This will not be a web service.

---

## 4. Target Metrics (Version 1.0)
The parser's initial goal is to find and extract the following four key metrics. The parser must be able to find the standard US-GAAP (us-gaap) taxonomy tags.

| Metric | Common US-GAAP XBRL Tags |
| :--- | :--- |
| **Total Revenues** | `Revenues`, `SalesRevenueNet`, `RevenuesNet` |
| **Net Income** | `NetIncomeLoss` |
| **Total Assets** | `Assets` |
| **Total Liabilities** | `Liabilities` |

---

## 5. Technical Stack
* **Language:** `Python 3.10+`
* **Downloading:** `requests` (for all HTTP calls to SEC.gov)
* **Parsing:** `lxml` (The standard, high-performance library for parsing `.xml` XBRL files)
* **Database:** `sqlite3` (Built-in Python module)
* **Data Staging:** `pandas` (Useful for holding data before inserting it into the DB)
* **CLI:** `argparse` (Built-in Python module for creating the user interface)
* **Concurrency:** `concurrent.futures` (For parallel downloading of filings)

---

## 6. Database Schema
The pipeline will populate two main tables in a single `edgar_data.db` file.

**Table 1: `companies`**
This table maps a CIK to its common identifiers.
* `cik` (TEXT, Primary Key): The 10-digit Central Index Key.
* `ticker` (TEXT): The company's most recent ticker symbol.
* `name` (TEXT): The company's official name.

**Table 2: `financial_facts`**
This is the main data table. It stores every individual fact in a "tidy" format.
* `id` (INTEGER, Primary Key): A unique ID for the row.
* `company_cik` (TEXT): Foreign Key to `companies.cik`.
* `metric` (TEXT): The name of the financial metric (e.g., `NetIncomeLoss`).
* `value` (REAL): The extracted numeric value (e.g., `12345000000`).
* `period_end_date` (TEXT): The end date of the reporting period (e.g., "2025-09-30").
* `fiscal_year` (INTEGER): The reported fiscal year.
* `fiscal_quarter` (INTEGER): The reported fiscal quarter (1-4).
* `form_type` (TEXT): The form this fact came from ("10-K" or "10-Q").
* `filing_date` (TEXT): The date the report was filed with the SEC.

---

## 7. Architecture & Key Modules
This project can be broken into 3-4 key Python files:

**1. `database.py`**
* **Purpose:** Handles all SQLite database interactions.
* **Key Functions:**
    * `create_connection()`: Connects to the `edgar_data.db` file.
    * `create_tables()`: Runs the `CREATE TABLE` SQL to build the schema.
    * `insert_company(cik, ticker, name)`: Adds/updates a company in the `companies` table.
    * `insert_financials(facts_list)`: Bulk-inserts a list of parsed facts into the `financial_facts` table.

**2. `edgar_downloader.py`**
* **Purpose:** Handles all communication with SEC.gov. This module *gets* the work, it doesn't *do* the work.
* **Classes/Functions:**
    * `CIKMapper`: Uses the `company_tickers.json` file to build a lookup. Your `lookup_cik` function is perfect for this.
    * `FilingDownloader`:
        * `list_filings(cik, start_date)`: Fetches the `submissions/CIK{...}.json` file.
        * It will parse this JSON and return a list of `Filing` objects.
        * Crucially, the `Filing` object **must** store the `isXBRL` and `isInlineXBRL` booleans, along with the `accessionNumber`, `filingDate`, etc.

**3. `xbrl_parser.py`**
* **Purpose:** The core logic. Takes a `Filing` object and extracts the data.
* **Classes/Functions:**
    * `XBRLParser`:
        * `parse_filing(filing)`:
            1.  Checks `if not filing.isXBRL and not filing.isInlineXBRL: return []`.
            2.  Constructs the URL for the primary `.xml` data file from the `accessionNumber`.
            3.  Downloads the `.xml` file content.
            4.  Uses `lxml` and `xpath` to find all tags matching our target metrics (e.g., `//us-gaap:NetIncomeLoss`).
            5.  For each tag found, it also finds its `contextRef` (to get the date) and `unitRef` (to check for USD).
            6.  Returns a list of dictionaries, where each one is a clean row for our `financial_facts` table.

**4. `main.py`**
* **Purpose:** The entry point that ties everything together.
* **Logic:**
    1.  Uses `argparse` to get user input (e.g., `--tickers "AAPL,MSFT"`).
    2.  Initializes the `DatabaseManager` and `CIKMapper`.
    3.  For each ticker:
        * Gets the CIK.
        * Calls `FilingDownloader.list_filings()` to get a list of all `Filing` objects.
        * Iterates through the list of filings.
        * Passes each `Filing` to `XBRLParser.parse_filing()`.
        * Takes the returned list of facts and passes them to `DatabaseManager.insert_financials()`.

---

## 8. Example Workflow (User Story)
1.  **User runs:** `python main.py --tickers "MSFT" --start-year 2010`
2.  `main.py` starts.
3.  `CIKMapper` looks up "MSFT" -> "0000789019".
4.  `FilingDownloader` fetches all 10-K/10-Q filings for "0000789019" since 2010.
5.  `main.py` loops through the list...
    * It picks a 2012 10-K. It sees `isXBRL: True`. It sends this to the parser.
    * `XBRLParser` downloads the `.xml`, finds `<us-gaap:NetIncomeLoss ...>16008000000</us-gaap:NetIncomeLoss>`, and returns a clean data row.
    * `DatabaseManager` inserts this row.
    * It picks a 2005 10-K. It sees `isXBRL: False`. It **skips this filing**.
6.  The script finishes. The user now has all of Microsoft's XBRL-era financial facts for our four metrics in `edgar_data.db`.


