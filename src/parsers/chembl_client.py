"""ChEMBL Client — bioactivity data (IC50, EC50, Ki, etc.)."""
from __future__ import annotations
from typing import Any
import requests

_BASE = "https://www.ebi.ac.uk/chembl/api/data"


class ChEMBLClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "ChemistryDiscoveryHub/1.0",
            "Accept": "application/json",
        })

    def get_bioactivity(self, name: str, max_activities: int = 5) -> dict[str, Any]:
        """
        Retrieve bioactivity data for a compound by name.
        Returns IC50/EC50/Ki values and target information.
        """
        chembl_id = self._get_chembl_id(name)
        if not chembl_id:
            return {"found": False, "name": name}

        activities = self._get_activities(chembl_id, max_activities)
        return {
            "found":      True,
            "name":       name,
            "chembl_id":  chembl_id,
            "activities": activities,
            "chembl_url": f"https://www.ebi.ac.uk/chembl/compound_report_card/{chembl_id}/",
        }

    def _get_chembl_id(self, name: str) -> str | None:
        url = f"{_BASE}/molecule"
        params = {
            "pref_name__iexact": name,
            "format": "json",
            "limit": 1,
        }
        try:
            resp = self.session.get(url, params=params, timeout=12)
            resp.raise_for_status()
            molecules = resp.json().get("molecules", [])
            if molecules:
                return molecules[0].get("molecule_chembl_id")
        except Exception:
            pass

        # Try synonym search
        params2 = {"molecule_synonyms__molecule_synonym__iexact": name, "format": "json", "limit": 1}
        try:
            resp = self.session.get(url, params=params2, timeout=12)
            resp.raise_for_status()
            molecules = resp.json().get("molecules", [])
            if molecules:
                return molecules[0].get("molecule_chembl_id")
        except Exception as exc:
            print(f"[ChEMBL] ID lookup failed for '{name}': {exc}")
        return None

    def _get_activities(self, chembl_id: str, limit: int) -> list[dict[str, Any]]:
        url = f"{_BASE}/activity"
        params = {
            "molecule_chembl_id": chembl_id,
            "format": "json",
            "limit": limit,
            "standard_type__in": "IC50,EC50,Ki,Kd,GI50,MIC",
        }
        try:
            resp = self.session.get(url, params=params, timeout=12)
            resp.raise_for_status()
            acts = resp.json().get("activities", [])
            return [
                {
                    "type":   a.get("standard_type", ""),
                    "value":  a.get("standard_value", ""),
                    "units":  a.get("standard_units", ""),
                    "target": a.get("target_pref_name", ""),
                    "assay":  a.get("assay_description", ""),
                }
                for a in acts
                if a.get("standard_value")
            ]
        except Exception as exc:
            print(f"[ChEMBL] activities error for {chembl_id}: {exc}")
            return []
