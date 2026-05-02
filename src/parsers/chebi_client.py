"""ChEBI Client — biological role and chemical classification."""
from __future__ import annotations
from typing import Any
import requests

_BASE = "https://www.ebi.ac.uk/webservices/chebi/2.0/test"


class ChEBIClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "ChemistryDiscoveryHub/1.0"})

    def get_info(self, name: str) -> dict[str, Any]:
        """Get ChEBI entry for compound name: biological roles, classification."""
        chebi_id = self._search_id(name)
        if not chebi_id:
            return {"found": False, "name": name}
        details = self._get_details(chebi_id)
        return details or {"found": False, "name": name}

    def _search_id(self, name: str) -> str | None:
        url = f"{_BASE}/getLiteEntity"
        params = {
            "search": name, "searchCategory": "ALL",
            "maximumResults": 5, "stars": "ALL",
        }
        try:
            resp = self.session.get(url, params=params, timeout=12)
            resp.raise_for_status()
            # ChEBI returns XML; parse it simply
            import xml.etree.ElementTree as ET
            root = ET.fromstring(resp.text)
            ns = {"s": "https://www.ebi.ac.uk/webservices/chebi"}
            entities = root.findall(".//s:ListElement", ns)
            if not entities:
                # Try without namespace
                entities = root.findall(".//{*}ListElement")
            if entities:
                chebi_id_el = (
                    entities[0].find("{*}chebiId") or
                    entities[0].find("chebiId")
                )
                if chebi_id_el is not None:
                    return chebi_id_el.text
        except Exception as exc:
            print(f"[ChEBI] search error for '{name}': {exc}")
        return None

    def _get_details(self, chebi_id: str) -> dict[str, Any] | None:
        url = f"{_BASE}/getCompleteEntity"
        try:
            resp = self.session.get(url, params={"chebiId": chebi_id}, timeout=12)
            resp.raise_for_status()
            import xml.etree.ElementTree as ET
            root = ET.fromstring(resp.text)

            def find_text(tag: str) -> str:
                el = root.find(f".//{{{_chebi_ns}}}{tag}") or root.find(f".//*[local-name()='{tag}']")
                return el.text.strip() if el is not None and el.text else ""

            _chebi_ns = "https://www.ebi.ac.uk/webservices/chebi"

            # Roles
            roles: list[str] = []
            for el in root.findall(f".//*[local-name()='OntologyParents']"):
                role_name = el.find("*[local-name()='chebiName']")
                if role_name is not None and role_name.text:
                    roles.append(role_name.text.strip())

            name = find_text("chebiAsciiName") or find_text("preferredName")
            return {
                "found":      True,
                "chebi_id":   chebi_id,
                "name":       name,
                "definition": find_text("definition"),
                "roles":      roles[:5],
                "chebi_url":  f"https://www.ebi.ac.uk/chebi/searchId.do?chebiId={chebi_id}",
            }
        except Exception as exc:
            print(f"[ChEBI] details error for {chebi_id}: {exc}")
            return None
