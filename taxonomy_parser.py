import re
import requests
from lxml import etree
from urllib.parse import urljoin
from edgar_downloader import Filing, HEADERS


def _get_taxonomy_file_urls(filing: Filing) -> dict:
    """
    Locate the label and presentation taxonomy files for a filing via its index page.
    """
    accession_with_dashes = filing.accessionNumber
    accession_no_dashes = accession_with_dashes.replace("-", "")
    index_url = (
        f"https://www.sec.gov/Archives/edgar/data/"
        f"{filing.cik}/{accession_no_dashes}/{accession_with_dashes}-index.htm"
    )

    response = requests.get(index_url, headers=HEADERS)
    response.raise_for_status()

    tree = etree.HTML(response.content)

    taxonomy_urls = {}
    base_archive_path = f"https://www.sec.gov/Archives/edgar/data/{filing.cik}/{accession_no_dashes}/"
    link_elements = tree.xpath("//a[contains(@href, '.xml')]")

    for link in link_elements:
        href = link.get("href")
        if not href:
            continue

        href = href.strip()
        if not href:
            continue

        full_url = urljoin(index_url, href)
        filename = full_url.split("/")[-1]
        if href.lower().endswith("_lab.xml"):
            taxonomy_urls["label_url"] = base_archive_path + filename
        elif href.lower().endswith("_pre.xml"):
            taxonomy_urls["presentation_url"] = base_archive_path + filename

    return taxonomy_urls


def _build_label_map(label_file_url: str) -> dict:
    """
    Download the label taxonomy file and build a map from tag names to human-readable labels.
    """
    response = requests.get(label_file_url, headers=HEADERS)
    response.raise_for_status()

    parser = etree.XMLParser(ns_clean=True, recover=True)
    tree = etree.fromstring(response.content, parser)

    label_map = {}
    label_elements = tree.xpath("//*[local-name() = 'label']")

    xlink_label_attr = "{http://www.w3.org/1999/xlink}label"

    for element in label_elements:
        tag_name = element.get(xlink_label_attr)
        if not tag_name:
            continue

        label_text = (element.text or "").strip()
        if not label_text:
            continue

        normalized_name = tag_name
        if normalized_name.lower().endswith("_lbl"):
            normalized_name = normalized_name[:-4]

        if normalized_name not in label_map:
            label_map[normalized_name] = label_text

    return label_map


def _find_missing_aliases(presentation_url: str, label_map: dict, missing_metrics: list[str]) -> dict:
    """
    Inspect the presentation taxonomy to map human-readable labels to their tag names for given metrics.
    """
    response = requests.get(presentation_url, headers=HEADERS)
    response.raise_for_status()

    parser = etree.XMLParser(ns_clean=True, recover=True)
    tree = etree.fromstring(response.content, parser)

    new_aliases_found = {}
    alias_scores = {}

    loc_elements = tree.xpath("//*[local-name() = 'loc']")
    xlink_label_attr = "{http://www.w3.org/1999/xlink}label"

    for loc_element in loc_elements:
        tag_name = loc_element.get(xlink_label_attr)
        if not tag_name:
            continue

        normalized_tag = tag_name
        if normalized_tag.lower().endswith("_loc"):
            normalized_tag = normalized_tag[:-4]

        human_label = label_map.get(normalized_tag)
        if not human_label:
            continue

        label_lower = human_label.lower()

        for standard_name in missing_metrics:
            standard_lower = standard_name.lower()
            score = _score_label_match(standard_lower, label_lower)
            if score is None:
                continue

            current_best = alias_scores.get(standard_name)
            if current_best is None or score < current_best:
                alias_scores[standard_name] = score
                new_aliases_found[standard_name] = normalized_tag

    return new_aliases_found


def _score_label_match(standard_lower: str, label_lower: str):
    """
    Determine how well a label matches a standard metric name.
    Lower scores are better. Returns None when there is no reasonable match.
    """
    if label_lower == standard_lower:
        base_score = 0
    elif re.search(rf"\b{re.escape(standard_lower)}\b", label_lower):
        base_score = 1
    elif standard_lower.endswith("s") and re.search(rf"\b{re.escape(standard_lower[:-1])}\b", label_lower):
        base_score = 2
    elif standard_lower.endswith("es") and re.search(rf"\b{re.escape(standard_lower[:-2])}\b", label_lower):
        base_score = 2
    else:
        return None

    penalty = 0
    if any(term in label_lower for term in ("schedule", "table", "text block", "details")):
        penalty += 2

    return (base_score + penalty, len(label_lower))


def discover_aliases(filing: Filing, missing_metrics: list[str]) -> dict:
    """
    Skeleton entry point for the Librarian module; will discover metric aliases for missing metrics.
    """
    taxonomy_urls = _get_taxonomy_file_urls(filing)

    label_url = taxonomy_urls.get("label_url")
    presentation_url = taxonomy_urls.get("presentation_url")

    if not label_url or not presentation_url:
        print("[discover_aliases] Warning: Missing taxonomy URLs; cannot discover aliases.")
        return {}

    label_map = _build_label_map(label_url)
    new_aliases = _find_missing_aliases(presentation_url, label_map, missing_metrics)

    return new_aliases


if __name__ == "__main__":
    print("--- Testing taxonomy_parser.py ---")
    
    # --- Test Data ---
    test_filing = Filing(
        cik='0000320193',
        accessionNumber='0001193125-15-023697',
        filingDate='2015-01-28',
        reportDate='2014-12-27',
        formType='10-Q',
        isXBRL=True,
        isInlineXBRL=False,
        primaryDocument='aapl-20141227.htm'
    )
    
    missing_metrics_list = ["Revenues", "Assets", "Liabilities"]

    # --- Final Test: Full Librarian Workflow ---
    print("\n[Test 1] Calling discover_aliases main function...")
    
    new_aliases = discover_aliases(test_filing, missing_metrics_list)
    
    assert new_aliases, "[Test 1] FAILED: No aliases were discovered."
    assert "Revenues" in new_aliases, "[Test 1] FAILED: Did not discover 'Revenues'."
    
    print("Librarian successfully discovered aliases:")
    print(new_aliases)
    
    assert new_aliases['Revenues'] == 'us-gaap_SalesRevenueNet', "[Test 1] FAILED: Wrong tag for Revenues."
    
    print("[Test 1] Passed.")
    print("\n--- All tests complete. ---")
