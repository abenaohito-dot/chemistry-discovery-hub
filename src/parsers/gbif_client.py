"""GBIF Client — Plant taxonomy normalization and synonym lookup (Plantae-restricted)."""
from __future__ import annotations

from typing import Any

import requests

from src.utils.cache import SQLiteCache, TTL_ENTITY_SECONDS
from src.utils.common import QueryResult, cached_query, classify_request_error, make_cache_key

_MATCH_URL = "https://api.gbif.org/v1/species/match"
_SPECIES_URL = "https://api.gbif.org/v1/species"


class GBIFClient:
    """Resolve plant names against GBIF Taxonomic Backbone (kingdom=Plantae)."""

    def __init__(self, cache: SQLiteCache | None = None):
        self.cache = cache
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "ChemistryDiscoveryHub/2.0"})

    def match_plant(self, name: str, synonym_limit: int = 30) -> QueryResult:
        """
        Match a plant scientific name within kingdom Plantae and retrieve synonyms.
        Prevents cross-kingdom homonyms (e.g., Ecklonia in Cyperaceae vs brown algae).
        """
        q = name.strip()
        if not q:
            return QueryResult(source="GBIF", status="empty")

        key = make_cache_key("gbif_plant", q.lower(), synonym_limit)

        def _fetch() -> QueryResult:
            try:
                resp = self.session.get(
                    _MATCH_URL,
                    params={"name": q, "kingdom": "Plantae"},
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                return classify_request_error("GBIF", exc)

            match_type = data.get("matchType", "NONE")
            kingdom = data.get("kingdom", "")
            if match_type == "NONE" or kingdom != "Plantae":
                return QueryResult(
                    source="GBIF",
                    status="empty",
                    total_count=0,
                    message=f"GBIF (Plantae): '{q}' に該当する植物分類名が見つかりませんでした",
                )

            usage_key = data.get("usageKey")
            accepted_key = data.get("acceptedUsageKey") or usage_key
            matched_canonical = (data.get("canonicalName") or "").strip()

            accepted_record = data
            if accepted_key and accepted_key != usage_key:
                try:
                    acc_resp = self.session.get(f"{_SPECIES_URL}/{accepted_key}", timeout=15)
                    if acc_resp.status_code == 200:
                        accepted_record = acc_resp.json()
                except Exception:
                    pass

            accepted_name = (
                accepted_record.get("canonicalName")
                or accepted_record.get("species")
                or accepted_record.get("genus")
                or accepted_record.get("family")
                or matched_canonical
            ).strip()

            synonyms: list[str] = []
            seen_lower: set[str] = {accepted_name.lower()} if accepted_name else set()
            if matched_canonical and matched_canonical.lower() not in seen_lower:
                synonyms.append(matched_canonical)
                seen_lower.add(matched_canonical.lower())

            syn_truncated = False
            if accepted_key:
                try:
                    syn_resp = self.session.get(
                        f"{_SPECIES_URL}/{accepted_key}/synonyms",
                        params={"limit": synonym_limit},
                        timeout=15,
                    )
                    if syn_resp.status_code == 200:
                        syn_json = syn_resp.json()
                        syn_truncated = not syn_json.get("endOfRecords", True)
                        for s in syn_json.get("results", []):
                            cn = (s.get("canonicalName") or "").strip()
                            if cn and cn.lower() not in seen_lower:
                                seen_lower.add(cn.lower())
                                synonyms.append(cn)
                except Exception:
                    pass

            item: dict[str, Any] = {
                "input_name": q,
                "matched_name": matched_canonical,
                "accepted_name": accepted_name,
                "scientific_name": accepted_record.get("scientificName", ""),
                "rank": (accepted_record.get("rank") or data.get("rank") or "").upper(),
                "status": data.get("status", ""),
                "match_type": match_type,
                "confidence": data.get("confidence", 0),
                "kingdom": kingdom,
                "family": accepted_record.get("family") or data.get("family", ""),
                "genus": accepted_record.get("genus") or data.get("genus", ""),
                "species": accepted_record.get("species") or data.get("species", ""),
                "usage_key": usage_key,
                "accepted_usage_key": accepted_key,
                "synonyms": synonyms,
                "gbif_url": f"https://www.gbif.org/species/{accepted_key}" if accepted_key else "",
            }

            return QueryResult(
                source="GBIF",
                status="truncated" if syn_truncated else "ok",
                items=[item],
                total_count=1,
                truncated=syn_truncated,
                message=f"承認名: {accepted_name} (シノニム {len(synonyms)}件)",
            )

        return cached_query(self.cache, key, TTL_ENTITY_SECONDS, _fetch)
