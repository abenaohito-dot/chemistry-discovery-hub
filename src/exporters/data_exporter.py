"""Data Exporter — CSV and Markdown export for papers and compounds."""
from __future__ import annotations
from typing import Any
import io
import pandas as pd


class DataExporter:

    # ── Papers ───────────────────────────────────────────────────────────────

    def papers_to_dataframe(self, papers: list[dict[str, Any]]) -> pd.DataFrame:
        rows = []
        for p in papers:
            authors = "; ".join(p.get("authors", []))
            keywords = "; ".join(p.get("keywords", []))
            doi = p.get("doi", "")
            scifinder_url = (
                f"https://scifinder-n.cas.org/searchRedirect?redirectUrl="
                f"https%3A%2F%2Fdoi.org%2F{doi}" if doi else ""
            )
            rows.append({
                "Title":           p.get("title", ""),
                "Authors":         authors,
                "Journal":         p.get("journal", ""),
                "Year":            p.get("year", ""),
                "DOI":             doi,
                "PMID":            p.get("pmid", ""),
                "Abstract":        p.get("abstract", ""),
                "Keywords":        keywords,
                "Citations":       p.get("citations", ""),
                "Source":          p.get("source", ""),
                "SciFinder_URL":   scifinder_url,
            })
        return pd.DataFrame(rows)

    def papers_to_csv(self, papers: list[dict[str, Any]]) -> bytes:
        df = self.papers_to_dataframe(papers)
        buf = io.StringIO()
        df.to_csv(buf, index=False, encoding="utf-8-sig")
        return buf.getvalue().encode("utf-8-sig")

    def papers_to_markdown(self, papers: list[dict[str, Any]]) -> str:
        lines = ["# Chemistry Discovery Hub — Search Results\n"]
        for i, p in enumerate(papers, 1):
            doi  = p.get("doi", "")
            pmid = p.get("pmid", "")
            authors = "; ".join(p.get("authors", []))
            scifinder_url = (
                f"https://scifinder-n.cas.org/searchRedirect?redirectUrl="
                f"https%3A%2F%2Fdoi.org%2F{doi}" if doi else ""
            )
            lines.append(f"## {i}. {p.get('title', 'No title')}\n")
            lines.append(f"**Authors:** {authors}  ")
            lines.append(f"**Journal:** {p.get('journal', '')} ({p.get('year', '')})  ")
            if doi:
                lines.append(f"**DOI:** [{doi}](https://doi.org/{doi})  ")
            if pmid:
                lines.append(f"**PMID:** [{pmid}](https://pubmed.ncbi.nlm.nih.gov/{pmid}/)  ")
            if scifinder_url:
                lines.append(f"**SciFinder-n:** [View]({scifinder_url})  ")
            abstract = p.get("abstract", "")
            if abstract:
                lines.append(f"\n> {abstract[:500]}{'...' if len(abstract) > 500 else ''}")
            lines.append("\n---\n")
        return "\n".join(lines)

    # ── Compounds ────────────────────────────────────────────────────────────

    def compounds_to_dataframe(self, compounds: list[dict[str, Any]]) -> pd.DataFrame:
        rows = []
        for c in compounds:
            pubchem = c.get("pubchem", {}) or {}
            lotus   = c.get("lotus", {}) or {}
            chembl  = c.get("chembl", {}) or {}

            organisms = "; ".join(
                o.get("name", "") for o in lotus.get("organisms", [])
            )
            activities = "; ".join(
                f"{a['type']} {a['value']} {a['units']} ({a['target']})"
                for a in chembl.get("activities", [])
            )

            rows.append({
                "Name":          c.get("name", ""),
                "Confidence":    c.get("confidence", ""),
                "CAS":           pubchem.get("cas", ""),
                "Formula":       pubchem.get("formula", ""),
                "Mol_Weight":    pubchem.get("mol_weight", ""),
                "InChIKey":      pubchem.get("inchikey", ""),
                "SMILES":        pubchem.get("smiles", ""),
                "PubChem_CID":   pubchem.get("cid", ""),
                "COCONUT_ID":    c.get("coconut", {}).get("coconut_id", "") if c.get("coconut") else "",
                "ChEMBL_ID":     chembl.get("chembl_id", ""),
                "Source_Organisms": organisms,
                "Bioactivities": activities,
                "PubChem_URL":   pubchem.get("pubchem_url", ""),
                "ChEMBL_URL":    chembl.get("chembl_url", ""),
            })
        return pd.DataFrame(rows)

    def compounds_to_csv(self, compounds: list[dict[str, Any]]) -> bytes:
        df = self.compounds_to_dataframe(compounds)
        buf = io.StringIO()
        df.to_csv(buf, index=False, encoding="utf-8-sig")
        return buf.getvalue().encode("utf-8-sig")
