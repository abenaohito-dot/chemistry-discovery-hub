"""Chemistry Discovery Hub — Main Streamlit Application."""
from __future__ import annotations

import urllib.parse
from pathlib import Path
from typing import Any

import streamlit as st
import pandas as pd

# ── Page config (must be first) ──────────────────────────────────────────────
st.set_page_config(
    page_title="Chemistry Discovery Hub",
    page_icon="⚗️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ──────────────────────────────────────────────────────────────────────
css_path = Path(__file__).parent / "assets" / "theme.css"
if css_path.exists():
    st.markdown(f"<style>{css_path.read_text()}</style>", unsafe_allow_html=True)

# ── Lazy imports (avoid startup cost) ────────────────────────────────────────
@st.cache_resource
def get_fetchers():
    from src.fetchers.pubmed_fetcher import PubMedFetcher
    from src.fetchers.crossref_fetcher import CrossRefFetcher
    from src.fetchers.europepmc_fetcher import EuropePMCFetcher
    from src.fetchers.journal_fetcher import JournalFetcher
    return PubMedFetcher(), CrossRefFetcher(), EuropePMCFetcher(), JournalFetcher()

@st.cache_resource
def get_parsers():
    from src.parsers.compound_extractor import CompoundExtractor
    from src.parsers.pubchem_client import PubChemClient
    from src.parsers.coconut_client import COCONUTClient
    from src.parsers.lotus_client import LOTUSClient
    from src.parsers.chebi_client import ChEBIClient
    from src.parsers.chembl_client import ChEMBLClient
    return (CompoundExtractor(), PubChemClient(),
            COCONUTClient(), LOTUSClient(), ChEBIClient(), ChEMBLClient())

@st.cache_resource
def get_exporter():
    from src.exporters.data_exporter import DataExporter
    return DataExporter()

# ── Session state ─────────────────────────────────────────────────────────────
for key, default in [
    ("papers", []),
    ("compound_data", {}),
    ("last_query", ""),
    ("searched", False),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ── SciFinder-n URL helpers ───────────────────────────────────────────────────
def scifinder_doi_url(doi: str) -> str:
    encoded = urllib.parse.quote(f"https://doi.org/{doi}", safe="")
    return f"https://scifinder-n.cas.org/searchRedirect?redirectUrl={encoded}"

def scifinder_substance_url(compound: str) -> str:
    q = urllib.parse.quote(compound)
    return f"https://scifinder-n.cas.org/search#search/{{\"queryType\":\"substance\",\"query\":\"{q}\"}}"

# ── UI helpers ────────────────────────────────────────────────────────────────
def render_paper_card(paper: dict[str, Any]) -> str:
    title    = paper.get("title", "No title")
    authors  = "; ".join(paper.get("authors", [])[:4])
    if len(paper.get("authors", [])) > 4:
        authors += " et al."
    journal  = paper.get("journal", "")
    year     = paper.get("year", "")
    doi      = paper.get("doi", "")
    abstract = paper.get("abstract", "")
    source   = paper.get("source", "")
    keywords = paper.get("keywords", [])[:6]
    citations = paper.get("citations", "")

    abstract_short = (abstract[:320] + "…") if len(abstract) > 320 else abstract

    source_cls = {
        "PubMed": "source-pubmed", "CrossRef": "source-crossref",
        "EuropePMC": "source-europmc", "Scrapling": "source-scrapling",
    }.get(source, "source-pubmed")

    tags_html = "".join(f'<span class="compound-tag">{kw}</span>' for kw in keywords)

    btns = ""
    if doi:
        btns += (
            f'<a class="btn-scifinder" href="{scifinder_doi_url(doi)}" target="_blank">'
            f'🔬 View in SciFinder-n</a>'
        )

    # Compound buttons from keywords
    for kw in keywords[:2]:
        btns += (
            f'<a class="btn-substance" href="{scifinder_substance_url(kw)}" target="_blank">'
            f'⚗️ {kw[:20]}</a>'
        )

    if doi:
        btns += (
            f'<a class="btn-doi" href="https://doi.org/{doi}" target="_blank">'
            f'🔗 DOI</a>'
        )

    cite_html = (
        f'<span style="font-size:0.74rem;color:rgba(180,220,255,0.5);margin-left:0.5rem;">'
        f'📚 {citations} citations</span>'
        if citations else ""
    )

    return f"""
<div class="paper-card">
  <div style="margin-bottom:0.5rem;">
    <span class="paper-journal-badge">{journal[:40]}</span>
    <span class="paper-year-badge">{year}</span>
    <span class="paper-source-badge {source_cls}">{source}</span>
    {cite_html}
  </div>
  <div class="paper-title">{title}</div>
  <div class="paper-authors">{authors}</div>
  {"<div class='paper-abstract'>" + abstract_short + "</div>" if abstract_short else ""}
  {"<div style='margin-bottom:0.7rem;'>" + tags_html + "</div>" if tags_html else ""}
  <div style="margin-top:0.5rem;">{btns}</div>
</div>
"""

def render_compound_card(name: str, data: dict[str, Any]) -> str:
    pubchem = data.get("pubchem") or {}
    lotus   = data.get("lotus") or {}
    chembl  = data.get("chembl") or {}

    img_url     = pubchem.get("image_url", "")
    formula     = pubchem.get("formula", "")
    mw          = pubchem.get("mol_weight", "")
    cas         = pubchem.get("cas", "")
    inchikey    = pubchem.get("inchikey", "")
    pubchem_url = pubchem.get("pubchem_url", "")
    chembl_url  = chembl.get("chembl_url", "")

    organisms = lotus.get("organisms", [])
    org_text  = " · ".join(o["name"] for o in organisms[:3]) if organisms else ""

    activities = chembl.get("activities", [])
    act_text   = ""
    if activities:
        a = activities[0]
        act_text = f"{a.get('type','')} {a.get('value','')} {a.get('units','')} — {a.get('target','')[:40]}"

    img_html = (
        f'<img src="{img_url}" style="max-width:160px;border-radius:8px;margin-bottom:0.5rem;" />'
        if img_url else
        '<div style="height:80px;display:flex;align-items:center;justify-content:center;'
        'color:rgba(180,210,255,0.3);font-size:2rem;">⚗️</div>'
    )

    props_html = "".join([
        f'<span class="compound-prop">{formula}</span>' if formula else "",
        f'<span class="compound-prop">MW {mw}</span>' if mw else "",
        f'<span class="compound-prop">CAS {cas}</span>' if cas else "",
    ])

    links = ""
    if pubchem_url:
        links += f'<a href="{pubchem_url}" target="_blank" class="btn-doi" style="font-size:0.72rem;">PubChem</a> '
    if chembl_url:
        links += f'<a href="{chembl_url}" target="_blank" class="btn-doi" style="font-size:0.72rem;">ChEMBL</a> '
    links += (
        f'<a href="{scifinder_substance_url(name)}" target="_blank" '
        f'class="btn-substance" style="font-size:0.72rem;">SciFinder-n</a>'
    )

    return f"""
<div class="compound-card">
  {img_html}
  <div class="compound-name">{name}</div>
  <div style="margin:0.3rem 0;">{props_html}</div>
  {"<div class='compound-origin'>🌿 " + org_text + "</div>" if org_text else ""}
  {"<div class='compound-activity'>🧬 " + act_text + "</div>" if act_text else ""}
  <div style="margin-top:0.7rem;">{links}</div>
</div>
"""

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚗️ Search Settings")
    query = st.text_input(
        "Search Query",
        placeholder="e.g. quercetin antioxidant, Curcuma longa alkaloids",
        help="Supports PubMed field tags: [Title], [MeSH Terms], etc.",
    )
    max_results = st.slider("Results per source", 5, 50, 15, 5)

    st.markdown("### 📚 Data Sources")
    use_pubmed    = st.checkbox("PubMed (NCBI)", value=True)
    use_crossref  = st.checkbox("CrossRef (ACS / Wiley / Elsevier / RSC)", value=True)
    use_europepmc = st.checkbox("Europe PMC", value=False)
    use_scrapling = st.checkbox("Journals (Scrapling)", value=False)

    if use_scrapling:
        _, _, _, journal_fetcher = get_fetchers()
        available_journals = journal_fetcher.get_available_journals()
        selected_journals = st.multiselect(
            "Select Journals",
            options=list(available_journals.keys()),
            default=["molecules"],
            format_func=lambda k: available_journals[k],
        )

    if use_crossref:
        _, crossref_fetcher, _, _ = get_fetchers()
        journal_filter = st.selectbox(
            "CrossRef: Filter by journal (optional)",
            ["All journals"] + crossref_fetcher.get_available_journals(),
        )
    else:
        journal_filter = "All journals"

    st.markdown("### 🧪 Compound Enrichment")
    enrich_pubchem  = st.checkbox("PubChem (structure)", value=True)
    enrich_coconut  = st.checkbox("COCONUT (natural products)", value=True)
    enrich_lotus    = st.checkbox("LOTUS (organism sources)", value=True)
    enrich_chembl   = st.checkbox("ChEMBL (bioactivity)", value=False)

    search_btn = st.button("🚀 Launch Search", use_container_width=True)

# ── Hero Header ───────────────────────────────────────────────────────────────
st.markdown("""
<div class="cdh-hero">
  <h1>⚗️ Chemistry Discovery Hub</h1>
  <p class="subtitle">研究の重力をゼロにしよう — Pharmacognosy Research Platform</p>
</div>
""", unsafe_allow_html=True)

# ── Stats bar (when results exist) ───────────────────────────────────────────
if st.session_state.searched and st.session_state.papers:
    papers    = st.session_state.papers
    compounds = st.session_state.compound_data
    cols = st.columns(4)
    stats = [
        (len(papers), "Papers Found"),
        (len([p for p in papers if p.get("source") == "PubMed"]), "from PubMed"),
        (len([p for p in papers if p.get("source") == "CrossRef"]), "from CrossRef"),
        (len(compounds), "Compounds"),
    ]
    for col, (num, label) in zip(cols, stats):
        col.markdown(
            f'<div class="stat-card"><div class="stat-number">{num}</div>'
            f'<div class="stat-label">{label}</div></div>',
            unsafe_allow_html=True,
        )
    st.markdown('<div class="cdh-divider"></div>', unsafe_allow_html=True)

# ── Search execution ──────────────────────────────────────────────────────────
if search_btn and query:
    pubmed_f, crossref_f, europepmc_f, journal_f = get_fetchers()
    extractor, pubchem_c, coconut_c, lotus_c, chebi_c, chembl_c = get_parsers()

    all_papers: list[dict] = []

    with st.spinner("🔍 Searching literature databases..."):
        if use_pubmed:
            results = pubmed_f.search(query, max_results=max_results)
            all_papers.extend(results)

        if use_crossref:
            jf = None if journal_filter == "All journals" else journal_filter
            results = crossref_f.search(query, max_results=max_results, journal_filter=jf)
            all_papers.extend(results)

        if use_europepmc:
            results = europepmc_f.search(query, max_results=max_results)
            all_papers.extend(results)

        if use_scrapling:
            results = journal_f.search(
                query,
                journals=selected_journals if selected_journals else None,
                max_per_journal=max_results,
            )
            all_papers.extend(results)

    # Deduplicate by DOI
    seen_dois: set[str] = set()
    unique_papers: list[dict] = []
    for p in all_papers:
        doi = p.get("doi", "")
        key = doi if doi else p.get("title", "")
        if key not in seen_dois:
            seen_dois.add(key)
            unique_papers.append(p)

    st.session_state.papers    = unique_papers
    st.session_state.last_query = query

    # Compound extraction + enrichment
    with st.spinner("🧪 Extracting and enriching compound data..."):
        all_compound_names: set[str] = set()
        for paper in unique_papers:
            hits = extractor.extract_from_paper(paper)
            for h in hits:
                paper.setdefault("detected_compounds", []).append(h["name"])
                all_compound_names.add(h["name"])

        compound_data: dict[str, dict] = {}
        for cname in list(all_compound_names)[:30]:  # cap at 30 for API rate limits
            entry: dict[str, Any] = {"name": cname}
            if enrich_pubchem:
                entry["pubchem"] = pubchem_c.get_compound_info(cname)
            if enrich_coconut:
                entry["coconut"] = coconut_c.search(cname)
            if enrich_lotus:
                entry["lotus"] = lotus_c.get_organisms(cname)
            if enrich_chembl:
                entry["chembl"] = chembl_c.get_bioactivity(cname)
            compound_data[cname] = entry

        st.session_state.compound_data = compound_data
        st.session_state.searched = True

    st.rerun()

# ── Main Tabs ─────────────────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["📄 Results", "🧪 Compound Explorer", "📤 Export"])

# ── Tab 1: Results ────────────────────────────────────────────────────────────
with tab1:
    papers = st.session_state.papers
    if not papers:
        st.markdown("""
        <div style="text-align:center;padding:4rem 2rem;color:rgba(180,210,255,0.4);">
            <div style="font-size:4rem;margin-bottom:1rem;">🔭</div>
            <div style="font-size:1.1rem;">Enter a query in the sidebar and click <strong>Launch Search</strong></div>
            <div style="font-size:0.85rem;margin-top:0.5rem;">
                Try: <em>quercetin antioxidant</em> · <em>Taxol biosynthesis</em> · <em>berberine antimicrobial</em>
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        # Filter / sort controls
        c1, c2, c3 = st.columns([3, 2, 2])
        with c1:
            filter_text = st.text_input("🔎 Filter results", placeholder="Filter by keyword...")
        with c2:
            source_filter = st.selectbox(
                "Source", ["All"] + list({p.get("source", "") for p in papers})
            )
        with c3:
            sort_by = st.selectbox("Sort by", ["Relevance", "Year (newest)", "Citations"])

        # Apply filters
        filtered = papers
        if filter_text:
            ft = filter_text.lower()
            filtered = [
                p for p in filtered
                if ft in p.get("title", "").lower()
                or ft in p.get("abstract", "").lower()
                or ft in " ".join(p.get("keywords", [])).lower()
            ]
        if source_filter != "All":
            filtered = [p for p in filtered if p.get("source") == source_filter]

        # Sort
        if sort_by == "Year (newest)":
            filtered = sorted(filtered, key=lambda p: p.get("year", ""), reverse=True)
        elif sort_by == "Citations":
            filtered = sorted(filtered, key=lambda p: int(p.get("citations", 0) or 0), reverse=True)

        st.markdown(
            f'<div style="color:rgba(180,210,255,0.5);font-size:0.82rem;margin-bottom:1rem;">'
            f'Showing {len(filtered)} of {len(papers)} papers</div>',
            unsafe_allow_html=True,
        )

        for paper in filtered:
            st.markdown(render_paper_card(paper), unsafe_allow_html=True)

# ── Tab 2: Compound Explorer ──────────────────────────────────────────────────
with tab2:
    compounds = st.session_state.compound_data
    if not compounds:
        st.markdown("""
        <div style="text-align:center;padding:3rem;color:rgba(180,210,255,0.4);">
            <div style="font-size:3rem;margin-bottom:0.8rem;">🧬</div>
            <div>Run a search first to discover compounds</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        # Manual compound lookup
        manual_q = st.text_input("🔬 Lookup a compound directly", placeholder="e.g. curcumin")
        if manual_q and st.button("Lookup"):
            _, pubchem_c, coconut_c, lotus_c, _, chembl_c = get_parsers()
            entry = {
                "name":    manual_q,
                "pubchem": pubchem_c.get_compound_info(manual_q),
                "coconut": coconut_c.search(manual_q),
                "lotus":   lotus_c.get_organisms(manual_q),
                "chembl":  chembl_c.get_bioactivity(manual_q),
            }
            st.session_state.compound_data[manual_q] = entry
            st.rerun()

        st.markdown('<div class="cdh-divider"></div>', unsafe_allow_html=True)

        # Grid layout: 3 columns
        names = list(compounds.keys())
        for row_start in range(0, len(names), 3):
            cols = st.columns(3)
            for col, name in zip(cols, names[row_start:row_start + 3]):
                with col:
                    st.markdown(
                        render_compound_card(name, compounds[name]),
                        unsafe_allow_html=True,
                    )

# ── Tab 3: Export ─────────────────────────────────────────────────────────────
with tab3:
    exporter = get_exporter()
    papers   = st.session_state.papers
    compounds_list = list(st.session_state.compound_data.values())

    if not papers and not compounds_list:
        st.info("No data to export yet. Run a search first.")
    else:
        st.markdown("### 📄 Papers")
        if papers:
            df_papers = exporter.papers_to_dataframe(papers)
            st.dataframe(df_papers, use_container_width=True, height=300)

            c1, c2 = st.columns(2)
            with c1:
                st.download_button(
                    "⬇️ Download CSV",
                    data=exporter.papers_to_csv(papers),
                    file_name=f"cdh_papers_{st.session_state.last_query[:20]}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            with c2:
                st.download_button(
                    "⬇️ Download Markdown",
                    data=exporter.papers_to_markdown(papers).encode("utf-8"),
                    file_name=f"cdh_papers_{st.session_state.last_query[:20]}.md",
                    mime="text/markdown",
                    use_container_width=True,
                )

        st.markdown("### 🧪 Compounds")
        if compounds_list:
            df_cmp = exporter.compounds_to_dataframe(compounds_list)
            st.dataframe(df_cmp, use_container_width=True, height=250)
            st.download_button(
                "⬇️ Download Compounds CSV",
                data=exporter.compounds_to_csv(compounds_list),
                file_name=f"cdh_compounds_{st.session_state.last_query[:20]}.csv",
                mime="text/csv",
                use_container_width=True,
            )
