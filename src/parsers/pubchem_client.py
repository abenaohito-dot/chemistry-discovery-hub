"""
PubChem Client — PUG REST API for compound properties and structure images.
"""
from __future__ import annotations

import time
from functools import lru_cache
from typing import Any

import requests

_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
_PROPS = "MolecularFormula,MolecularWeight,CanonicalSMILES,IsomericSMILES,InChIKey,IUPACName"


class PubChemClient:
    """Query PubChem for compound info. Results are cached per session."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "ChemistryDiscoveryHub/1.0"})

    def get_compound_info(self, name: str) -> dict[str, Any] | None:
        """
        Retrieve compound properties + structure image URL by name.

        Args:
            name: Compound name (e.g. 'quercetin', 'berberine').
        Returns:
            Dict with compound metadata or None if not found.
        """
        name = name.strip()
        if not name:
            return None

        # Step 1: name → CID
        cid = self._get_cid(name)
        if not cid:
            return None

        # Step 2: CID → properties
        props = self._get_properties(cid)
        if not props:
            return None

        # Step 3: synonyms (for CAS number extraction)
        synonyms = self._get_synonyms(cid)
        cas = self._extract_cas(synonyms)

        return {
            "cid":          cid,
            "name":         name,
            "iupac_name":   props.get("IUPACName", ""),
            "formula":      props.get("MolecularFormula", ""),
            "mol_weight":   props.get("MolecularWeight", ""),
            "smiles":       props.get("IsomericSMILES") or props.get("CanonicalSMILES", ""),
            "inchikey":     props.get("InChIKey", ""),
            "cas":          cas,
            "image_url":    f"{_BASE}/compound/cid/{cid}/PNG?image_size=300x300",
            "pubchem_url":  f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}",
        }

    def get_compound_info_batch(
        self, names: list[str], delay: float = 0.22
    ) -> list[dict[str, Any] | None]:
        """Retrieve info for multiple compounds with rate-limiting."""
        results = []
        for name in names:
            results.append(self.get_compound_info(name))
            time.sleep(delay)
        return results

    # ── Private helpers ──────────────────────────────────────────────────────

    def _get_cid(self, name: str) -> int | None:
        url = f"{_BASE}/compound/name/{requests.utils.quote(name)}/cids/JSON"
        try:
            resp = self.session.get(url, timeout=10)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            cids = resp.json().get("IdentifierList", {}).get("CID", [])
            return cids[0] if cids else None
        except Exception as exc:
            print(f"[PubChem] CID lookup failed for '{name}': {exc}")
            return None

    def _get_properties(self, cid: int) -> dict | None:
        url = f"{_BASE}/compound/cid/{cid}/property/{_PROPS}/JSON"
        try:
            resp = self.session.get(url, timeout=10)
            resp.raise_for_status()
            props_list = resp.json().get("PropertyTable", {}).get("Properties", [])
            return props_list[0] if props_list else None
        except Exception as exc:
            print(f"[PubChem] properties lookup failed for CID {cid}: {exc}")
            return None

    def _get_synonyms(self, cid: int) -> list[str]:
        url = f"{_BASE}/compound/cid/{cid}/synonyms/JSON"
        try:
            resp = self.session.get(url, timeout=10)
            resp.raise_for_status()
            info = resp.json().get("InformationList", {}).get("Information", [])
            return info[0].get("Synonym", []) if info else []
        except Exception:
            return []

    @staticmethod
    def _extract_cas(synonyms: list[str]) -> str:
        """Extract CAS Registry Number from synonym list."""
        import re
        cas_pattern = re.compile(r"^\d{2,7}-\d{2}-\d$")
        for syn in synonyms:
            if cas_pattern.match(syn.strip()):
                return syn.strip()
        return ""
