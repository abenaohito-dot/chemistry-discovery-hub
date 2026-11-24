"""
Europe PMC Fetcher — Broader coverage than NCBI PubMed.
Includes European journals, citation data, and OA full-text links.
"""
from __future__ import annotations

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

EUROPE_PMC_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


class EuropePMCFetcher:
    """Fetch paper metadata from Europe PMC REST API."""

    def __init__(self, cache: SQLiteCache | None = None):
        self.cache = cache
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "ChemistryDiscoveryHub/2.0"})

    def search(
        self,
        query: str,
        max_results: int = 20,
        open_access_only: bool = False,
    ) -> QueryResult:
        """Search Europe PMC and return a QueryResult."""
        q = query.strip()
        if not q:
            return QueryResult(source="EuropePMC", status="empty")

        limit = max(1, min(int(max_results), 100))
        key = make_cache_key("epmc", q, limit, int(open_access_only))

        def _fetch() -> QueryResult:
            full_q = f"{q} OPEN_ACCESS:y" if open_access_only else q
            params: dict[str, Any] = {
                "query": full_q,
                "format": "json",
                "pageSize": limit,
                "resultType": "core",
                "sort": "RELEVANCE",
            }
            try:
                resp = self.session.get(EUROPE_PMC_URL, params=params, timeout=20)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                return classify_request_error("EuropePMC", exc)

            total = int(data.get("hitCount") or 0)
            results = data.get("resultList", {}).get("result", [])
            papers = [self._parse_result(r) for r in results]
            if not papers:
                return QueryResult(source="EuropePMC", status="empty", total_count=0)

            truncated = total > len(papers)
            status = "truncated" if truncated else "ok"
            msg = f"{len(papers)} / {total} 件表示" if truncated else f"{len(papers)} 件"
            return QueryResult(
                source="EuropePMC",
                status=status,
                items=papers,
                total_count=total,
                truncated=truncated,
                message=msg,
            )

        return cached_query(self.cache, key, TTL_LITERATURE_SECONDS, _fetch)

    def _parse_result(self, r: dict[str, Any]) -> dict[str, Any]:
        authors: list[str] = []
        for auth in (r.get("authorList") or {}).get("author", []):
            full = auth.get("fullName", "")
            if full:
                authors.append(full)

        keywords: list[str] = []
        for kw in (r.get("keywordList") or {}).get("keyword", []):
            if isinstance(kw, str):
                keywords.append(kw)

        fulltext_url = ""
        for url_info in (r.get("fullTextUrlList") or {}).get("fullTextUrl", []):
            if url_info.get("documentStyle") == "html":
                fulltext_url = url_info.get("url", "")
                break

        return {
            "title": r.get("title", "No title"),
            "authors": authors,
            "doi": normalize_doi(r.get("doi", "")),
            "pmid": r.get("pmid", ""),
            "abstract": r.get("abstractText", ""),
            "journal": r.get("journalTitle", ""),
            "year": str(r.get("pubYear", "")),
            "keywords": keywords,
            "citations": r.get("citedByCount", 0),
            "fulltext_url": fulltext_url,
            "source": "EuropePMC",
        }
