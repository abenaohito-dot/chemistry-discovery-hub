"""
CrossRef Fetcher — Unified access to ACS, Wiley, Elsevier, RSC, Springer journals.
Uses the CrossRef REST API (free, no auth required).
"""
from __future__ import annotations

import os
import re
from typing import Any

import requests

from src.utils.cache import SQLiteCache, TTL_LITERATURE_SECONDS
from src.utils.common import (
    QueryResult,
    cached_query,
    classify_request_error,
    make_cache_key,
    normalize_doi,
)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

CROSSREF_URL = "https://api.crossref.org/works"
CROSSREF_EMAIL = os.getenv("CROSSREF_EMAIL", "")

# Common natural product journal ISSNs for targeted search
NATURAL_PRODUCT_JOURNALS: dict[str, str] = {
    "Journal of Natural Products": "1520-6025",
    "Journal of Medicinal Chemistry": "1520-4804",
    "ACS Chemical Biology": "1554-8937",
    "Natural Product Reports": "1460-4752",
    "Phytochemistry": "0031-9422",
    "Phytomedicine": "1618-095X",
    "Fitoterapia": "1873-6971",
    "Journal of Ethnopharmacology": "1872-7573",
    "Phytochemistry Letters": "1874-3900",
    "Natural Product Research": "1478-6427",
    "Planta Medica": "1439-0221",
    "Molecules": "1420-3049",
    "Marine Drugs": "1660-3397",
    "European Journal of Medicinal Chemistry": "1768-3254",
    "Bioorganic & Medicinal Chemistry": "1464-3391",
    "Bioorganic & Medicinal Chemistry Letters": "1464-3405",
    "Journal of Agricultural and Food Chemistry": "1520-5118",
}


class CrossRefFetcher:
    """Fetch paper metadata via CrossRef REST API."""

    def __init__(self, cache: SQLiteCache | None = None):
        self.cache = cache
        self.session = requests.Session()
        ua = "ChemistryDiscoveryHub/2.0"
        if CROSSREF_EMAIL:
            ua += f" (mailto:{CROSSREF_EMAIL})"
        self.session.headers.update({"User-Agent": ua})

    def search(
        self,
        query: str,
        max_results: int = 20,
        journal_filter: str | None = None,
    ) -> QueryResult:
        """Search CrossRef works and return a QueryResult."""
        q = query.strip()
        if not q:
            return QueryResult(source="CrossRef", status="empty")

        limit = max(1, min(int(max_results), 50))
        key = make_cache_key("crossref", q, limit, journal_filter or "")

        def _fetch() -> QueryResult:
            params: dict[str, Any] = {
                "query": q,
                "rows": limit,
                "sort": "relevance",
                "select": "DOI,title,author,abstract,container-title,published,is-referenced-by-count,subject",
            }
            if journal_filter:
                issn = NATURAL_PRODUCT_JOURNALS.get(journal_filter)
                if issn:
                    params["filter"] = f"issn:{issn}"

            try:
                resp = self.session.get(CROSSREF_URL, params=params, timeout=20)
                resp.raise_for_status()
                msg_body = resp.json().get("message", {})
            except Exception as exc:
                return classify_request_error("CrossRef", exc)

            total = int(msg_body.get("total-results") or 0)
            items = msg_body.get("items", [])
            papers = [self._parse_item(item) for item in items]
            if not papers:
                return QueryResult(source="CrossRef", status="empty", total_count=0)

            truncated = total > len(papers)
            status = "truncated" if truncated else "ok"
            msg = f"{len(papers)} / {total} 件表示" if truncated else f"{len(papers)} 件"
            return QueryResult(
                source="CrossRef",
                status=status,
                items=papers,
                total_count=total,
                truncated=truncated,
                message=msg,
            )

        return cached_query(self.cache, key, TTL_LITERATURE_SECONDS, _fetch)

    def get_available_journals(self) -> list[str]:
        """Return list of pre-configured journal names."""
        return list(NATURAL_PRODUCT_JOURNALS.keys())

    def _parse_item(self, item: dict[str, Any]) -> dict[str, Any]:
        title_list = item.get("title", [])
        title = title_list[0] if title_list else "No title"

        authors: list[str] = []
        for auth in item.get("author", []):
            family = auth.get("family", "")
            given = auth.get("given", "")
            if family:
                initials = " ".join(w[0] for w in given.split() if w) if given else ""
                authors.append(f"{family} {initials}".strip())

        container = item.get("container-title", [])
        journal = container[0] if container else ""

        pub = item.get("published", {})
        date_parts = pub.get("date-parts", [[""]])
        year = str(date_parts[0][0]) if date_parts and date_parts[0] else ""

        abstract = item.get("abstract", "")
        if abstract:
            abstract = re.sub(r"<[^>]+>", " ", abstract).strip()

        return {
            "title": title,
            "authors": authors,
            "doi": normalize_doi(item.get("DOI", "")),
            "pmid": "",
            "abstract": abstract,
            "journal": journal,
            "year": year,
            "keywords": item.get("subject", []),
            "citations": item.get("is-referenced-by-count", 0),
            "source": "CrossRef",
        }
