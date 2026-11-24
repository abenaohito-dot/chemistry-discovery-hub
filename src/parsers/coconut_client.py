"""COCONUT Client — Collection of Open Natural Products v2 REST API."""
from __future__ import annotations

import math
from typing import Any

import requests

from src.utils.cache import SQLiteCache, TTL_ENTITY_SECONDS
from src.utils.common import (
    QueryResult,
    cached_query,
    classify_request_error,
    is_cas_number,
    is_inchikey,
    make_cache_key,
    normalize_formula,
    smiles_to_props,
)

_SEARCH_URL = "https://coconut.naturalproducts.net/api/search"
_ATTRIBUTION_NOTE = "COCONUT (生物・文献はM:N集計のため個別対応は原著要確認)"


class COCONUTClient:
    """Query COCONUT v2 via POST /api/search (supports name, InChIKey, formula; NOT CAS/organism)."""

    def __init__(self, cache: SQLiteCache | None = None):
        self.cache = cache
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "ChemistryDiscoveryHub/2.0",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def search_by_name(self, name: str, max_results: int = 20) -> QueryResult:
        """Search COCONUT by compound name (skips raw CAS strings to avoid server HTTP 500)."""
        q = name.strip()
        if not q:
            return QueryResult(source="COCONUT", status="empty")
        if is_cas_number(q):
            return QueryResult(
                source="COCONUT",
                status="empty",
                message="COCONUT APIはCAS番号の直接検索に非対応です（InChIKey経由で照会します）",
            )
        return self._post_search(q, max_results=max_results, cache_tag="coconut_name", target_formula="")

    def search_by_inchikey(self, inchikey: str) -> QueryResult:
        """Search COCONUT by strict 27-character InChIKey."""
        ik = inchikey.strip().upper()
        if not is_inchikey(ik):
            return QueryResult(source="COCONUT", status="empty")
        return self._post_search(ik, max_results=5, cache_tag="coconut_ik", target_formula="")

    def search_by_formula(self, formula: str, max_results: int = 50) -> QueryResult:
        """Search COCONUT by molecular formula (computes InChIKey & formula via RDKit)."""
        mf = normalize_formula(formula)
        if not mf:
            return QueryResult(source="COCONUT", status="empty")
        return self._post_search(mf, max_results=max_results, cache_tag="coconut_mf", target_formula=mf)

    def _post_search(
        self,
        query: str,
        max_results: int,
        cache_tag: str,
        target_formula: str,
    ) -> QueryResult:
        limit = max(1, min(int(max_results), 72))
        key = make_cache_key(cache_tag, query.lower(), limit)

        def _fetch() -> QueryResult:
            items: list[dict[str, Any]] = []
            total = 0
            page = 1
            max_pages = max(1, math.ceil(limit / 24))

            while page <= max_pages and len(items) < limit:
                try:
                    resp = self.session.post(
                        _SEARCH_URL,
                        json={"query": query, "page": page},
                        timeout=20,
                    )
                    resp.raise_for_status()
                    payload = resp.json()
                except Exception as exc:
                    if items:
                        break
                    return classify_request_error("COCONUT", exc)

                data_block = payload.get("data") or {}
                rows = data_block.get("data") if isinstance(data_block, dict) else []
                total = int(data_block.get("total") or len(rows or [])) if isinstance(data_block, dict) else 0
                last_page = int(data_block.get("last_page") or 1) if isinstance(data_block, dict) else 1

                if not rows:
                    break

                for row in rows:
                    parsed = self._parse_row(row)
                    if target_formula and parsed["formula"] and parsed["formula"] != target_formula:
                        continue
                    items.append(parsed)
                    if len(items) >= limit:
                        break

                if page >= last_page:
                    break
                page += 1

            if not items:
                return QueryResult(source="COCONUT", status="empty", total_count=0)

            truncated = total > len(items)
            return QueryResult(
                source="COCONUT",
                status="truncated" if truncated else "ok",
                items=items,
                total_count=total,
                truncated=truncated,
                message=f"{len(items)} / {total} 件表示" if truncated else f"{len(items)} 件",
            )

        return cached_query(self.cache, key, TTL_ENTITY_SECONDS, _fetch)

    def _parse_row(self, row: dict[str, Any]) -> dict[str, Any]:
        cid = str(row.get("identifier") or "")
        smiles = (row.get("canonical_smiles") or "").strip()
        ik, mf = smiles_to_props(smiles)
        name = (row.get("name") or row.get("iupac_name") or cid or "").strip()
        return {
            "source": "COCONUT",
            "coconut_id": cid,
            "coconut_url": f"https://coconut.naturalproducts.net/compounds/{cid}" if cid else "",
            "name": name,
            "iupac_name": (row.get("iupac_name") or "").strip(),
            "smiles": smiles,
            "inchikey": ik,
            "formula": mf,
            "mol_weight": "",
            "organism_count": row.get("organism_count"),
            "citation_count": row.get("citation_count"),
            "annotation_level": row.get("annotation_level"),
            "attribution_note": _ATTRIBUTION_NOTE,
        }
