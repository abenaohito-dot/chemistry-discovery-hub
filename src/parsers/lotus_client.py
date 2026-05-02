"""
LOTUS Client — Natural product–organism occurrence data via Wikidata SPARQL.
"""
from __future__ import annotations
from typing import Any
import requests

_SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
_WIKIDATA_SEARCH = "https://www.wikidata.org/w/api.php"


class LOTUSClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "ChemistryDiscoveryHub/1.0",
            "Accept": "application/sparql-results+json",
        })

    def get_organisms(self, compound_name: str) -> dict[str, Any]:
        """Find organisms known to contain the given compound via LOTUS/Wikidata."""
        qid = self._search_compound_qid(compound_name)
        if not qid:
            return {"compound_name": compound_name, "found": False, "organisms": []}
        organisms = self._sparql_organisms(qid)
        return {
            "compound_name": compound_name,
            "found": True,
            "qid": qid,
            "organisms": organisms[:10],
            "wikidata_url": f"https://www.wikidata.org/wiki/{qid}",
        }

    def _search_compound_qid(self, name: str) -> str | None:
        params = {
            "action": "wbsearchentities", "search": name,
            "language": "en", "type": "item",
            "format": "json", "limit": 5,
        }
        try:
            resp = self.session.get(
                _WIKIDATA_SEARCH, params=params, timeout=10,
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            results = resp.json().get("search", [])
            for r in results:
                desc = r.get("description", "").lower()
                if any(kw in desc for kw in ("chemical", "compound", "molecule",
                                              "alkaloid", "flavonoid", "natural")):
                    return r.get("id")
            return results[0]["id"] if results else None
        except Exception as exc:
            print(f"[LOTUS] Wikidata search error: {exc}")
            return None

    def _sparql_organisms(self, qid: str) -> list[dict[str, str]]:
        query = f"""
        SELECT DISTINCT ?taxon ?taxonLabel WHERE {{
          VALUES ?compound {{ wd:{qid} }}
          {{ ?compound wdt:P703 ?taxon . }}
          UNION
          {{ ?compound p:P1059 ?s . ?s ps:P1059 ?taxon . }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
        }} LIMIT 15
        """
        try:
            resp = self.session.get(
                _SPARQL_ENDPOINT, params={"query": query, "format": "json"}, timeout=20
            )
            resp.raise_for_status()
            bindings = resp.json().get("results", {}).get("bindings", [])
            seen: set[str] = set()
            results = []
            for b in bindings:
                name = b.get("taxonLabel", {}).get("value", "")
                qid_t = b.get("taxon", {}).get("value", "").split("/")[-1]
                if name and name not in seen:
                    seen.add(name)
                    results.append({"name": name, "qid": qid_t})
            return results
        except Exception as exc:
            print(f"[LOTUS] SPARQL error: {exc}")
            return []
