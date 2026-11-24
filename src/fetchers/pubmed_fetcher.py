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

from src.utils.cache import SQLiteCache, TTL_LITERATURE_SECONDS
from src.utils.common import (
    QueryResult,
    cached_query,
    classify_request_error,
    make_cache_key,
    normalize_doi,
)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


class PubMedFetcher:
    """Fetch literature metadata from PubMed via NCBI E-utilities."""

    def __init__(self, cache: SQLiteCache | None = None):
        self.cache = cache
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "ChemistryDiscoveryHub/2.0"})

    def search(self, query: str, max_results: int = 20) -> QueryResult:
        """Search PubMed and return a QueryResult containing parsed papers."""
        q = query.strip()
        if not q:
            return QueryResult(source="PubMed", status="empty")

        limit = max(1, min(int(max_results), 100))
        key = make_cache_key("pubmed", q, limit)

        def _fetch() -> QueryResult:
            api_key = os.getenv("NCBI_API_KEY", "").strip()
            delay = 0.11 if api_key else 0.34
            try:
                total, pmids = self._esearch(q, limit, api_key)
                if not pmids:
                    return QueryResult(source="PubMed", status="empty", total_count=0)
                time.sleep(delay)
                papers = self._efetch(pmids, api_key)
            except Exception as exc:
                return classify_request_error("PubMed", exc)

            if not papers:
                return QueryResult(source="PubMed", status="empty", total_count=0)

            truncated = total > len(papers)
            status = "truncated" if truncated else "ok"
            msg = f"{len(papers)} / {total} 件表示" if truncated else f"{len(papers)} 件"
            return QueryResult(
                source="PubMed",
                status=status,
                items=papers,
                total_count=total,
                truncated=truncated,
                message=msg,
            )

        return cached_query(self.cache, key, TTL_LITERATURE_SECONDS, _fetch)

    def _esearch(self, query: str, retmax: int, api_key: str) -> tuple[int, list[str]]:
        params: dict[str, Any] = {
            "db": "pubmed",
            "term": query,
            "retmax": retmax,
            "retmode": "json",
            "sort": "relevance",
        }
        if api_key:
            params["api_key"] = api_key

        resp = self.session.get(ESEARCH_URL, params=params, timeout=15)
        resp.raise_for_status()
        res = resp.json().get("esearchresult", {})
        return int(res.get("count") or 0), res.get("idlist", [])

    def _efetch(self, pmids: list[str], api_key: str) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
            "rettype": "abstract",
        }
        if api_key:
            params["api_key"] = api_key

        resp = self.session.get(EFETCH_URL, params=params, timeout=25)
        resp.raise_for_status()
        return self._parse_xml(resp.text)

    def _parse_xml(self, xml_text: str) -> list[dict[str, Any]]:
        papers: list[dict[str, Any]] = []
        root = ET.fromstring(xml_text)
        for article in root.findall(".//PubmedArticle"):
            papers.append(self._parse_article(article))
        return papers

    def _parse_article(self, article: ET.Element) -> dict[str, Any]:
        medline = article.find("MedlineCitation")
        art = medline.find("Article") if medline is not None else None

        pmid_el = medline.find("PMID") if medline is not None else None
        pmid = pmid_el.text if pmid_el is not None and pmid_el.text else ""

        title_el = art.find("ArticleTitle") if art is not None else None
        title = "".join(title_el.itertext()) if title_el is not None else "No title"

        authors: list[str] = []
        author_list = art.find("AuthorList") if art is not None else None
        if author_list is not None:
            for author in author_list.findall("Author"):
                last = author.findtext("LastName", "")
                init = author.findtext("Initials", "")
                if last:
                    authors.append(f"{last} {init}".strip())

        journal_el = art.find("Journal") if art is not None else None
        journal = ""
        year = ""
        if journal_el is not None:
            journal = journal_el.findtext("Title", "") or journal_el.findtext("ISOAbbreviation", "")
            pub_date = journal_el.find("JournalIssue/PubDate")
            if pub_date is not None:
                year = pub_date.findtext("Year", "") or pub_date.findtext("MedlineDate", "")[:4]

        abstract_parts: list[str] = []
        abstract_el = art.find("Abstract") if art is not None else None
        if abstract_el is not None:
            for text_el in abstract_el.findall("AbstractText"):
                label = text_el.get("Label", "")
                text = "".join(text_el.itertext())
                abstract_parts.append(f"{label}: {text}" if label else text)
        abstract = " ".join(abstract_parts)

        doi = ""
        id_list = article.find(".//ArticleIdList")
        if id_list is not None:
            for aid in id_list.findall("ArticleId"):
                if aid.get("IdType") == "doi" and aid.text:
                    doi = normalize_doi(aid.text)
                    break

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
            "title": title,
            "authors": authors,
            "doi": doi,
            "pmid": pmid,
            "abstract": abstract,
            "journal": journal,
            "year": year,
            "keywords": keywords,
            "source": "PubMed",
        }
