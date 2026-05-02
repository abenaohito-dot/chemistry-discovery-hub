"""
COCONUT Client — COlleCtion of Open NatUral producTs API.
Searches the COCONUT database (~500k natural compounds).
"""
from __future__ import annotations

from typing import Any

import requests

_BASE = "https://coconut.naturalproducts.net/api"


class COCONUTClient:
    """Query the COCONUT natural products database."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "ChemistryDiscoveryHub/1.0",
            "Accept":     "application/json",
        })

    def search(self, name: str, max_results: int = 5) -> dict[str, Any] | None:
        """
        Search COCONUT by compound name.

        Returns dict with:
          - found:        bool
          - coconut_id:   str
          - name:         str
          - synonyms:     list[str]
          - mol_formula:  str
          - mol_weight:   float
          - nplikeness:   float  (natural product-likeness score)
          - sources:      list[str]  (source organisms / references)
          - coconut_url:  str
        """
        # Try exact name search
        result = self._search_by_name(name)
        if result:
            return result

        # Try SMILES-based search if name lookup fails (not implemented here)
        return {"found": False, "name": name}

    def get_by_id(self, coconut_id: str) -> dict[str, Any] | None:
        """Fetch a compound by its COCONUT identifier (e.g. 'CNP0000001')."""
        url = f"{_BASE}/compound/{coconut_id}"
        try:
            resp = self.session.get(url, timeout=10)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return self._parse_compound(resp.json())
        except Exception as exc:
            print(f"[COCONUT] get_by_id error for {coconut_id}: {exc}")
            return None

    # ── Private helpers ──────────────────────────────────────────────────────

    def _search_by_name(self, name: str) -> dict[str, Any] | None:
        """Try the COCONUT search endpoint."""
        # COCONUT v2 API search endpoint
        endpoints = [
            f"{_BASE}/search/compounds?query={requests.utils.quote(name)}&type=name",
            f"{_BASE}/v2/search?query={requests.utils.quote(name)}",
            f"{_BASE}/search?q={requests.utils.quote(name)}",
        ]

        for url in endpoints:
            try:
                resp = self.session.get(url, timeout=12)
                if resp.status_code not in (200, 201):
                    continue
                data = resp.json()

                # Handle different response shapes
                compounds = (
                    data.get("data") or
                    data.get("compounds") or
                    data.get("results") or
                    (data if isinstance(data, list) else [])
                )

                if compounds:
                    return self._parse_compound(
                        compounds[0] if isinstance(compounds, list) else compounds
                    )
            except Exception:
                continue

        return None

    def _parse_compound(self, data: dict) -> dict[str, Any]:
        coconut_id  = (
            data.get("coconut_id") or
            data.get("id") or
            data.get("identifier", "")
        )
        name = (
            data.get("name") or
            data.get("iupac_name") or
            data.get("preferred_name", "")
        )
        synonyms = data.get("synonyms", [])
        if isinstance(synonyms, str):
            synonyms = [synonyms]

        # Source organisms
        sources: list[str] = []
        for src in data.get("sources", data.get("organisms", [])):
            if isinstance(src, dict):
                org = src.get("organism_name") or src.get("name", "")
                if org:
                    sources.append(org)
            elif isinstance(src, str):
                sources.append(src)

        return {
            "found":       True,
            "coconut_id":  str(coconut_id),
            "name":        name,
            "synonyms":    synonyms[:10],
            "mol_formula": data.get("molecular_formula", data.get("formula", "")),
            "mol_weight":  data.get("molecular_weight", data.get("mol_weight", "")),
            "nplikeness":  data.get("np_likeness_score", data.get("nplikeness", "")),
            "sources":     sources[:5],
            "coconut_url": (
                f"https://coconut.naturalproducts.net/compound/{coconut_id}"
                if coconut_id else ""
            ),
        }
