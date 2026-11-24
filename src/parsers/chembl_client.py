"""ChEMBL Client — On-demand bioactivity data (IC50, EC50, Ki, etc.)."""
from __future__ import annotations

from typing import Any

import requests

from src.utils.cache import SQLiteCache, TTL_ENTITY_SECONDS
from src.utils.common import (
    QueryResult,
    cached_query,
    classify_request_error,
    is_inchikey,
    make_cache_key,
)

_BASE = "https://www.ebi.ac.uk/chembl/api/data"


class ChEMBLClient:
    """Retrieve bioactivity data on demand via ChEMBL REST API (27-char InChIKey first)."""

    def __init__(self, cache: SQLiteCache | None = None):
        self.cache = cache
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "ChemistryDiscoveryHub/2.0",
            "Accept": "application/json",
        })

    def get_bioactivity(
        self,
        inchikey: str = "",
        name: str = "",
        max_activities: int = 10,
    ) -> QueryResult:
        """
        Retrieve bioactivity records by exact 27-char InChIKey (preferred) or compound name.
        Returns a QueryResult distinguishing empty, truncated, timeout, and error states.
        """
        ik = inchikey.strip().upper()
        nm = name.strip()
        if not ik and not nm:
            return QueryResult(source="ChEMBL", status="empty")

        limit = max(1, min(int(max_activities), 50))
        key = make_cache_key("chembl", ik, nm.lower(), limit)

        def _fetch() -> QueryResult:
            try:
                chembl_id, match_type = self._resolve_chembl_id(ik, nm)
            except Exception as exc:
                return classify_request_error("ChEMBL", exc)

            if not chembl_id:
                return QueryResult(
                    source="ChEMBL",
                    status="empty",
                    total_count=0,
                    message="ChEMBL に該当化合物なし",
                )

            try:
                total, activities = self._get_activities(chembl_id, limit)
            except Exception as exc:
                return classify_request_error("ChEMBL", exc)

            entry = {
                "chembl_id": chembl_id,
                "match_type": match_type,
                "activities": activities,
                "chembl_url": f"https://www.ebi.ac.uk/chembl/compound_report_card/{chembl_id}/",
            }
            if not activities:
                return QueryResult(
                    source="ChEMBL",
                    status="empty",
                    items=[entry],
                    total_count=0,
                    message=f"{chembl_id} ({match_type}): 対象の活性データ(IC50等)なし",
                )

            truncated = total > len(activities)
            status = "truncated" if truncated else "ok"
            msg = (
                f"{chembl_id} ({match_type}): {len(activities)} / {total} 件表示"
                if truncated
                else f"{chembl_id} ({match_type}): {len(activities)} 件"
            )
            return QueryResult(
                source="ChEMBL",
                status=status,
                items=[entry],
                total_count=total,
                truncated=truncated,
                message=msg,
            )

        return cached_query(self.cache, key, TTL_ENTITY_SECONDS, _fetch)

    def _resolve_chembl_id(self, inchikey: str, name: str) -> tuple[str | None, str]:
        url = f"{_BASE}/molecule"
        if is_inchikey(inchikey):
            resp = self.session.get(
                url,
                params={
                    "molecule_structures__standard_inchi_key": inchikey,
                    "format": "json",
                    "limit": 1,
                },
                timeout=15,
            )
            resp.raise_for_status()
            mols = resp.json().get("molecules", [])
            if mols:
                return mols[0].get("molecule_chembl_id"), "InChIKey完全一致"

        if name:
            for param_key in ("pref_name__iexact", "molecule_synonyms__molecule_synonym__iexact"):
                resp = self.session.get(
                    url,
                    params={param_key: name, "format": "json", "limit": 1},
                    timeout=15,
                )
                resp.raise_for_status()
                mols = resp.json().get("molecules", [])
                if mols:
                    return mols[0].get("molecule_chembl_id"), "名称一致（立体要確認）"

        return None, ""

    def _get_activities(self, chembl_id: str, limit: int) -> tuple[int, list[dict[str, Any]]]:
        url = f"{_BASE}/activity"
        params = {
            "molecule_chembl_id": chembl_id,
            "format": "json",
            "limit": limit,
            "standard_type__in": "IC50,EC50,Ki,Kd,GI50,MIC",
        }
        resp = self.session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        payload = resp.json()
        total = int((payload.get("page_meta") or {}).get("total_count") or 0)
        acts = payload.get("activities", [])
        parsed = [
            {
                "type": a.get("standard_type", ""),
                "relation": a.get("standard_relation", "="),
                "value": a.get("standard_value", ""),
                "units": a.get("standard_units", ""),
                "target": a.get("target_pref_name", ""),
                "assay": a.get("assay_description", ""),
            }
            for a in acts
            if a.get("standard_value") is not None
        ]
        return total, parsed
