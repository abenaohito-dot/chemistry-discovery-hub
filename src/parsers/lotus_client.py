"""LOTUS Client — Natural products search via LOTUS Web API and Wikidata SPARQL."""
from __future__ import annotations

import urllib.parse
from typing import Any

import requests

from src.utils.cache import SQLiteCache, TTL_ENTITY_SECONDS
from src.utils.common import (
    QueryResult,
    cached_query,
    classify_request_error,
    is_inchikey,
    make_cache_key,
    normalize_doi,
    normalize_formula,
)

_WEB_SIMPLE_URL = "https://lotus.naturalproducts.net/api/search/simple"
_SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"


def _escape_sparql(val: str) -> str:
    return val.replace("\\", "\\\\").replace('"', '\\"')


class LOTUSClient:
    """Query LOTUS Web API (name/formula) and Wikidata SPARQL (InChIKey/taxon with DOIs)."""

    def __init__(self, cache: SQLiteCache | None = None):
        self.cache = cache
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "ChemistryDiscoveryHub/2.0 (https://github.com/abenaohito-dot/chemistry-discovery-hub)",
            "Accept": "application/json",
        })

    def search_by_name(self, name: str, max_results: int = 20) -> QueryResult:
        """Search LOTUS Web API by compound name (works independently of PubChem)."""
        q = name.strip()
        if not q:
            return QueryResult(source="LOTUS", status="empty")

        limit = max(1, min(int(max_results), 50))
        key = make_cache_key("lotus_name", q.lower(), limit)

        def _fetch() -> QueryResult:
            try:
                resp = self.session.get(_WEB_SIMPLE_URL, params={"query": q}, timeout=25)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                return classify_request_error("LOTUS", exc)

            nps = data.get("naturalProducts") or []
            if not nps:
                return QueryResult(source="LOTUS", status="empty", total_count=0)

            q_low = q.lower()
            # Rank exact traditional_name matches earlier without discarding isomers/glycosides
            nps_sorted = sorted(
                nps,
                key=lambda x: (
                    0 if (x.get("traditional_name") or "").strip().lower() == q_low else 1,
                    int(x.get("heavy_atom_number") or 999),
                ),
            )
            total = len(nps_sorted)
            items = [self._parse_web_item(x) for x in nps_sorted[:limit]]
            truncated = total > len(items)
            return QueryResult(
                source="LOTUS",
                status="truncated" if truncated else "ok",
                items=items,
                total_count=total,
                truncated=truncated,
                message=f"{len(items)} / {total} 件表示" if truncated else f"{len(items)} 件",
            )

        return cached_query(self.cache, key, TTL_ENTITY_SECONDS, _fetch)

    def search_by_formula(self, formula: str, max_results: int = 50) -> QueryResult:
        """Search LOTUS Web API by molecular formula."""
        mf = normalize_formula(formula)
        if not mf:
            return QueryResult(source="LOTUS", status="empty")

        limit = max(1, min(int(max_results), 100))
        key = make_cache_key("lotus_mf", mf, limit)

        def _fetch() -> QueryResult:
            try:
                resp = self.session.get(_WEB_SIMPLE_URL, params={"query": mf}, timeout=25)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                return classify_request_error("LOTUS", exc)

            nps = data.get("naturalProducts") or []
            if not nps:
                return QueryResult(source="LOTUS", status="empty", total_count=0)

            total = len(nps)
            items = [self._parse_web_item(x) for x in nps[:limit]]
            truncated = total > len(items)
            return QueryResult(
                source="LOTUS",
                status="truncated" if truncated else "ok",
                items=items,
                total_count=total,
                truncated=truncated,
                message=f"{len(items)} / {total} 件表示" if truncated else f"{len(items)} 件",
            )

        return cached_query(self.cache, key, TTL_ENTITY_SECONDS, _fetch)

    def get_organisms_by_inchikey(self, inchikey: str, limit: int = 50) -> QueryResult:
        """
        Query Wikidata SPARQL by strict 27-character InChIKey (wdt:P235)
        to retrieve source organisms (p:P703) and reference DOIs (prov:wasDerivedFrom).
        """
        ik = inchikey.strip().upper()
        if not is_inchikey(ik):
            return QueryResult(source="LOTUS", status="empty", message="有効な27文字InChIKeyなし")

        lim = max(1, min(int(limit), 100))
        key = make_cache_key("lotus_wd_ik", ik, lim)

        def _fetch() -> QueryResult:
            sparql = f"""
            SELECT DISTINCT ?compound ?taxon ?taxonLabel ?doi WHERE {{
              ?compound wdt:P235 "{_escape_sparql(ik)}" .
              ?compound p:P703 ?stmt .
              ?stmt ps:P703 ?taxon .
              OPTIONAL {{ ?stmt prov:wasDerivedFrom/pr:P248/wdt:P356 ?doi . }}
              SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
            }} LIMIT {lim + 1}
            """
            try:
                resp = self.session.get(
                    _SPARQL_ENDPOINT,
                    params={"query": sparql, "format": "json"},
                    headers={"Accept": "application/sparql-results+json"},
                    timeout=20,
                )
                resp.raise_for_status()
                bindings = resp.json().get("results", {}).get("bindings", [])
            except Exception as exc:
                return classify_request_error("LOTUS(Wikidata)", exc)

            if not bindings:
                return QueryResult(source="LOTUS", status="empty", total_count=0)

            truncated = len(bindings) > lim
            bindings = bindings[:lim]

            seen: set[tuple[str, str]] = set()
            items: list[dict[str, Any]] = []
            for b in bindings:
                t_name = (b.get("taxonLabel") or {}).get("value", "").strip()
                t_uri = (b.get("taxon") or {}).get("value", "")
                c_uri = (b.get("compound") or {}).get("value", "")
                doi = normalize_doi((b.get("doi") or {}).get("value", ""))
                sig = (t_name, doi)
                if not t_name or sig in seen:
                    continue
                seen.add(sig)
                items.append({
                    "name": t_name,
                    "doi": doi,
                    "taxon_qid": t_uri.split("/")[-1] if t_uri else "",
                    "compound_qid": c_uri.split("/")[-1] if c_uri else "",
                    "wikidata_url": c_uri,
                })

            if not items:
                return QueryResult(source="LOTUS", status="empty", total_count=0)

            return QueryResult(
                source="LOTUS",
                status="truncated" if truncated else "ok",
                items=items,
                truncated=truncated,
                message=f"基原生物-文献ペア {len(items)}件" + ("（上限到達・一部表示）" if truncated else ""),
            )

        return cached_query(self.cache, key, TTL_ENTITY_SECONDS, _fetch)

    def search_by_taxon(
        self,
        taxon_name: str,
        rank: str = "SPECIES",
        limit: int = 80,
        gbif_id: int | str | None = None,
    ) -> QueryResult:
        """
        Retrieve reported compounds + DOIs for a plant species or genus via Wikidata SPARQL.
        If gbif_id is given, excludes homonyms with a conflicting GBIF ID (P846).
        Family-level bulk queries are intentionally excluded to avoid 60s SPARQL timeouts.
        """
        name = taxon_name.strip()
        rk = rank.strip().upper()
        if not name:
            return QueryResult(source="LOTUS", status="empty")

        if rk == "FAMILY":
            return QueryResult(
                source="LOTUS",
                status="empty",
                message="科レベルの既報化合物一括取得は公開APIの制限により対象外です。属または種を指定するか、上の文献検索をご利用ください。",
            )

        lim = max(1, min(int(limit), 150))
        gbif_str = str(gbif_id).strip() if gbif_id else ""
        key = make_cache_key("lotus_taxon", name.lower(), rk, lim, gbif_str)

        def _fetch() -> QueryResult:
            safe = _escape_sparql(name)
            if rk == "GENUS":
                homonym_filter = (
                    f'FILTER NOT EXISTS {{ ?genus wdt:P846 ?gid . FILTER(?gid != "{_escape_sparql(gbif_str)}") }}'
                    if gbif_str
                    else ""
                )
                taxon_pattern = f"""
                  ?genus wdt:P225 "{safe}" .
                  {homonym_filter}
                  ?taxon wdt:P171 ?genus ;
                         wdt:P225 ?taxonName .
                """
            else:
                homonym_filter = (
                    f'FILTER NOT EXISTS {{ ?taxon wdt:P846 ?gid . FILTER(?gid != "{_escape_sparql(gbif_str)}") }}'
                    if gbif_str
                    else ""
                )
                taxon_pattern = f"""
                  ?taxon wdt:P225 "{safe}" .
                  {homonym_filter}
                  BIND("{safe}" AS ?taxonName)
                """

            sparql = f"""
            SELECT DISTINCT ?taxonName ?c ?cLabel ?ik ?mf ?smiles ?doi WHERE {{
              {taxon_pattern}
              ?c p:P703 ?stmt .
              ?stmt ps:P703 ?taxon .
              OPTIONAL {{ ?c wdt:P235 ?ik . }}
              OPTIONAL {{ ?c wdt:P274 ?mf . }}
              OPTIONAL {{ ?c wdt:P2017 ?smilesIso . }}
              OPTIONAL {{ ?c wdt:P233 ?smilesCan . }}
              BIND(COALESCE(?smilesIso, ?smilesCan) AS ?smiles)
              OPTIONAL {{ ?stmt prov:wasDerivedFrom/pr:P248/wdt:P356 ?doi . }}
              SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
            }} LIMIT {lim + 1}
            """
            try:
                resp = self.session.get(
                    _SPARQL_ENDPOINT,
                    params={"query": sparql, "format": "json"},
                    headers={"Accept": "application/sparql-results+json"},
                    timeout=20,
                )
                resp.raise_for_status()
                bindings = resp.json().get("results", {}).get("bindings", [])
            except Exception as exc:
                return classify_request_error("LOTUS(Wikidata)", exc)

            if not bindings:
                return QueryResult(source="LOTUS", status="empty", total_count=0)

            truncated = len(bindings) > lim
            bindings = bindings[:lim]

            seen: set[tuple[str, str, str]] = set()
            items: list[dict[str, Any]] = []
            for b in bindings:
                t_name = (b.get("taxonName") or {}).get("value", "").strip() or name
                c_uri = (b.get("c") or {}).get("value", "")
                c_label = (b.get("cLabel") or {}).get("value", "").strip()
                ik = (b.get("ik") or {}).get("value", "").strip().upper()
                mf = normalize_formula((b.get("mf") or {}).get("value", ""))
                smiles = (b.get("smiles") or {}).get("value", "").strip()
                doi = normalize_doi((b.get("doi") or {}).get("value", ""))

                sig = (t_name, ik or c_label, doi)
                if sig in seen:
                    continue
                seen.add(sig)
                items.append({
                    "source": "LOTUS",
                    "taxon": t_name,
                    "name": c_label or ik or c_uri.split("/")[-1],
                    "inchikey": ik,
                    "formula": mf,
                    "smiles": smiles,
                    "doi": doi,
                    "wikidata_url": c_uri,
                })

            if not items:
                return QueryResult(source="LOTUS", status="empty", total_count=0)

            return QueryResult(
                source="LOTUS",
                status="truncated" if truncated else "ok",
                items=items,
                truncated=truncated,
                message=f"{len(items)} 件取得" + ("（上限到達・一部表示）" if truncated else ""),
            )

        return cached_query(self.cache, key, TTL_ENTITY_SECONDS, _fetch)

    def _parse_web_item(self, x: dict[str, Any]) -> dict[str, Any]:
        lotus_id = str(x.get("lotus_id") or "")
        wikidata_raw = str(x.get("wikidata_id") or "")
        name = (
            x.get("traditional_name")
            or x.get("iupac_name")
            or lotus_id
            or ""
        )
        smiles = x.get("smiles") or x.get("smiles2D") or ""
        ik = (x.get("inchikey") or "").strip().upper()

        # Extract (organism, doi) pairs from taxonomyReferenceObjects when present
        organisms: list[dict[str, str]] = []
        seen_org: set[tuple[str, str]] = set()
        tax_refs = x.get("taxonomyReferenceObjects") or {}
        if isinstance(tax_refs, dict):
            for raw_doi, sources_dict in tax_refs.items():
                doi = normalize_doi(raw_doi.replace("$x$x$", "."))
                if not isinstance(sources_dict, dict):
                    continue
                for entries in sources_dict.values():
                    if not isinstance(entries, list):
                        continue
                    for entry in entries:
                        if not isinstance(entry, dict):
                            continue
                        org_name = (
                            entry.get("organism_value")
                            or entry.get("species")
                            or ""
                        ).strip()
                        if org_name and (org_name, doi) not in seen_org:
                            seen_org.add((org_name, doi))
                            organisms.append({
                                "name": org_name,
                                "doi": doi,
                                "wikidata_url": wikidata_raw,
                            })
                        if len(organisms) >= 20:
                            break
                    if len(organisms) >= 20:
                        break
                if len(organisms) >= 20:
                    break

        mw = x.get("molecular_weight")
        mw_str = f"{float(mw):.2f}" if isinstance(mw, (int, float)) else str(mw or "")

        return {
            "source": "LOTUS",
            "lotus_id": lotus_id,
            "wikidata_id": wikidata_raw.split("/")[-1] if wikidata_raw else "",
            "wikidata_url": wikidata_raw,
            "lotus_url": (
                f"https://lotus.naturalproducts.net/compound/lotus_id/{urllib.parse.quote(lotus_id)}"
                if lotus_id
                else ""
            ),
            "name": str(name).strip(),
            "iupac_name": str(x.get("iupac_name") or ""),
            "formula": normalize_formula(str(x.get("molecular_formula") or "")),
            "mol_weight": mw_str,
            "smiles": smiles,
            "inchikey": ik,
            "cas": str(x.get("cas") or ""),
            "organisms": organisms,
        }
