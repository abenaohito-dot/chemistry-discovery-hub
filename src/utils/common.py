"""Shared data models, identifier normalizers, RDKit SVG rendering, and merge helpers."""
from __future__ import annotations

import re
import urllib.parse
from dataclasses import asdict, dataclass, field
import hashlib
from typing import Any, Callable, Literal

import requests
from rdkit import Chem
from rdkit.Chem import rdMolDescriptors
from rdkit.Chem.Draw import rdMolDraw2D

from src.utils.cache import CACHEABLE_STATUSES, SQLiteCache

StatusType = Literal["ok", "empty", "truncated", "timeout", "rate_limited", "error"]

_SUBSCRIPT_TRANS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
_CAS_RE = re.compile(r"^(\d{2,7})-(\d{2})-(\d)$")
_INCHIKEY_RE = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")


@dataclass
class QueryResult:
    """Unified response envelope distinguishing success, empty, truncation, and failure."""

    source: str
    status: StatusType
    items: list[dict[str, Any]] = field(default_factory=list)
    total_count: int | None = None
    truncated: bool = False
    message: str = ""
    from_cache: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any], from_cache: bool = True) -> "QueryResult":
        return cls(
            source=data.get("source", ""),
            status=data.get("status", "error"),
            items=data.get("items", []),
            total_count=data.get("total_count"),
            truncated=bool(data.get("truncated", False)),
            message=data.get("message", ""),
            from_cache=from_cache,
        )


# ── Normalizers & Validators ─────────────────────────────────────────────────


def normalize_doi(doi: str) -> str:
    """Strip common URL/prefix wrappers and lowercase a DOI."""
    if not doi:
        return ""
    s = doi.strip()
    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
        "doi:",
    ):
        if s.lower().startswith(prefix):
            s = s[len(prefix):]
            break
    return s.strip().lower()


def normalize_formula(formula: str) -> str:
    """Convert Unicode subscripts to ASCII digits and remove spaces."""
    if not formula:
        return ""
    return re.sub(r"\s+", "", formula.translate(_SUBSCRIPT_TRANS)).strip()


def is_cas_number(text: str) -> bool:
    """Validate CAS Registry Number format and check digit."""
    m = _CAS_RE.match(text.strip())
    if not m:
        return False
    digits = m.group(1) + m.group(2)
    check = int(m.group(3))
    total = sum(int(ch) * idx for idx, ch in enumerate(reversed(digits), start=1))
    return (total % 10) == check


def is_inchikey(text: str) -> bool:
    """Check strict 27-character standard InChIKey format."""
    return bool(_INCHIKEY_RE.match(text.strip().upper()))


# ── RDKit Chemistry Utilities ────────────────────────────────────────────────


def smiles_to_props(smiles: str) -> tuple[str, str]:
    """Compute (27-char InChIKey, molecular_formula) from SMILES using RDKit."""
    if not smiles:
        return "", ""
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return "", ""
        ik = Chem.MolToInchiKey(mol) or ""
        mf = rdMolDescriptors.CalcMolFormula(mol) or ""
        return ik.upper(), mf
    except Exception:
        return "", ""


def render_smiles_svg(smiles: str, width: int = 240, height: int = 165) -> str | None:
    """Render 2D chemical structure SVG string from SMILES via RDKit."""
    if not smiles:
        return None
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None
        drawer = rdMolDraw2D.MolDraw2DSVG(width, height)
        opts = drawer.drawOptions()
        opts.clearBackground = False
        drawer.DrawMolecule(mol)
        drawer.FinishDrawing()
        svg = drawer.GetDrawingText()
        # Ensure responsive sizing inside HTML cards
        svg = re.sub(r"<\?xml[^>]*\?>", "", svg).strip()
        return svg
    except Exception:
        return None


# ── SciFinder-n External Link Helpers (preserved) ────────────────────────────


def scifinder_doi_url(doi: str) -> str:
    encoded = urllib.parse.quote(f"https://doi.org/{doi}", safe="")
    return f"https://scifinder-n.cas.org/searchRedirect?redirectUrl={encoded}"


def scifinder_substance_url(term: str) -> str:
    q = urllib.parse.quote(term)
    return f'https://scifinder-n.cas.org/search#search/{{"queryType":"substance","query":"{q}"}}'


# ── Deduplication & Merge Helpers ────────────────────────────────────────────


def merge_papers(results: list[QueryResult]) -> list[dict[str, Any]]:
    """
    Merge literature QueryResults by normalized DOI (or normalized title fallback).
    Preserves all contributing source database names and fills missing metadata.
    """
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for qr in results:
        for raw in qr.items:
            doi = normalize_doi(raw.get("doi", ""))
            title = (raw.get("title") or "").strip()
            title_key = re.sub(r"[^a-z0-9]+", "", title.lower())[:90]
            key = f"doi:{doi}" if doi else f"title:{title_key}"
            if not key or key in ("doi:", "title:"):
                continue

            src = raw.get("source") or qr.source
            if key not in merged:
                item = dict(raw)
                item["doi"] = doi
                item["sources"] = [src] if src else []
                merged[key] = item
                order.append(key)
            else:
                cur = merged[key]
                if src and src not in cur["sources"]:
                    cur["sources"].append(src)
                if not cur.get("abstract") and raw.get("abstract"):
                    cur["abstract"] = raw["abstract"]
                if not cur.get("pmid") and raw.get("pmid"):
                    cur["pmid"] = raw["pmid"]
                if not cur.get("journal") and raw.get("journal"):
                    cur["journal"] = raw["journal"]
                if not cur.get("year") and raw.get("year"):
                    cur["year"] = raw["year"]
                if not cur.get("authors") and raw.get("authors"):
                    cur["authors"] = raw["authors"]
                if not cur.get("fulltext_url") and raw.get("fulltext_url"):
                    cur["fulltext_url"] = raw["fulltext_url"]
                # Keep highest citation count observed
                try:
                    c_cur = int(cur.get("citations") or 0)
                    c_new = int(raw.get("citations") or 0)
                    if c_new > c_cur:
                        cur["citations"] = c_new
                except (ValueError, TypeError):
                    pass
                # Merge keywords cleanly
                existing_kw = {k.lower() for k in cur.get("keywords", [])}
                for kw in raw.get("keywords", []):
                    if kw and kw.lower() not in existing_kw:
                        cur.setdefault("keywords", []).append(kw)
                        existing_kw.add(kw.lower())

    return [merged[k] for k in order]


def merge_compounds(results: list[QueryResult]) -> list[dict[str, Any]]:
    """
    Merge compound records ONLY when 27-character InChIKey matches identically.
    Records with empty or differing InChIKeys are NEVER merged even if names match.
    """
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    unmerged_seq = 0

    for qr in results:
        for raw in qr.items:
            ik = (raw.get("inchikey") or "").strip().upper()
            src = raw.get("source") or qr.source

            if is_inchikey(ik):
                key = f"ik:{ik}"
            else:
                unmerged_seq += 1
                key = f"unmerged:{unmerged_seq}:{src}"

            if key not in merged:
                rec = {
                    "inchikey": ik if is_inchikey(ik) else "",
                    "name": (raw.get("name") or "").strip(),
                    "iupac_name": raw.get("iupac_name", ""),
                    "formula": normalize_formula(raw.get("formula", "")),
                    "mol_weight": raw.get("mol_weight", ""),
                    "smiles": raw.get("smiles", ""),
                    "cas": raw.get("cas", ""),
                    "sources": [src] if src else [],
                    "pubchem": raw.get("pubchem") or (dict(raw) if src == "PubChem" else None),
                    "lotus": raw.get("lotus") or (dict(raw) if src == "LOTUS" else None),
                    "coconut": raw.get("coconut") or (dict(raw) if src == "COCONUT" else None),
                    "organisms": list(raw.get("organisms", [])),
                    "attribution_notes": [raw["attribution_note"]] if raw.get("attribution_note") else [],
                }
                merged[key] = rec
                order.append(key)
            else:
                rec = merged[key]
                if src and src not in rec["sources"]:
                    rec["sources"].append(src)
                if not rec["name"] and raw.get("name"):
                    rec["name"] = raw["name"].strip()
                if not rec["iupac_name"] and raw.get("iupac_name"):
                    rec["iupac_name"] = raw["iupac_name"]
                if not rec["formula"] and raw.get("formula"):
                    rec["formula"] = normalize_formula(raw["formula"])
                if not rec["mol_weight"] and raw.get("mol_weight"):
                    rec["mol_weight"] = raw["mol_weight"]
                if not rec["smiles"] and raw.get("smiles"):
                    rec["smiles"] = raw["smiles"]
                if not rec["cas"] and raw.get("cas"):
                    rec["cas"] = raw["cas"]

                if src == "PubChem" or raw.get("pubchem"):
                    rec["pubchem"] = raw.get("pubchem") or dict(raw)
                if src == "LOTUS" or raw.get("lotus"):
                    rec["lotus"] = raw.get("lotus") or dict(raw)
                if src == "COCONUT" or raw.get("coconut"):
                    rec["coconut"] = raw.get("coconut") or dict(raw)

                # Merge organisms (dedup by name + doi)
                seen_org = {(o.get("name", ""), o.get("doi", "")) for o in rec["organisms"]}
                for o in raw.get("organisms", []):
                    sig = (o.get("name", ""), o.get("doi", ""))
                    if sig not in seen_org:
                        rec["organisms"].append(o)
                        seen_org.add(sig)

                note = raw.get("attribution_note")
                if note and note not in rec["attribution_notes"]:
                    rec["attribution_notes"].append(note)

    return [merged[k] for k in order]


# ── Shared Cache & HTTP Error Helpers ────────────────────────────────────────


def make_cache_key(prefix: str, *parts: Any) -> str:
    """Build deterministic compact cache key."""
    raw = "|".join(str(p) for p in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}:{digest}"


def cached_query(
    cache: SQLiteCache | None,
    key: str,
    ttl_seconds: int,
    fn: Callable[[], QueryResult],
) -> QueryResult:
    """Execute query with persistent SQLite caching for valid non-error responses."""
    if cache is not None:
        hit = cache.get(key)
        if isinstance(hit, dict):
            return QueryResult.from_dict(hit, from_cache=True)

    result = fn()
    if cache is not None and result.status in CACHEABLE_STATUSES:
        cache.set(key, result.to_dict(), ttl_seconds=ttl_seconds)
    return result


def classify_request_error(source: str, exc: Exception, hint: str = "") -> QueryResult:
    """Map requests/network exceptions to explicit QueryResult error statuses."""
    if isinstance(exc, requests.Timeout):
        msg = f"{source}: タイムアウト"
        return QueryResult(source=source, status="timeout", message=msg)
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        code = exc.response.status_code
        if code == 429:
            msg = f"{source}: レート制限 (HTTP 429)" + (f" — {hint}" if hint else "")
            return QueryResult(source=source, status="rate_limited", message=msg)
        return QueryResult(source=source, status="error", message=f"{source}: HTTP {code}")
    return QueryResult(source=source, status="error", message=f"{source}: 取得失敗 ({type(exc).__name__})")

