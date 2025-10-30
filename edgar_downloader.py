from dataclasses import dataclass
import requests
from typing import List

# You must declare a User-Agent.
# Replace with your own info if you want.
HEADERS = {"User-Agent": "PyQuantEDGAR Contact@example.com"}

@dataclass(frozen=True)
class Filing:
    """A structured container for a single SEC filing."""
    cik: str
    accessionNumber: str
    filingDate: str
    reportDate: str
    formType: str
    isXBRL: bool
    isInlineXBRL: bool
    primaryDocument: str

def get_cik_map():
    """
    Downloads the SEC's CIK/ticker mapping and returns a dictionary
    mapping lowercase tickers to 10-digit zero-padded CIK numbers.
    """
    url = "https://www.sec.gov/files/company_tickers.json"
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()  # Raise an exception for bad status codes
    data = response.json()

    cik_map = {}
    for row in data.values():
        ticker = row['ticker'].lower()
        cik = f"{row['cik_str']:010d}"  # Formats to 10-digit zero-padded string
        cik_map[ticker] = cik

    return cik_map

def list_filings(cik: str) -> List[Filing]:
    """
    Lists all 10-K and 10-Q filings with XBRL for a given CIK.
    """
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    data = response.json()

    recent = data['filings']['recent']
    acc_numbers = recent.get('accessionNumber', [])
    filing_dates = recent.get('filingDate', [])
    report_dates = recent.get('reportDate', [])
    form_types = recent.get('form', [])
    is_xbrls = recent.get('isXBRL', [])
    is_inline_xbrls = recent.get('isInlineXBRL', [])
    primary_documents = recent.get('primaryDocument', [])

    filings_list = []
    # Note the two changes here:
    for acc_num, f_date, r_date, form, is_xbrl, is_inline, doc in zip(
        acc_numbers, filing_dates, report_dates, form_types, is_xbrls, is_inline_xbrls, primary_documents
    ):
        # ... (your filter logic)
        if (form in {"10-K", "10-Q"}) and (is_xbrl or is_inline):
            filings_list.append(
                Filing(
                    cik=cik,
                    accessionNumber=acc_num,
                    filingDate=f_date,
                    reportDate=r_date,
                    formType=form,
                    isXBRL=bool(is_xbrl),       # Good idea to cast to bool
                    isInlineXBRL=bool(is_inline), # Good idea to cast to bool
                    primaryDocument=doc        # <-- ADD THIS
                )
            )
    
    return filings_list

if __name__ == "__main__":
    print("--- Testing edgar_downloader.py ---")

    # Test 1: CIK Mapper
    print("\n[Test 1] Loading CIK map...")
    cik_map = get_cik_map()
    print(f"AAPL CIK: {cik_map.get('aapl')}")
    print(f"MSFT CIK: {cik_map.get('msft')}")
    print("[Test 1] Passed.")

    # Test 2: list_filings
    print("\n[Test 2] Listing filings for AAPL (0000320193)...")
    aapl_cik = cik_map.get('aapl', '0000320193')
    
    filings = list_filings(aapl_cik)
    
    if filings:
        print(f"Found {len(filings)} XBRL-enabled 10-K/10-Q filings.")
        print(f"  Oldest filing found: {filings[-1]}") # Filings are newest-first
        print(f"  Newest filing found: {filings[0]}")
        print("[Test 2] Passed.")
    else:
        print("[Test 2] FAILED: No filings found.")

    print("\n--- All tests complete. ---")
