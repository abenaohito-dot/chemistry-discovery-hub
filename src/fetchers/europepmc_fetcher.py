"""
Europe PMC Fetcher — Broader coverage than NCBI PubMed.
Includes European journals, citation data, and OA full-text links.
"""
from __future__ import annotations

from typing import Any

import requests

EUROPE_PMC_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


class EuropePMCFetcher:
    """Fetch paper metadata from Europe PMC REST API."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "ChemistryDiscoveryHub/1.0"})

    def search(
        self,
        query: str,
        max_results: int = 20,
        open_access_only: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Search Europe PMC.

        Args:
            query:            Query string (supports Boolean operators).
            max_results:      Maximum results to return.
            open_access_only: If True, restrict to Open Access articles.
        Returns:
            List of paper dicts.
        """
        q = query
        if open_access_only:
            q += " OPEN_ACCESS:y"

        params: dict[str, Any] = {
            "query":      q,
            "format":     "json",
            "pageSize":   min(max_results, 100),
            "resultType": "core",
            "sort":       "RELEVANCE",
        }

        try:
            resp = self.session.get(EUROPE_PMC_URL, params=params, timeout=20)
            resp.raise_for_status()
            results = resp.json().get("resultList", {}).get("result", [])
            return [self._parse_result(r) for r in results]
        except Exception as exc:
            print(f"[EuropePMC] search error: {exc}")
            return []

    # ── Private helpers ──────────────────────────────────────────────────────

    def _parse_result(self, r: dict) -> dict[str, Any]:
        # Authors
        authors: list[str] = []
        for auth in r.get("authorList", {}).get("author", []):
            full = auth.get("fullName", "")
            if full:
                authors.append(full)

        # Keywords
        keywords: list[str] = []
        for kw in r.get("keywordList", {}).get("keyword", []):
            if isinstance(kw, str):
                keywords.append(kw)

        # Full-text URL (OA articles)
        fulltext_url = ""
        for url_info in r.get("fullTextUrlList", {}).get("fullTextUrl", []):
            if url_info.get("documentStyle") == "html":
                fulltext_url = url_info.get("url", "")
                break

        # Citation count
        citations = r.get("citedByCount", 0)

        doi  = r.get("doi", "")
        pmid = r.get("pmid", "")

        return {
            "title":        r.get("title", "No title"),
            "authors":      authors,
            "doi":          doi,
            "pmid":         pmid,
            "abstract":     r.get("abstractText", ""),
            "journal":      r.get("journalTitle", ""),
            "year":         str(r.get("pubYear", "")),
            "keywords":     keywords,
            "citations":    citations,
            "fulltext_url": fulltext_url,
            "source":       "EuropePMC",
        }
