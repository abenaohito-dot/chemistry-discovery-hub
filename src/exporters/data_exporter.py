"""Data Exporter — CSV and Markdown export for literature, compounds, formula hits, and taxon compounds."""
from __future__ import annotations

import io
from typing import Any

import pandas as pd

from src.utils.common import scifinder_doi_url, scifinder_substance_url


class DataExporter:

    # ── Papers ───────────────────────────────────────────────────────────────

    def papers_to_dataframe(self, papers: list[dict[str, Any]]) -> pd.DataFrame:
        rows = []
        for p in papers:
            authors = "; ".join(p.get("authors", []))
            keywords = "; ".join(p.get("keywords", []))
            doi = p.get("doi", "")
            sources = "; ".join(p.get("sources") or ([p["source"]] if p.get("source") else []))
            rows.append({
                "Title": p.get("title", ""),
                "Authors": authors,
                "Journal": p.get("journal", ""),
                "Year": p.get("year", ""),
                "DOI": doi,
                "PMID": p.get("pmid", ""),
                "Citations": p.get("citations", ""),
                "Sources": sources,
                "Keywords": keywords,
                "Abstract": p.get("abstract", ""),
                "SciFinder_URL": scifinder_doi_url(doi) if doi else "",
            })
        return pd.DataFrame(rows)

    def papers_to_csv(self, papers: list[dict[str, Any]]) -> bytes:
        df = self.papers_to_dataframe(papers)
        buf = io.StringIO()
        df.to_csv(buf, index=False, encoding="utf-8-sig")
        return buf.getvalue().encode("utf-8-sig")

    def papers_to_markdown(self, papers: list[dict[str, Any]]) -> str:
        lines = ["# Chemistry Discovery Hub — Literature Results\n"]
        for i, p in enumerate(papers, 1):
            doi = p.get("doi", "")
            pmid = p.get("pmid", "")
            authors = "; ".join(p.get("authors", []))
            sources = ", ".join(p.get("sources") or ([p["source"]] if p.get("source") else []))
            lines.append(f"## {i}. {p.get('title', 'No title')}\n")
            lines.append(f"**Authors:** {authors}  ")
            lines.append(f"**Journal:** {p.get('journal', '')} ({p.get('year', '')})  ")
            if sources:
                lines.append(f"**Sources:** {sources}  ")
            if doi:
                lines.append(f"**DOI:** [{doi}](https://doi.org/{doi})  ")
                lines.append(f"**SciFinder-n:** [View]({scifinder_doi_url(doi)})  ")
            if pmid:
                lines.append(f"**PMID:** [{pmid}](https://pubmed.ncbi.nlm.nih.gov/{pmid}/)  ")
            abstract = p.get("abstract", "")
            if abstract:
                lines.append(f"\n> {abstract[:500]}{'...' if len(abstract) > 500 else ''}")
            lines.append("\n---\n")
        return "\n".join(lines)

    # ── Compounds (merged / formula results) ─────────────────────────────────

    def compounds_to_dataframe(
        self,
        compounds: list[dict[str, Any]],
        chembl_map: dict[str, dict[str, Any]] | None = None,
    ) -> pd.DataFrame:
        chembl_map = chembl_map or {}
        rows = []
        for c in compounds:
            pubchem = c.get("pubchem") or {}
            lotus = c.get("lotus") or {}
            coconut = c.get("coconut") or {}
            ik = c.get("inchikey", "")
            name = c.get("name", "")
            chembl_entry = chembl_map.get(ik or name, {})

            org_parts = []
            for o in c.get("organisms", []):
                oname = o.get("name", "")
                odoi = o.get("doi", "")
                org_parts.append(f"{oname} [{odoi}]" if odoi else oname)

            activities = "; ".join(
                f"{a.get('type','')} {a.get('relation','')}{a.get('value','')} {a.get('units','')} ({a.get('target','')})"
                for a in chembl_entry.get("activities", [])
            )

            rows.append({
                "Name": name,
                "InChIKey": ik,
                "Formula": c.get("formula", ""),
                "Mol_Weight": c.get("mol_weight", ""),
                "CAS": c.get("cas", ""),
                "SMILES": c.get("smiles", ""),
                "Sources": "; ".join(c.get("sources", [])),
                "PubChem_CID": pubchem.get("cid", ""),
                "LOTUS_ID": lotus.get("lotus_id", ""),
                "COCONUT_ID": coconut.get("coconut_id", ""),
                "COCONUT_Org_Count": coconut.get("organism_count", ""),
                "COCONUT_Cit_Count": coconut.get("citation_count", ""),
                "LOTUS_Organisms_DOIs": "; ".join(org_parts),
                "ChEMBL_ID": chembl_entry.get("chembl_id", ""),
                "ChEMBL_Match": chembl_entry.get("match_type", ""),
                "Bioactivities": activities,
                "PubChem_URL": pubchem.get("pubchem_url", ""),
                "LOTUS_URL": lotus.get("lotus_url", "") or lotus.get("wikidata_url", ""),
                "COCONUT_URL": coconut.get("coconut_url", ""),
                "SciFinder_URL": scifinder_substance_url(c.get("cas") or name or ik),
                "Notes": "; ".join(c.get("attribution_notes", [])),
            })
        return pd.DataFrame(rows)

    def compounds_to_csv(
        self,
        compounds: list[dict[str, Any]],
        chembl_map: dict[str, dict[str, Any]] | None = None,
    ) -> bytes:
        df = self.compounds_to_dataframe(compounds, chembl_map=chembl_map)
        buf = io.StringIO()
        df.to_csv(buf, index=False, encoding="utf-8-sig")
        return buf.getvalue().encode("utf-8-sig")

    def compounds_to_markdown(
        self,
        compounds: list[dict[str, Any]],
        chembl_map: dict[str, dict[str, Any]] | None = None,
    ) -> str:
        chembl_map = chembl_map or {}
        lines = ["# Chemistry Discovery Hub — Compound Results\n"]
        for i, c in enumerate(compounds, 1):
            name = c.get("name", "Unnamed")
            ik = c.get("inchikey", "")
            pubchem = c.get("pubchem") or {}
            lotus = c.get("lotus") or {}
            coconut = c.get("coconut") or {}
            lines.append(f"## {i}. {name}\n")
            lines.append(f"- **Sources:** {', '.join(c.get('sources', []))}")
            if ik:
                lines.append(f"- **InChIKey:** `{ik}`")
            if c.get("formula"):
                lines.append(f"- **Formula:** {c['formula']}  **MW:** {c.get('mol_weight', '')}")
            if c.get("cas"):
                lines.append(f"- **CAS:** {c['cas']}")
            if c.get("smiles"):
                lines.append(f"- **SMILES:** `{c['smiles']}`")
            if pubchem.get("pubchem_url"):
                lines.append(f"- **PubChem:** [{pubchem.get('cid')}]({pubchem['pubchem_url']})")
            if lotus.get("lotus_url"):
                lines.append(f"- **LOTUS:** [{lotus.get('lotus_id')}]({lotus['lotus_url']})")
            if coconut.get("coconut_url"):
                lines.append(
                    f"- **COCONUT:** [{coconut.get('coconut_id')}]({coconut['coconut_url']}) "
                    f"(org_count={coconut.get('organism_count', '')}, cit_count={coconut.get('citation_count', '')} — M:N参考)"
                )
            if c.get("organisms"):
                lines.append("- **Source Organisms (LOTUS):**")
                for o in c["organisms"][:15]:
                    d = o.get("doi", "")
                    lines.append(f"  - *{o.get('name', '')}*" + (f" (DOI: https://doi.org/{d})" if d else ""))
            chembl_entry = chembl_map.get(ik or name)
            if chembl_entry and chembl_entry.get("activities"):
                lines.append(f"- **ChEMBL ({chembl_entry.get('chembl_id')} / {chembl_entry.get('match_type')}):**")
                for a in chembl_entry["activities"][:10]:
                    lines.append(f"  - {a.get('type')} {a.get('relation','')}{a.get('value')} {a.get('units')} — {a.get('target')}")
            lines.append("\n---\n")
        return "\n".join(lines)

    # ── Taxon Compounds (LOTUS Wikidata) ─────────────────────────────────────

    def taxon_compounds_to_dataframe(self, items: list[dict[str, Any]]) -> pd.DataFrame:
        rows = []
        for it in items:
            doi = it.get("doi", "")
            name = it.get("name", "")
            ik = it.get("inchikey", "")
            rows.append({
                "Taxon": it.get("taxon", ""),
                "Compound_Name": name,
                "Formula": it.get("formula", ""),
                "InChIKey": ik,
                "SMILES": it.get("smiles", ""),
                "Reference_DOI": doi,
                "DOI_URL": f"https://doi.org/{doi}" if doi else "",
                "Wikidata_URL": it.get("wikidata_url", ""),
                "SciFinder_URL": scifinder_substance_url(name or ik),
                "Source": it.get("source", "LOTUS"),
            })
        return pd.DataFrame(rows)

    def taxon_compounds_to_csv(self, items: list[dict[str, Any]]) -> bytes:
        df = self.taxon_compounds_to_dataframe(items)
        buf = io.StringIO()
        df.to_csv(buf, index=False, encoding="utf-8-sig")
        return buf.getvalue().encode("utf-8-sig")
