"""
Journal Fetcher — Scrapling-based scraper for Planta Medica, NPR, and MDPI journals.
Uses StealthyFetcher to bypass bot-detection, with adaptive CSS matching.
"""
from __future__ import annotations

import re
from typing import Any

import requests
from bs4 import BeautifulSoup

# Try to import Scrapling; fall back to requests+BeautifulSoup if unavailable.
try:
    from scrapling import StealthyFetcher as _ScraplingFetcher
    _SCRAPLING_AVAILABLE = True
except ImportError:
    try:
        from scrapling.fetchers import StealthyFetcher as _ScraplingFetcher
        _SCRAPLING_AVAILABLE = True
    except ImportError:
        _SCRAPLING_AVAILABLE = False
        print("[JournalFetcher] Scrapling not installed — falling back to requests.")


# ── Target journal configurations ────────────────────────────────────────────

JOURNAL_CONFIGS: dict[str, dict] = {
    "planta_medica": {
        "name":       "Planta Medica",
        "search_url": "https://www.thieme-connect.de/products/ejournals/issue/10.1055/s-00000058",
        "query_url":  "https://www.thieme-connect.de/products/ejournals/html/10.1055/s-00000058?query={query}",
        "selectors": {
            "article":  ".articleListing__item, .article-listing-item",
            "title":    ".articleTitle, h3.title, .article-title",
            "authors":  ".authorList, .authors",
            "doi":      "[data-doi], .doi",
            "abstract": ".abstractSection, .abstract-text",
        },
    },
    "natural_product_research": {
        "name":       "Natural Product Research",
        "search_url": "https://www.tandfonline.com/action/doSearch?journalCode=gnpl20&query={query}",
        "selectors": {
            "article":  ".articleEntry, .search-result-item",
            "title":    ".art_title, h3 a",
            "authors":  ".entryAuthor, .authors",
            "doi":      "[data-doi], .DOI",
            "abstract": ".abstract, .hlFld-Abstract",
        },
    },
    "molecules": {
        "name":       "Molecules (MDPI)",
        "search_url": "https://www.mdpi.com/search?journal=molecules&q={query}",
        "selectors": {
            "article":  "article.article-item, .article-content",
            "title":    "h2.title a, .article-title a",
            "authors":  ".article-authors, .authors",
            "doi":      ".doi, [href*='doi.org']",
            "abstract": ".abstract-full, p.abstract",
        },
    },
    "marine_drugs": {
        "name":       "Marine Drugs (MDPI)",
        "search_url": "https://www.mdpi.com/search?journal=marinedrugs&q={query}",
        "selectors": {
            "article":  "article.article-item, .article-content",
            "title":    "h2.title a, .article-title a",
            "authors":  ".article-authors, .authors",
            "doi":      ".doi, [href*='doi.org']",
            "abstract": ".abstract-full, p.abstract",
        },
    },
}


class JournalFetcher:
    """Scrape journal websites using Scrapling StealthyFetcher (or requests fallback)."""

    def __init__(self):
        if _SCRAPLING_AVAILABLE:
            self._use_scrapling = True
        else:
            self._use_scrapling = False
            self.session = requests.Session()
            self.session.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            })

    def search(
        self,
        query: str,
        journals: list[str] | None = None,
        max_per_journal: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Scrape one or more journals for the given query.

        Args:
            query:            Search keyword.
            journals:         List of journal keys (from JOURNAL_CONFIGS).
                              Defaults to all available journals.
            max_per_journal:  Max results per journal.
        Returns:
            Combined list of paper dicts.
        """
        if journals is None:
            journals = list(JOURNAL_CONFIGS.keys())

        papers: list[dict[str, Any]] = []
        for journal_key in journals:
            cfg = JOURNAL_CONFIGS.get(journal_key)
            if not cfg:
                continue
            results = self._scrape_journal(query, cfg, max_per_journal)
            papers.extend(results)

        return papers

    def get_available_journals(self) -> dict[str, str]:
        """Return dict of {key: display_name} for all configured journals."""
        return {k: v["name"] for k, v in JOURNAL_CONFIGS.items()}

    # ── Private helpers ──────────────────────────────────────────────────────

    def _scrape_journal(
        self,
        query: str,
        cfg: dict,
        max_results: int,
    ) -> list[dict[str, Any]]:
        url = cfg["search_url"].format(query=requests.utils.quote(query))

        try:
            html = self._fetch_html(url)
            if not html:
                return []
            return self._parse_html(html, cfg, max_results)
        except Exception as exc:
            print(f"[JournalFetcher] Error scraping {cfg['name']}: {exc}")
            return []

    def _fetch_html(self, url: str) -> str:
        if self._use_scrapling:
            try:
                page = _ScraplingFetcher.fetch(
                    url,
                    headless=True,
                    network_idle=True,
                    block_webrtc=True,
                )
                return page.html_content if hasattr(page, "html_content") else str(page)
            except Exception as exc:
                print(f"[JournalFetcher] Scrapling error, falling back to requests: {exc}")

        # Fallback to plain requests
        resp = self.session.get(url, timeout=20)
        resp.raise_for_status()
        return resp.text

    def _parse_html(
        self,
        html: str,
        cfg: dict,
        max_results: int,
    ) -> list[dict[str, Any]]:
        soup    = BeautifulSoup(html, "lxml")
        sel     = cfg["selectors"]
        papers: list[dict[str, Any]] = []

        # Try each article selector variant (comma-separated → multiple attempts)
        articles = []
        for article_sel in sel["article"].split(","):
            articles = soup.select(article_sel.strip())
            if articles:
                break

        for article in articles[:max_results]:
            title    = self._extract_text(article, sel.get("title", ""))
            authors  = self._extract_text(article, sel.get("authors", ""))
            doi      = self._extract_doi(article, sel.get("doi", ""))
            abstract = self._extract_text(article, sel.get("abstract", ""))

            if not title or title.lower() in ("", "no title"):
                continue

            papers.append({
                "title":    title,
                "authors":  [a.strip() for a in re.split(r"[,;]", authors) if a.strip()],
                "doi":      doi,
                "pmid":     "",
                "abstract": abstract,
                "journal":  cfg["name"],
                "year":     self._extract_year(article),
                "keywords": [],
                "source":   "Scrapling",
            })

        return papers

    def _extract_text(self, el: Any, selectors: str) -> str:
        for sel in selectors.split(","):
            found = el.select_one(sel.strip())
            if found:
                return found.get_text(separator=" ", strip=True)
        return ""

    def _extract_doi(self, el: Any, selectors: str) -> str:
        for sel in selectors.split(","):
            found = el.select_one(sel.strip())
            if not found:
                continue
            # Check data-doi attribute
            doi = found.get("data-doi", "")
            if doi:
                return doi
            # Check href
            href = found.get("href", "")
            m = re.search(r"10\.\d{4,}/[^\s\"']+", href)
            if m:
                return m.group(0)
            # Check text content
            m = re.search(r"10\.\d{4,}/[^\s\"']+", found.get_text())
            if m:
                return m.group(0)
        return ""

    def _extract_year(self, el: Any) -> str:
        text = el.get_text()
        m = re.search(r"\b(19|20)\d{2}\b", text)
        return m.group(0) if m else ""
