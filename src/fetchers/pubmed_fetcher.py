"""
PubMed Fetcher — NCBI E-utilities API
Retrieves papers from PubMed with title, authors, DOI, abstract, MeSH terms.
"""
from __future__ import annotations

import os
import time
import xml.etree.ElementTree as ET
from typing import Any

import requests
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

NCBI_API_KEY = os.getenv("NCBI_API_KEY", "")
# Rate: 10 req/s with key, 3 req/s without
_RATE_DELAY  = 0.11 if NCBI_API_KEY else 0.34


class PubMedFetcher:
    """Fetch literature metadata from PubMed via NCBI E-utilities."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "ChemistryDiscoveryHub/1.0"})

    def search(self, query: str, max_results: int = 20) -> list[dict[str, Any]]:
        """
        Search PubMed and return a list of paper dicts.

        Args:
            query:       PubMed search string (supports MeSH terms, field tags, etc.)
            max_results: Maximum number of records to retrieve.

        Returns:
            List of dicts with keys: title, authors, doi, abstract, journal,
            year, pmid, keywords, source.
        """
        pmids = self._esearch(query, max_results)
        if not pmids:
            return []
        time.sleep(_RATE_DELAY)
        return self._efetch(pmids)

    # ── Private helpers ──────────────────────────────────────────────────────

    def _esearch(self, query: str, retmax: int) -> list[str]:
        params: dict[str, Any] = {
            "db": "pubmed",
            "term": query,
            "retmax": retmax,
            "retmode": "json",
            "sort": "relevance",
        }
        if NCBI_API_KEY:
            params["api_key"] = NCBI_API_KEY

        try:
            resp = self.session.get(ESEARCH_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            return data.get("esearchresult", {}).get("idlist", [])
        except Exception as exc:
            print(f"[PubMed] esearch error: {exc}")
            return []

    def _efetch(self, pmids: list[str]) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
            "rettype": "abstract",
        }
        if NCBI_API_KEY:
            params["api_key"] = NCBI_API_KEY

        try:
            resp = self.session.get(EFETCH_URL, params=params, timeout=30)
            resp.raise_for_status()
            return self._parse_xml(resp.text)
        except Exception as exc:
            print(f"[PubMed] efetch error: {exc}")
            return []

    def _parse_xml(self, xml_text: str) -> list[dict[str, Any]]:
        papers: list[dict[str, Any]] = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            print(f"[PubMed] XML parse error: {exc}")
            return papers

        for article in root.findall(".//PubmedArticle"):
            papers.append(self._parse_article(article))

        return papers

    def _parse_article(self, article: ET.Element) -> dict[str, Any]:
        medline = article.find("MedlineCitation")
        art     = medline.find("Article") if medline is not None else None

        # PMID
        pmid_el = medline.find("PMID") if medline is not None else None
        pmid    = pmid_el.text if pmid_el is not None else ""

        # Title
        title_el = art.find("ArticleTitle") if art is not None else None
        title    = "".join(title_el.itertext()) if title_el is not None else "No title"

        # Authors
        authors: list[str] = []
        author_list = art.find("AuthorList") if art is not None else None
        if author_list is not None:
            for author in author_list.findall("Author"):
                last  = author.findtext("LastName", "")
                init  = author.findtext("Initials", "")
                if last:
                    authors.append(f"{last} {init}".strip())

        # Journal & Year
        journal_el = art.find("Journal") if art is not None else None
        journal    = ""
        year       = ""
        if journal_el is not None:
            journal = journal_el.findtext("Title", "") or journal_el.findtext("ISOAbbreviation", "")
            pub_date = journal_el.find("JournalIssue/PubDate")
            if pub_date is not None:
                year = pub_date.findtext("Year", "") or pub_date.findtext("MedlineDate", "")[:4]

        # Abstract
        abstract_parts: list[str] = []
        abstract_el = art.find("Abstract") if art is not None else None
        if abstract_el is not None:
            for text_el in abstract_el.findall("AbstractText"):
                label = text_el.get("Label", "")
                text  = "".join(text_el.itertext())
                abstract_parts.append(f"{label}: {text}" if label else text)
        abstract = " ".join(abstract_parts)

        # DOI
        doi = ""
        id_list = article.find(".//ArticleIdList")
        if id_list is not None:
            for aid in id_list.findall("ArticleId"):
                if aid.get("IdType") == "doi":
                    doi = aid.text or ""
                    break

        # MeSH / Keywords
        keywords: list[str] = []
        mesh_list = medline.find("MeshHeadingList") if medline is not None else None
        if mesh_list is not None:
            for mesh in mesh_list.findall("MeshHeading"):
                desc = mesh.findtext("DescriptorName", "")
                if desc:
                    keywords.append(desc)

        kw_list = medline.find("KeywordList") if medline is not None else None
        if kw_list is not None:
            for kw in kw_list.findall("Keyword"):
                kw_text = "".join(kw.itertext()).strip()
                if kw_text and kw_text not in keywords:
                    keywords.append(kw_text)

        return {
            "title":    title,
            "authors":  authors,
            "doi":      doi,
            "pmid":     pmid,
            "abstract": abstract,
            "journal":  journal,
            "year":     year,
            "keywords": keywords,
            "source":   "PubMed",
        }
