---
date created: 2025-10-29
tags: 
---
# PyQuantEDGAR - XBRL Ground Truth Pipeline

The goal of this project is to build a robust, open-source Python data pipeline that creates an accurate, queryable database of historical financials for publicly traded US companies.

This pipeline targets **XBRL-enabled SEC filings (approx. 2009-present)**. The resulting SQLite database serves as the "ground truth"—a clean, reliable dataset essential for quantitative analysis and for training a future "Stage 2" AI model.

This project was built bottom-up, module-by-module, with a focus on testing and robustness.

---

## 1. Core Features & Scope (Version 1.0)

##### ✅ **In-Scope:**
* **CIK-Ticker Mapping:** Resolves company tickers (e.g., `AAPL`) to their 10-digit CIK numbers.
* **Full Filing History:** Intelligently parses the `submissions.json` API, including all historical "paginated" files, to fetch the *complete* filing history for a company (not just the "recent" view).
* **Smart URL Discovery:** Automatically finds the correct parsable file (`.xml` or `.htm`) for both old-style XBRL and new-style iXBRL filings.
* **Metric Aliasing:** Parses filings using a "cheat sheet" of known tag variations (`METRIC_ALIASES`) to correctly find metrics across different years and taxonomy versions.
* **Value Processing:** Correctly scales financial values based on the `decimals` attribute (e.g., handles millions, thousands) and cleans numeric text.
* **Database Storage:** Saves all extracted facts into a local `edgar_data.db` SQLite database.
* **CLI Interface:** Runs on-demand via a command-line interface (e.g., `python main.py --tickers AAPL --start-year 2009`).

##### ❌ **Out-of-Scope (Critical Boundaries):**
* **No Text/HTML Parsing:** This tool does *not* parse unstructured text from pre-XBRL filings (pre-~2009). This is deferred to Stage 2.
* **No "Librarian" (Stage 1.5):** This version does not yet dynamically parse taxonomy files (`_pre.xml`, `_lab.xml`). It relies on the manually-curated `METRIC_ALIASES` map.
* **No Other Forms:** Exclusively focuses on `10-K` and `10-Q` forms.

---

## 2. Target Metrics (Version 1.0)
The parser uses an aliasing map to find the most common tag variations for each standard metric. This allows it to find facts across different US-GAAP taxonomy versions.

| Standard Metric | Common US-GAAP XBRL Tags (Aliases) |
| :--- | :--- |
| **Revenues** | `Revenues`, `SalesRevenueNet`, `RevenueFromContractWithCustomerExcludingAssessedTax` |
| **NetIncomeLoss** | `NetIncomeLoss`, `ProfitLoss` |
| **Assets** | `Assets` |
| **Liabilities** | `Liabilities` |
| **GrossProfit** | `GrossProfit` |
| **OperatingIncomeLoss**| `OperatingIncomeLoss` |
| **EarningsPerShareDiluted** | `EarningsPerShareDiluted` |
| **AssetsCurrent** | `AssetsCurrent` |
| **LiabilitiesCurrent** | `LiabilitiesCurrent` |
| **StockholdersEquity** | `StockholdersEquity`, `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest` |
| **CashAndCashEquivalents...** | `CashAndCashEquivalentsAtCarryingValue` |
| **NetCash...Operating** | `NetCashProvidedByUsedInOperatingActivities` |
| **NetCash...Investing** | `NetCashProvidedByUsedInInvestingActivities` |
| **NetCash...Financing**| `NetCashProvidedByUsedInFinancingActivities` |

---

## 3. Technical Stack
* **Language:** `Python 3.10+`
* **Downloading:** `requests`
* **Parsing:** `lxml`
* **Database:** `sqlite3`
* **CLI:** `argparse`

---

## 4. Database Schema
The pipeline populates two tables in `edgar_data.db`:

**Table 1: `companies`**
* `cik` (TEXT, Primary Key): The 10-digit Central Index Key.
* `ticker` (TEXT): The company's ticker symbol.
* `name` (TEXT): The company name.

**Table 2: `financial_facts`**
* `id` (INTEGER, Primary Key): A unique ID for the fact.
* `company_cik` (TEXT): Foreign Key to `companies.cik`.
* `metric` (TEXT): The **standardized** metric name (e.g., "Revenues").
* `value` (REAL): The final, scaled numeric value.
* `period_end_date` (TEXT): The end date of the reporting period ("YYYY-MM-DD").
* `fiscal_year` (INTEGER): The reported fiscal year.
* `fiscal_quarter` (INTEGER): The reported fiscal quarter (1-4).
* `form_type` (TEXT): "10-K" or "10-Q".
* `filing_date` (TEXT): The date the form was filed ("YYYY-MM-DD").

---

## 5. Architecture ("The Newsroom")
* **`main.py` (The Editor-in-Chief):** The "controller." Takes commands from the user (via CLI), and directs the other modules to run the full pipeline, handling errors gracefully.
* **`database.py` (The News Archive):** Handles all SQLite database interactions: creating the tables and inserting the final, clean facts.
* **`edgar_downloader.py` (The Book Runner / Field Reporter):** Handles all communication with SEC.gov. Finds CIKs and fetches the *complete, paginated* filing history (all JSON files) for a company.
* **`xbrl_parser.py` (The Reader):** The "brains."
    1.  Receives a single `Filing` object.
    2.  Finds the correct `.xml` or `.htm` file to parse.
    3.  Parses the document using `lxml`.
    4.  Uses the `METRIC_ALIASES` map to find all relevant facts.
    5.  Parses the `<context>` elements to find the correct dates.
    6.  Selects the *most relevant* fact for each metric.
    7.  Cleans and scales the numeric value (using the `decimals` attribute).
    8.  Returns a final list of facts, ready for the database.

---

## 6. Example Workflow (User Story)
1.  **User runs:** `python main.py --tickers "AAPL" --start-year 2009`
2.  `main.py` starts.
3.  `database.py` initializes the `edgar_data.db` tables.
4.  `edgar_downloader.py` fetches the CIK for "aapl" (`0000320193`).
5.  `edgar_downloader.py` fetches `CIK0000320193.json`, finds the `filings.files` array, and downloads all historical JSON files (e.g., `...-001.json`). It builds a *complete* list of all 65 XBRL-enabled filings from 2009-present.
6.  `main.py` loops through this complete list.
    * It picks the 2017 10-K. It passes the `Filing` object to the parser.
    * `xbrl_parser.py` sees `isInlineXBRL: False` and `primaryDocument: 'aapl-20170930.htm'`.
    * It correctly builds the URL to `.../aapl-20170930.xml`.
    * It parses the `.xml` file and uses the "aliasing" logic (Method B) to find the tags (e.g., `us-gaap:SalesRevenueNet`).
    * It finds 12 facts, adjusts their values, and returns them as a list of clean dictionaries.
    * `database.py` inserts these 12 facts into the `financial_facts` table.
7.  The loop continues, populating the database with the full XBRL history.
8.  The script finishes: "Pipeline execution complete."