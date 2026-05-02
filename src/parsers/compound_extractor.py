"""
Compound Name Extractor — NER for natural product chemistry compounds.
Uses regex patterns tuned for pharmacognosy terminology.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CompoundMatch:
    name:       str
    confidence: float
    start:      int
    end:        int
    pattern:    str


# ── Regex patterns for natural product compound names ────────────────────────

# Greek-prefixed compounds: α-tocopherol, β-sitosterol, γ-linolenic acid
_GREEK = r"(?:α|β|γ|δ|ε|ζ|η|θ|ι|κ|λ|μ|ξ|π|σ|τ|υ|φ|χ|ψ|ω|alpha|beta|gamma|delta|omega)"

# Known natural product compound classes (high confidence)
_KNOWN_CLASSES = re.compile(
    r"\b(?:"
    # Flavonoids
    r"quercetin|kaempferol|luteolin|apigenin|myricetin|fisetin|rutin|naringenin|"
    r"hesperetin|hesperidin|naringin|catechin|epicatechin|epigallocatechin|EGCG|"
    r"taxifolin|eriodictyol|isorhamnetin|diosmetin|baicalein|baicalin|wogonin|"
    # Terpenoids / Terpenes
    r"limonene|linalool|menthol|camphor|thymol|carvacrol|geraniol|nerol|citral|"
    r"caryophyllene|humulene|bisabolol|borneol|terpineol|pinene|sabinene|"
    r"artemisin|artemisinin|parthenolide|thapsigargin|guaianolide|"
    # Alkaloids
    r"berberine|colchicine|vincristine|vinblastine|morphine|codeine|caffeine|"
    r"theophylline|theobromine|nicotine|piperine|capsaicin|palmatine|"
    r"coptisine|ephedrine|harmine|harmaline|yohimbine|reserpine|quinine|"
    # Stilbenes / Phenolics
    r"resveratrol|pterostilbene|piceatannol|oxyresveratrol|curcumin|"
    r"gallic acid|ellagic acid|protocatechuic acid|caffeic acid|ferulic acid|"
    r"chlorogenic acid|rosmarinic acid|p-coumaric acid|sinapic acid|"
    # Coumarins / Xanthones
    r"coumarin|umbelliferone|esculetin|scopoletin|bergapten|xanthotoxin|"
    r"mangiferin|α-mangostin|β-mangostin|γ-mangostin|"
    # Quinones
    r"emodin|aloe-emodin|chrysophanol|physcion|hypericin|hyperforin|"
    r"plumbagin|juglone|shikonin|naphthazarin|"
    # Saponins / Sterols
    r"β-sitosterol|stigmasterol|campesterol|lanosterol|betulin|betulinic acid|"
    r"ursolic acid|oleanolic acid|glycyrrhizin|ginsenoside|"
    # Lignans
    r"podophyllotoxin|secoisolariciresinol|matairesinol|arctigenin|"
    r"silymarin|silibinin|"
    # Polysaccharides
    r"fucoidan|lentinan|zymosan|arabinoxylan"
    r")\b",
    re.IGNORECASE,
)

# Glycoside / oside pattern: quercetin-3-glucoside, kaempferol-3-rutinoside
_GLYCOSIDE = re.compile(
    r"\b[A-Za-z]{4,}(?:oside|glycoside|rhamnoside|glucoside|galactoside|"
    r"arabinoside|xyloside|mannoside|fructoside|fucoside|rutinoside)\b",
    re.IGNORECASE,
)

# Greek-prefixed: α-linolenic acid, β-carotene
_GREEK_PREFIX = re.compile(
    rf"\b{_GREEK}[-‑]?[A-Za-z]{{3,}}(?:ol|one|ene|ine|ic acid|anol|anone)?\b",
    re.IGNORECASE,
)

# Numbered compound names: Compound 1, compound-2a, Fraction III
_NUMBERED = re.compile(
    r"\b(?:compound|fraction|substance|metabolite|isolate)s?\s*[-–]?\s*"
    r"(?:\d{1,3}[a-z]?|[IVX]{1,4})\b",
    re.IGNORECASE,
)

# General NP suffix pattern: words ending in characteristic suffixes
_SUFFIX = re.compile(
    r"\b[A-Za-z]{4,}(?:lactone|flavone|flavonol|chromone|xanthone|coumarin|"
    r"terpenol|sterol|diterpenoid|triterpenoid|sesquiterpene|diterpene|"
    r"monoterpene|triterpene|tetraterpene|naphthol|phenol)\b",
    re.IGNORECASE,
)

_PATTERNS: list[tuple[str, re.Pattern, float]] = [
    ("known_class",    _KNOWN_CLASSES,  0.95),
    ("glycoside",      _GLYCOSIDE,      0.85),
    ("greek_prefix",   _GREEK_PREFIX,   0.80),
    ("suffix_class",   _SUFFIX,         0.75),
    ("numbered",       _NUMBERED,       0.60),
]

# Common false-positive stopwords to exclude
_STOPWORDS: set[str] = {
    "abstract", "introduction", "method", "methods", "result", "results",
    "conclusion", "discussion", "figure", "table", "supplementary",
    "analysis", "activity", "extract", "fraction", "plant", "species",
    "this", "these", "their", "that", "with", "from", "were", "have",
    "also", "acid",  # "acid" alone is too broad
}


class CompoundExtractor:
    """Extract candidate natural product compound names from free text."""

    def extract(self, text: str) -> list[dict[str, Any]]:
        """
        Extract compound mentions from the given text.

        Args:
            text: Title, abstract, or full text of a paper.
        Returns:
            List of dicts: {name, confidence, pattern}.
            Deduplicated by name (highest confidence kept).
        """
        if not text:
            return []

        seen: dict[str, CompoundMatch] = {}

        for pattern_name, pattern, confidence in _PATTERNS:
            for m in pattern.finditer(text):
                name = m.group(0).strip()
                # Skip short or stopword tokens
                if len(name) < 4 or name.lower() in _STOPWORDS:
                    continue
                # Keep highest-confidence match per name (case-insensitive)
                key = name.lower()
                if key not in seen or seen[key].confidence < confidence:
                    seen[key] = CompoundMatch(
                        name=name,
                        confidence=confidence,
                        start=m.start(),
                        end=m.end(),
                        pattern=pattern_name,
                    )

        # Sort by confidence desc, then alpha
        results = sorted(
            seen.values(),
            key=lambda x: (-x.confidence, x.name.lower()),
        )

        return [
            {
                "name":       r.name,
                "confidence": r.confidence,
                "pattern":    r.pattern,
            }
            for r in results
        ]

    def extract_from_paper(self, paper: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Extract compounds from a paper dict (searches title + abstract + keywords).
        """
        texts = [
            paper.get("title", ""),
            paper.get("abstract", ""),
            " ".join(paper.get("keywords", [])),
        ]
        combined = " ".join(filter(None, texts))
        return self.extract(combined)
