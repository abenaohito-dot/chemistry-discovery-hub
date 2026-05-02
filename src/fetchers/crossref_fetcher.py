"""
CrossRef Fetcher — Unified access to ACS, Wiley, Elsevier, RSC, Springer journals.
Uses the CrossRef REST API (free, no auth required).
"""
from __future__ import annotations

import os
import time
from typing import Any

import requests
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

CROSSREF_URL   = "https://api.crossref.org/works"
CROSSREF_EMAIL = os.getenv("CROSSREF_EMAIL", "")

# Common natural product journal ISSNs for targeted search
NATURAL_PRODUCT_JOURNALS: dict[str, str] = {
    "Journal of Natural Products":          "1520-6025",
    "Journal of Medicinal Chemistry":       "1520-4804",
    "ACS Chemical Biology":                 "1554-8937",
    "Natural Product Reports":              "1460-4752",
    "Phytochemistry":                       "0031-9422",
    "Phytomedicine":                        "1618-095X",
    "Fitoterapia":                          "1873-6971",
    "Journal of Ethnopharmacology":         "1872-7573",
    "Phytochemistry Letters":               "1874-3900",
    "Natural Product Research":             "1478-6427",
    "Planta Medica":                        "1439-0221",
    "Molecules":                            "1420-3049",
    "Marine Drugs":                         "1660-3397",
    "European Journal of Medicinal Chemistry": "1768-3254",
    "Bioorganic & Medicinal Chemistry":     "1464-3391",
    "Bioorganic & Medicinal Chemistry Letters": "1464-3405",
    "Journal of Agricultural and Food Chemistry": "1520-5118",
}


class CrossRefFetcher:
    """Fetch paper metadata via CrossRef REST API."""

    def __init__(self):
        self.session = requests.Session()
        ua = "ChemistryDiscoveryHub/1.0"
        if CROSSREF_EMAIL:
            ua += f" (mailto:{CROSSREF_EMAIL})"
        self.session.headers.update({"User-Agent": ua})

    def search(
        self,
        query: str,
        max_results: int = 20,
        journal_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Search CrossRef for papers.

        Args:
            query:          Full-text query string.
            max_results:    Max number of results.
            journal_filter: Optional journal name from NATURAL_PRODUCT_JOURNALS
                            to restrict the search.
        Returns:
            List of paper dicts.
        """
        params: dict[str, Any] = {
            "query":  query,
            "rows":   min(max_results, 50),
            "sort":   "relevance",
            "select": "DOI,title,author,abstract,container-title,published,is-referenced-by-count,subject",
        }

        if journal_filter:
            issn = NATURAL_PRODUCT_JOURNALS.get(journal_filter)
            if issn:
                params["filter"] = f"issn:{issn}"

        try:
            resp = self.session.get(CROSSREF_URL, params=params, timeout=20)
            resp.raise_for_status()
            items = resp.json().get("message", {}).get("items", [])
            return [self._parse_item(item) for item in items]
        except Exception as exc:
            print(f"[CrossRef] search error: {exc}")
            return []

    def search_journal(
        self,
        query: str,
        journal_name: str,
        max_results: int = 10,
    ) -> list[dict[str, Any]]:
        """Convenience method: search within a specific journal by name."""
        return self.search(query, max_results=max_results, journal_filter=journal_name)

    def get_available_journals(self) -> list[str]:
        """Return list of pre-configured journal names."""
        return list(NATURAL_PRODUCT_JOURNALS.keys())

    # ── Private helpers ──────────────────────────────────────────────────────

    def _parse_item(self, item: dict) -> dict[str, Any]:
        # Title
        title_list = item.get("title", [])
        title = title_list[0] if title_list else "No title"

        # Authors
        authors: list[str] = []
        for auth in item.get("author", []):
            family = auth.get("family", "")
            given  = auth.get("given", "")
            if family:
                initials = " ".join(w[0] for w in given.split() if w) if given else ""
                authors.append(f"{family} {initials}".strip())

        # Journal
        container = item.get("container-title", [])
        journal   = container[0] if container else ""

        # Year
        pub = item.get("published", {})
        date_parts = pub.get("date-parts", [[""]])
        year = str(date_parts[0][0]) if date_parts and date_parts[0] else ""

        # DOI
        doi = item.get("DOI", "")

        # Abstract (often missing in CrossRef)
        abstract = item.get("abstract", "")
        if abstract:
            # Strip JATS XML tags if present
            import re
            abstract = re.sub(r"<[^>]+>", " ", abstract).strip()

        # Keywords / subjects
        keywords = item.get("subject", [])

        # Citation count
        citations = item.get("is-referenced-by-count", 0)

        return {
            "title":     title,
            "authors":   authors,
            "doi":       doi,
            "pmid":      "",
            "abstract":  abstract,
            "journal":   journal,
            "year":      year,
            "keywords":  keywords,
            "citations": citations,
            "source":    "CrossRef",
        }
