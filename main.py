"""
PyQuantEDGAR Main Controller
"""
import argparse
import time
import requests

import database
import edgar_downloader
import xbrl_parser
import taxonomy_parser
from xbrl_parser import save_new_aliases

import pandas as pd


def setup_cli():
    """
    Configure and parse command-line arguments.
    """
    parser = argparse.ArgumentParser(description="PyQuantEDGAR controller.")
    parser.add_argument(
        "--tickers",
        required=True,
        type=str,
        help="Comma-separated list of ticker symbols to process.",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        help="Optional start year to filter filings.",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        help="Optional end year to filter filings.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = setup_cli()
    print(f"Arguments received: {args}")

    database.initialize_database()

    cik_map = None
    for attempt in range(1, 4):
        try:
            cik_map = edgar_downloader.get_cik_map()
            print("CIK map loaded.")
            break
        except requests.RequestException as exc:
            print(f"Attempt {attempt} to load CIK map failed: {exc}.")
            if attempt < 3:
                time.sleep(1.0)
            else:
                print("Failed to load CIK map after multiple attempts. Exiting.")
                raise SystemExit(1)

    raw_tickers = args.tickers.split(",")
    tickers = [ticker.strip().lower() for ticker in raw_tickers if ticker.strip()]

    def filing_year(filing):
        """
        Determine the best available year for filtering, preferring reportDate.
        """
        for date_str in (filing.reportDate, filing.filingDate):
            if date_str and len(date_str) >= 4:
                try:
                    return int(date_str[:4])
                except ValueError:
                    continue
        return None

    start_year = args.start_year
    end_year = args.end_year

    for ticker in tickers:
        print(f"Looking up CIK for '{ticker}'...")
        cik = cik_map.get(ticker)
        if not cik:
            print(f"Warning: CIK not found for ticker '{ticker}'. Skipping.")
            continue

        time.sleep(0.2)

        try:
            filings = edgar_downloader.list_filings(cik)
        except requests.RequestException as exc:
            print(f"[{ticker.upper()}] Error fetching filings: {exc}. Skipping.")
            continue

        if not filings:
            print(f"[{ticker.upper()}] No XBRL filings found. Skipping.")
            continue

        if start_year or end_year:
            pre_filter_count = len(filings)
            filtered = []
            for filing in filings:
                year = filing_year(filing)
                if year is None:
                    filtered.append(filing)
                    continue
                if start_year and year < start_year:
                    continue
                if end_year and year > end_year:
                    continue
                filtered.append(filing)
            filings = filtered
            print(
                f"[{ticker.upper()}] Filtered filings from {pre_filter_count} to {len(filings)} "
                f"using start_year={start_year}, end_year={end_year}."
            )
            if not filings:
                range_desc = []
                if start_year:
                    range_desc.append(f"on or after {start_year}")
                if end_year:
                    range_desc.append(f"on or before {end_year}")
                constraint = " and ".join(range_desc) if range_desc else "specified range"
                print(f"[{ticker.upper()}] No filings {constraint}. Skipping.")
                continue

        print(f"[{ticker.upper()}] Found {len(filings)} XBRL filings. Processing...")

        for filing in filings:
            time.sleep(0.2)

            try:
                extracted_facts = xbrl_parser.parse_filing(filing)
            except requests.RequestException as exc:
                print(f"  [{filing.accessionNumber}] Request error: {exc}. Skipping filing.")
                continue
            except Exception as exc:
                print(f"  [{filing.accessionNumber}] Unexpected error: {exc}. Skipping filing.")
                continue

            if not extracted_facts:
                print(f"  - No facts found. Calling Librarian for {filing.accessionNumber}...")
                try:
                    missing_metrics = list(xbrl_parser._load_aliases().keys())
                    print(f"  > Librarian searching for metrics: {missing_metrics}")
                    new_aliases = taxonomy_parser.discover_aliases(filing, missing_metrics)
                except Exception as exc:
                    print(f"  > Librarian encountered an error: {exc}")
                    new_aliases = {}

                if new_aliases:
                    print(f"  > Librarian found new aliases: {new_aliases}")
                    print(f"  > Metrics updated: {list(new_aliases.keys())}")
                    try:
                        save_new_aliases(new_aliases)
                    except Exception as exc:
                        print(f"  > Failed to save new aliases: {exc}")
                    else:
                        try:
                            extracted_facts = xbrl_parser.parse_filing(filing)
                        except Exception as exc:
                            print(f"  > Re-parse failed after updating aliases: {exc}")
                            extracted_facts = []
                else:
                    print("  > Librarian did not find new aliases.")

            if extracted_facts:
                try:
                    saved = database.insert_financial_facts(extracted_facts)
                    print(
                        f"  Processed {filing.formType} ({filing.filingDate}): "
                        f"{saved} facts saved."
                    )
                except Exception as exc:
                    print(f"  Failed to save facts for {filing.accessionNumber}: {exc}")
            else:
                print(
                    f"  Processed {filing.formType} ({filing.filingDate}): "
                    "No target facts found."
                )

    print("Pipeline execution complete.")
    args = setup_cli()
    # ... (all your main pipeline code) ...
    print("Pipeline execution complete.")

    # --- Start of new query code ---
    print("\n--- Verifying Data in Database ---")
    if args.tickers:
        first_ticker_to_check = args.tickers.split(',')[0]
        # Call our new function
        df = database.query_facts_by_ticker(first_ticker_to_check)
        
        if not df.empty:
            print(f"Successfully fetched {len(df)} facts for {first_ticker_to_check.upper()}.")
            print("--- Most Recent Facts ---")
            print(df.head()) # Print the first 5 rows
        else:
            print(f"No facts found in DB for {first_ticker_to_check.upper()}.")
