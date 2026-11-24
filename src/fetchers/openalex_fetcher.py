"""OpenAlex Fetcher — Scholarly literature metadata via OpenAlex REST API."""
from __future__ import annotations

from typing import Any

import requests

from src.utils.cache import SQLiteCache, TTL_LITERATURE_SECONDS
from src.utils.common import (
    QueryResult,
    cached_query,
    classify_request_error,
    get_config_value,
    make_cache_key,
    normalize_doi,
)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

OPENALEX_URL = "https://api.openalex.org/works"
_SELECT_FIELDS = (
    "doi,ids,title,authorships,abstract_inverted_index,"
    "primary_location,publication_year,cited_by_count,topics"
)


def _reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str:
    """Reconstruct plain abstract text from OpenAlex inverted index."""
    if not inverted_index or not isinstance(inverted_index, dict):
        return ""
    pairs: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        if isinstance(positions, list):
            for pos in positions:
                pairs.append((pos, word))
    if not pairs:
        return ""
    pairs.sort(key=lambda x: x[0])
    return " ".join(w for _, w in pairs)


class OpenAlexFetcher:
    """Fetch literature metadata from OpenAlex REST API."""

    def __init__(self, cache: SQLiteCache | None = None):
        self.cache = cache
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "ChemistryDiscoveryHub/2.0"})

    def search(
        self,
        query: str,
        max_results: int = 20,
        title_abstract_only: bool = False,
    ) -> QueryResult:
        """Search OpenAlex works with optional title/abstract restriction."""
        q = query.strip()
        if not q:
            return QueryResult(source="OpenAlex", status="empty")

        limit = max(1, min(int(max_results), 100))
        key = make_cache_key("openalex", q, limit, int(title_abstract_only))

        def _fetch() -> QueryResult:
            api_key = get_config_value("OPENALEX_API_KEY")
            params: dict[str, Any] = {
                "per-page": limit,
                "select": _SELECT_FIELDS,
            }
            if title_abstract_only:
                # OpenAlex filter search rejects boolean OR/parens if mixed naively, so use clean search + filter or search param
                params["filter"] = f"title_and_abstract.search:{q}"
            else:
                params["search"] = q

            if api_key:
                params["api_key"] = api_key

            try:
                resp = self.session.get(OPENALEX_URL, params=params, timeout=20)
                if resp.status_code == 429:
                    return QueryResult(
                        source="OpenAlex",
                        status="rate_limited",
                        message="OpenAlex: レート制限 (HTTP 429) — 時間をおいて再試行するか、管理者設定の API キーを確認してください",
                    )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                return classify_request_error(
                    "OpenAlex", exc, hint="時間をおいて再試行するか、管理者設定の API キーを確認してください"
                )

            total = int((data.get("meta") or {}).get("count") or 0)
            results = data.get("results") or []
            papers = [self._parse_work(w) for w in results]
            if not papers:
                return QueryResult(source="OpenAlex", status="empty", total_count=0)

            truncated = total > len(papers)
            status = "truncated" if truncated else "ok"
            msg = f"{len(papers)} / {total} 件表示" if truncated else f"{len(papers)} 件"
            return QueryResult(
                source="OpenAlex",
                status=status,
                items=papers,
                total_count=total,
                truncated=truncated,
                message=msg,
            )

        return cached_query(self.cache, key, TTL_LITERATURE_SECONDS, _fetch)

    def _parse_work(self, w: dict[str, Any]) -> dict[str, Any]:
        authors: list[str] = []
        for auth in w.get("authorships") or []:
            name = ((auth.get("author") or {}).get("display_name") or "").strip()
            if name:
                authors.append(name)

        loc = w.get("primary_location") or {}
        src = loc.get("source") or {}
        journal = src.get("display_name") or ""

        doi = normalize_doi(w.get("doi") or "")
        pmid_raw = ((w.get("ids") or {}).get("pmid") or "")
        pmid = pmid_raw.rstrip("/").split("/")[-1] if pmid_raw else ""

        keywords = [
            t.get("display_name", "")
            for t in (w.get("topics") or [])[:5]
            if t.get("display_name")
        ]

        return {
            "title": w.get("title") or "No title",
            "authors": authors,
            "doi": doi,
            "pmid": pmid,
            "abstract": _reconstruct_abstract(w.get("abstract_inverted_index")),
            "journal": journal,
            "year": str(w.get("publication_year") or ""),
            "keywords": keywords,
            "citations": int(w.get("cited_by_count") or 0),
            "source": "OpenAlex",
        }
