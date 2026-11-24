"""PubChem Client — PUG REST API for name, CAS, InChIKey, and formula lookup."""
from __future__ import annotations

import time
import urllib.parse
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
)

_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
_PROPS = "MolecularFormula,MolecularWeight,IsomericSMILES,CanonicalSMILES,SMILES,ConnectivitySMILES,InChIKey,IUPACName"


class PubChemClient:
    """Query PubChem PUG REST API with persistent caching and polite rate limits."""

    def __init__(self, cache: SQLiteCache | None = None):
        self.cache = cache
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "ChemistryDiscoveryHub/2.0"})

    def search_compound(self, query: str, max_results: int = 5) -> QueryResult:
        """Search PubChem by CAS number, 27-char InChIKey, or compound name."""
        q = query.strip()
        if not q:
            return QueryResult(source="PubChem", status="empty")

        limit = max(1, min(int(max_results), 20))
        key = make_cache_key("pubchem_cmp", q.lower(), limit)

        def _fetch() -> QueryResult:
            enc = urllib.parse.quote(q, safe="")
            if is_cas_number(q):
                cid_url = f"{_BASE}/compound/xref/rn/{enc}/cids/JSON"
            elif is_inchikey(q):
                cid_url = f"{_BASE}/compound/inchikey/{enc}/cids/JSON"
            else:
                cid_url = f"{_BASE}/compound/name/{enc}/cids/JSON"

            return self._cids_to_result(cid_url, query_label=q, max_results=limit, fetch_cas=True)

        return cached_query(self.cache, key, TTL_ENTITY_SECONDS, _fetch)

    def search_by_formula(self, formula: str, max_results: int = 30) -> QueryResult:
        """Search PubChem by molecular formula via fastformula endpoint (includes synthetics)."""
        mf = normalize_formula(formula)
        if not mf:
            return QueryResult(source="PubChem", status="empty")

        limit = max(1, min(int(max_results), 50))
        key = make_cache_key("pubchem_mf", mf, limit)

        def _fetch() -> QueryResult:
            enc = urllib.parse.quote(mf, safe="")
            cid_url = f"{_BASE}/compound/fastformula/{enc}/cids/JSON"
            return self._cids_to_result(cid_url, query_label="", max_results=limit, fetch_cas=False)

        return cached_query(self.cache, key, TTL_ENTITY_SECONDS, _fetch)

    def _cids_to_result(
        self,
        cid_url: str,
        query_label: str,
        max_results: int,
        fetch_cas: bool,
    ) -> QueryResult:
        try:
            resp = self.session.get(cid_url, timeout=15)
            if resp.status_code == 404:
                return QueryResult(source="PubChem", status="empty", total_count=0)
            resp.raise_for_status()
            cids = resp.json().get("IdentifierList", {}).get("CID", [])
        except Exception as exc:
            return classify_request_error("PubChem", exc)

        if not cids:
            return QueryResult(source="PubChem", status="empty", total_count=0)

        total = len(cids)
        target_cids = cids[:max_results]
        time.sleep(0.22)

        try:
            props_list = self._get_properties_batch(target_cids)
        except Exception as exc:
            return classify_request_error("PubChem", exc)

        items: list[dict[str, Any]] = []
        for idx, props in enumerate(props_list):
            cid = props.get("CID")
            if not cid:
                continue
            smiles = (
                props.get("IsomericSMILES")
                or props.get("SMILES")
                or props.get("CanonicalSMILES")
                or props.get("ConnectivitySMILES")
                or ""
            )
            cas = ""
            display_name = query_label if (query_label and not is_cas_number(query_label) and not is_inchikey(query_label) and idx == 0) else ""
            if fetch_cas and idx < 3:
                time.sleep(0.22)
                syns = self._get_synonyms(int(cid))
                cas = self._extract_cas(syns)
                if not display_name and syns:
                    # Pick first non-CAS synonym as readable name
                    for s in syns:
                        if not is_cas_number(s):
                            display_name = s
                            break
            if is_cas_number(query_label) and not cas:
                cas = query_label

            items.append({
                "source": "PubChem",
                "cid": cid,
                "name": display_name or props.get("IUPACName") or f"CID {cid}",
                "iupac_name": props.get("IUPACName", ""),
                "formula": normalize_formula(props.get("MolecularFormula", "")),
                "mol_weight": props.get("MolecularWeight", ""),
                "smiles": smiles,
                "inchikey": (props.get("InChIKey") or "").strip().upper(),
                "cas": cas,
                "pubchem_url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}",
            })

        if not items:
            return QueryResult(source="PubChem", status="empty", total_count=0)

        truncated = total > len(items)
        status = "truncated" if truncated else "ok"
        msg = f"{len(items)} / {total} 件表示" if truncated else f"{len(items)} 件"
        return QueryResult(
            source="PubChem",
            status=status,
            items=items,
            total_count=total,
            truncated=truncated,
            message=msg,
        )

    def _get_properties_batch(self, cids: list[int]) -> list[dict[str, Any]]:
        cid_str = ",".join(str(c) for c in cids)
        url = f"{_BASE}/compound/cid/{cid_str}/property/{_PROPS}/JSON"
        resp = self.session.get(url, timeout=20)
        resp.raise_for_status()
        return resp.json().get("PropertyTable", {}).get("Properties", [])

    def _get_synonyms(self, cid: int) -> list[str]:
        url = f"{_BASE}/compound/cid/{cid}/synonyms/JSON"
        try:
            resp = self.session.get(url, timeout=10)
            if resp.status_code != 200:
                return []
            info = resp.json().get("InformationList", {}).get("Information", [])
            return info[0].get("Synonym", []) if info else []
        except Exception:
            return []

    @staticmethod
    def _extract_cas(synonyms: list[str]) -> str:
        for syn in synonyms:
            if is_cas_number(syn):
                return syn.strip()
        return ""
