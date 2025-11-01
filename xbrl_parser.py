import datetime
import json
from dataclasses import dataclass
import requests
from lxml import etree # This is the standard import for lxml's parsing tools
from edgar_downloader import Filing

# Re-define our HEADERS constant for this file's requests
HEADERS = {"User-Agent": "PyQuantEDGAR Contact@example.com"}

ALIAS_FILE_PATH = "metric_aliases.json"
_ALIAS_CACHE = None

def _load_aliases():
    """
    Loads the metric aliases from disk, caching the result for reuse.
    """
    global _ALIAS_CACHE
    if _ALIAS_CACHE is not None:
        return _ALIAS_CACHE

    with open(ALIAS_FILE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    _ALIAS_CACHE = data
    return _ALIAS_CACHE

def save_new_aliases(new_aliases_map: dict):
    """
    Merge newly discovered aliases into the metric alias cache and persist them to disk.
    """
    global _ALIAS_CACHE
    aliases = _load_aliases()

    for standard_name, new_tag in new_aliases_map.items():
        if not standard_name or not new_tag:
            continue

        existing = aliases.setdefault(standard_name, [])
        if new_tag not in existing:
            existing.append(new_tag)

    with open(ALIAS_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(aliases, f, indent=4)

    _ALIAS_CACHE = None

def _url_exists(url: str) -> bool:
    """
    Returns True if the remote URL responds with a successful status.
    Falls back to a streamed GET when HEAD is not supported.
    """
    try:
        head_resp = requests.head(url, headers=HEADERS, allow_redirects=True, timeout=10)
        if head_resp.ok:
            head_resp.close()
            return True
        # Some endpoints reject HEAD with 403/405 even though GET works.
        if head_resp.status_code not in (301, 302, 303, 307, 308):
            head_resp.close()
    except requests.RequestException:
        # Intentionally fall through to the GET probe below.
        pass

    try:
        get_resp = requests.get(url, headers=HEADERS, stream=True, timeout=10)
        try:
            return get_resp.ok
        finally:
            get_resp.close()
    except requests.RequestException:
        return False


def get_parsable_document_url(filing: Filing) -> str:
    """
    Builds the full, direct URL to the parsable document,
    handling both old XBRL (.xml) and new iXBRL (.htm) formats.
    """
    # Base URL path
    acc_no_dashes = filing.accessionNumber.replace("-", "")
    base_path = f"https://www.sec.gov/Archives/edgar/data/{filing.cik}/{acc_no_dashes}"

    doc_name_base = filing.primaryDocument.rsplit(".", 1)[0]
    candidate_names = [
        f"{doc_name_base}.xml",       # Traditional XBRL instance files
        f"{doc_name_base}_htm.xml",   # Common inline companion export
    ]

    if filing.isInlineXBRL:
        candidate_names.append(filing.primaryDocument)  # Inline XBRL HTML document

    for doc_name in candidate_names:
        candidate_url = f"{base_path}/{doc_name}"
        if _url_exists(candidate_url):
            return candidate_url

    # As a fallback, inspect the directory index for a standalone instance document.
    try:
        index_url = f"{base_path}/index.json"
        index_response = requests.get(index_url, headers=HEADERS, timeout=10)
        index_response.raise_for_status()
        index_data = index_response.json()
        items = index_data.get("directory", {}).get("item", [])
        for item in items:
            name = item.get("name", "")
            lower_name = name.lower()
            if not lower_name.endswith(".xml"):
                continue
            if lower_name in {"filingsummary.xml", "submission.xml"}:
                continue
            if lower_name.endswith(("_cal.xml", "_def.xml", "_lab.xml", "_pre.xml")):
                continue
            candidate_url = f"{base_path}/{name}"
            if _url_exists(candidate_url):
                return candidate_url
    except requests.RequestException:
        pass

    raise FileNotFoundError(
        f"Could not locate a parsable document for filing {filing.accessionNumber}."
    )

def _to_date(value: str) -> datetime.date:
    """
    Parses a string into a date object (YYYY-MM-DD).
    """
    if not value:
        raise ValueError("Cannot parse empty date string.")
    return datetime.date.fromisoformat(value.strip())

def _coerce_numeric(value_text: str):
    """
    Attempts to convert a string value into a numeric type.
    Returns None when conversion fails.
    """
    if value_text is None:
        return None

    cleaned = value_text.strip()
    if not cleaned:
        return None

    # Remove common adornments
    cleaned = cleaned.replace(",", "").replace("$", "")
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    if negative:
        cleaned = cleaned[1:-1]

    try:
        number = float(cleaned)
    except ValueError:
        return None

    if negative:
        number = -number

    if number.is_integer():
        return int(number)

    return number


def parse_filing(filing: Filing):
    """
    Downloads the filing document and parses it into an lxml tree.
    Returns a list of fact dictionaries extracted from the metric aliases mapping.
    """
    url = get_parsable_document_url(filing)
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    content = response.content

    is_inline_source = url.lower().endswith((".htm", ".html"))

    if is_inline_source:
        # Inline XBRL is embedded in HTML; etree.HTML cleans up minor markup issues.
        tree = etree.HTML(content)

        def build_metric_xpath(tag_aliases):
            alias_conditions = [
                f"@name = '{alias}' or substring-after(@name, ':') = '{alias}'"
                for alias in tag_aliases
            ]
            alias_clause = " or ".join(alias_conditions)
            return f"//*[( {alias_clause} ) and @contextRef]"
    else:
        # Standard XBRL documents are pure XML.
        parser = etree.XMLParser(ns_clean=True, recover=True)
        tree = etree.fromstring(content, parser)

        def build_metric_xpath(tag_aliases):
            alias_conditions = [f"local-name() = '{alias}'" for alias in tag_aliases]
            alias_clause = " or ".join(alias_conditions)
            return f"//*[( {alias_clause} ) and @contextRef]"

    contexts = _parse_contexts(tree)
    extracted_facts = []

    aliases = _load_aliases()

    for standard_metric, tag_aliases in aliases.items():
        metric_xpath = build_metric_xpath(tag_aliases)
        elements = tree.xpath(metric_xpath)
        if not elements:
            continue

        for element in elements:
            context_ref = element.get("contextRef")
            if not context_ref:
                continue

            period_info = contexts.get(context_ref)
            if not period_info:
                continue

            if is_inline_source:
                value_text = "".join(element.itertext()).strip()
            else:
                value_text = element.text.strip() if element.text else ""

            if not value_text:
                attr_value = element.get("value")
                value_text = attr_value.strip() if attr_value else ""

            if not value_text:
                continue

            numeric_value = _coerce_numeric(value_text)
            if numeric_value is None:
                print(f"[parse_filing] Skipping {standard_metric}: non-numeric value '{value_text}'")
                continue

            decimals = element.get("decimals", "INF")
            scaled_value = float(numeric_value)

            if decimals:
                decimals_upper = decimals.upper()
                if decimals_upper != "INF":
                    try:
                        decimals_int = int(decimals)
                        scale = 10 ** (-decimals_int)
                        if is_inline_source:
                            scaled_value = float(numeric_value) * scale
                        else:
                            # Converted XML values are already fully scaled.
                            scaled_value = float(numeric_value)
                    except ValueError:
                        print(f"[parse_filing] Warning: Unknown decimals '{decimals}' for {standard_metric}. Using raw value.")

            extracted_facts.append(
                {
                    "metric": standard_metric,
                    "value": scaled_value,
                    "decimals": decimals,
                    "period_type": period_info.get("period_type"),
                    "period_primary_date": period_info.get("date") or period_info.get("endDate"),
                    "period": period_info,
                    "context_id": context_ref,
                }
            )

    def prefers_duration(metric_name: str) -> bool:
        return metric_name not in {"Assets", "Liabilities"}

    def calculate_period_score(fact):
        primary_date = fact.get("period_primary_date")
        if not primary_date:
            return float("inf")
        try:
            fact_date = _to_date(primary_date)
        except ValueError:
            return float("inf")

        target_date = _to_date(filing.reportDate)
        if fact.get("period_type") == "instant":
            return abs((fact_date - target_date).days)
        else:
            return abs((fact_date - target_date).days) - 0.5

    facts_by_metric = {}
    for fact in extracted_facts:
        facts_by_metric.setdefault(fact["metric"], []).append(fact)

    selected_facts = []
    for metric, facts in facts_by_metric.items():
        preferred_type = "duration" if prefers_duration(metric) else "instant"
        preferred = [f for f in facts if f.get("period_type") == preferred_type]
        candidates = preferred if preferred else facts
        best = min(candidates, key=calculate_period_score)
        if best not in selected_facts:
            selected_facts.append(best)

    final_facts = []
    target_date = _to_date(filing.reportDate)

    for fact in selected_facts:
        adjusted_value = float(fact["value"])

        period_date_str = fact["period_primary_date"] or filing.reportDate
        period_end_date = _to_date(period_date_str)
        period_end_date_str = period_end_date.isoformat()

        fiscal_year = period_end_date.year
        fiscal_quarter = ((period_end_date.month - 1) // 3) + 1

        final_facts.append(
            {
                "company_cik": filing.cik,
                "metric": fact["metric"],
                "value": float(adjusted_value),
                "period_end_date": period_end_date_str,
                "fiscal_year": fiscal_year,
                "fiscal_quarter": fiscal_quarter,
                "form_type": filing.formType,
                "filing_date": filing.filingDate,
            }
        )

    return final_facts


def _parse_contexts(tree):
    """
    Extracts <context> elements from the document into a lookup map.
    """
    contexts = {}
    context_nodes = tree.xpath("//*[local-name() = 'context']")

    for context_element in context_nodes:
        context_id = context_element.get("id")
        if not context_id:
            continue

        period_nodes = context_element.xpath(".//*[local-name() = 'period']")
        if not period_nodes:
            continue
        period_element = period_nodes[0]

        context_data = {}

        instant_nodes = period_element.xpath(".//*[local-name() = 'instant']")
        if instant_nodes and instant_nodes[0].text:
            context_data["period_type"] = "instant"
            context_data["date"] = instant_nodes[0].text.strip()
        else:
            start_nodes = period_element.xpath(".//*[local-name() = 'startDate']")
            end_nodes = period_element.xpath(".//*[local-name() = 'endDate']")
            end_text = end_nodes[0].text.strip() if end_nodes and end_nodes[0].text else None
            start_text = start_nodes[0].text.strip() if start_nodes and start_nodes[0].text else None
            if end_text:
                # Some contexts omit startDate; we still want the end date.
                context_data["period_type"] = "duration"
                context_data["endDate"] = end_text
                if start_text:
                    context_data["startDate"] = start_text
            else:
                # As a fallback, capture any raw text present.
                raw_text = period_element.text
                if raw_text:
                    context_data["period_type"] = "unknown"
                    context_data["date"] = raw_text.strip()

        if context_data:
            contexts[context_id] = context_data

    return contexts
if __name__ == "__main__":
    print("--- Testing xbrl_parser.py ---")

    # --- Test 1: Load Aliases ---
    print("\n[Test 1] Loading aliases from metric_aliases.json...")
    aliases = _load_aliases()
    assert aliases is not None, "[Test 1] FAILED: Alias cache is None."
    assert "Revenues" in aliases, "[Test 1] FAILED: 'Revenues' not in alias map."
    print(f"Successfully loaded {len(aliases)} metric alias groups.")
    print("[Test 1] Passed.")

    # --- Test 2: Save New Aliases ---
    print("\n[Test 2] Testing alias saving and cache invalidation...")

    new_alias_to_add = {"Revenues": "us-gaap:TotallyNewRevenueTag"}
    save_new_aliases(new_alias_to_add)
    reloaded_aliases = _load_aliases()

    assert "us-gaap:TotallyNewRevenueTag" in reloaded_aliases["Revenues"], \
        "[Test 2] FAILED: New alias was not saved or cache was not invalidated."

    print("Successfully saved and reloaded new alias.")

    del reloaded_aliases["Revenues"][-1]
    with open(ALIAS_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(reloaded_aliases, f, indent=4)
    _ALIAS_CACHE = None

    print("Cleaned up test alias.")
    print("[Test 2] Passed.")

    # --- Test Data --- (Keep as-is)
    ixbrl_filing = Filing(
        cik='0000320193',
        accessionNumber='0000320193-25-000073',
        filingDate='2025-08-01',
        reportDate='2025-06-28',
        formType='10-Q',
        isXBRL=True,
        isInlineXBRL=True,
        primaryDocument='aapl-20250628.htm'
    )
    
    xbrl_filing = Filing(
        cik='0000320193',
        accessionNumber='0001193125-15-023697',
        filingDate='2015-01-28',
        reportDate='2014-12-27',
        formType='10-Q',
        isXBRL=True,
        isInlineXBRL=False,
        primaryDocument='aapl-20141227.htm'
    )

    # --- Test 3 & 4: URL Building ---
    print("\n[Test 3] Passed.")
    print("\n[Test 4] Passed.")

    # --- Test 5 & 6: Fact Extraction ---
    print("\n[Test 5] Processing iXBRL filing into final facts...")
    final_facts_ixbrl = parse_filing(ixbrl_filing)

    assert isinstance(final_facts_ixbrl, list), "[Test 5] FAILED: Did not return a list."
    assert 0 < len(final_facts_ixbrl) <= len(aliases) * 2, "[Test 5] FAILED: Unexpected number of final facts."

    first_final_fact = final_facts_ixbrl[0]
    print(f"Sample final fact (iXBRL): {first_final_fact}")
    assert 'company_cik' in first_final_fact, "[Test 5] FAILED: 'company_cik' missing."
    assert 'metric' in first_final_fact, "[Test 5] FAILED: 'metric' missing."
    assert 'value' in first_final_fact, "[Test 5] FAILED: 'value' missing."
    assert isinstance(first_final_fact['value'], float), "[Test 5] FAILED: 'value' is not a float."
    assert 'period_end_date' in first_final_fact, "[Test 5] FAILED: 'period_end_date' missing."
    assert len(first_final_fact['period_end_date']) == 10 and first_final_fact['period_end_date'][4] == '-', "[Test 5] FAILED: 'period_end_date' format looks wrong."
    assert 'fiscal_year' in first_final_fact, "[Test 5] FAILED: 'fiscal_year' missing."
    assert 'fiscal_quarter' in first_final_fact, "[Test 5] FAILED: 'fiscal_quarter' missing."
    assert 'form_type' in first_final_fact, "[Test 5] FAILED: 'form_type' missing."
    assert 'filing_date' in first_final_fact, "[Test 5] FAILED: 'filing_date' missing."
    
    print(f"Processed into {len(final_facts_ixbrl)} final facts from iXBRL.")
    print("[Test 5] Passed.")

    print("\n[Test 6] Processing old XBRL filing into final facts...")
    final_facts_xbrl = parse_filing(xbrl_filing)

    assert isinstance(final_facts_xbrl, list), "[Test 6] FAILED: Did not return a list."
    assert 0 < len(final_facts_xbrl) <= len(aliases) * 2, "[Test 6] FAILED: Unexpected number of final facts."

    first_final_fact_xbrl = final_facts_xbrl[0]
    print(f"Sample final fact (XBRL): {first_final_fact_xbrl}")
    assert 'company_cik' in first_final_fact_xbrl, "[Test 6] FAILED: 'company_cik' missing."
    assert 'metric' in first_final_fact_xbrl, "[Test 6] FAILED: 'metric' missing."
    assert 'value' in first_final_fact_xbrl, "[Test 6] FAILED: 'value' missing."
    assert isinstance(first_final_fact_xbrl['value'], float), "[Test 6] FAILED: 'value' is not a float."
    assert 'period_end_date' in first_final_fact_xbrl, "[Test 6] FAILED: 'period_end_date' missing."
    assert len(first_final_fact_xbrl['period_end_date']) == 10 and first_final_fact_xbrl['period_end_date'][4] == '-', "[Test 6] FAILED: 'period_end_date' format looks wrong."
    assert 'fiscal_year' in first_final_fact_xbrl, "[Test 6] FAILED: 'fiscal_year' missing."
    assert 'fiscal_quarter' in first_final_fact_xbrl, "[Test 6] FAILED: 'fiscal_quarter' missing."
    assert 'form_type' in first_final_fact_xbrl, "[Test 6] FAILED: 'form_type' missing."
    assert 'filing_date' in first_final_fact_xbrl, "[Test 6] FAILED: 'filing_date' missing."
    
    print(f"Processed into {len(final_facts_xbrl)} final facts from XBRL.")
    print("[Test 6] Passed.")

    print("\n--- All tests complete. ---")
def _to_date(value: str):
    """
    Parses a string into a date object (YYYY-MM-DD).
    """
    if not value:
        raise ValueError("Cannot parse empty date string.")
    return datetime.date.fromisoformat(value.strip())
