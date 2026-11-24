"""Chemistry Discovery Hub — Public Natural Products & Literature Search Platform."""
from __future__ import annotations

import html
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import streamlit as st

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from src.utils.common import (
    QueryResult,
    get_config_value,
    is_cas_number,
    is_inchikey,
    merge_compounds,
    merge_papers,
    normalize_formula,
    render_smiles_svg,
    scifinder_doi_url,
    scifinder_substance_url,
)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Chemistry Discovery Hub",
    page_icon="⚗️",
    layout="wide",
    initial_sidebar_state="expanded",
)

css_path = Path(__file__).parent / "assets" / "theme.css"
if css_path.exists():
    st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


# ── Cached Resources (SQLite Cache + API Clients) ─────────────────────────────
@st.cache_resource
def get_cache():
    from src.utils.cache import SQLiteCache
    return SQLiteCache()


@st.cache_resource
def get_clients():
    cache = get_cache()
    from src.exporters.data_exporter import DataExporter
    from src.fetchers.crossref_fetcher import CrossRefFetcher
    from src.fetchers.europepmc_fetcher import EuropePMCFetcher
    from src.fetchers.openalex_fetcher import OpenAlexFetcher
    from src.fetchers.pubmed_fetcher import PubMedFetcher
    from src.parsers.chembl_client import ChEMBLClient
    from src.parsers.coconut_client import COCONUTClient
    from src.parsers.gbif_client import GBIFClient
    from src.parsers.lotus_client import LOTUSClient
    from src.parsers.pubchem_client import PubChemClient

    return {
        "openalex": OpenAlexFetcher(cache=cache),
        "epmc": EuropePMCFetcher(cache=cache),
        "pubmed": PubMedFetcher(cache=cache),
        "crossref": CrossRefFetcher(cache=cache),
        "gbif": GBIFClient(cache=cache),
        "pubchem": PubChemClient(cache=cache),
        "lotus": LOTUSClient(cache=cache),
        "coconut": COCONUTClient(cache=cache),
        "chembl": ChEMBLClient(cache=cache),
        "exporter": DataExporter(),
    }


NAV_PAGES = [
    "📄 文献検索",
    "🧪 化合物検索",
    "⚗️ 分子式検索",
    "🌿 基原植物検索",
    "📤 エクスポート",
]

# ── Session State Initialization & Pending Cross-Navigation ───────────────────
for k, default in [
    ("nav_page", NAV_PAGES[0]),
    ("lit_query", ""),
    ("lit_papers", []),
    ("lit_statuses", []),
    ("lit_gbif_info", None),
    ("compound_query", ""),
    ("compound_results", []),
    ("compound_statuses", []),
    ("chembl_results", {}),
    ("formula_query", ""),
    ("formula_results", []),
    ("formula_statuses", []),
    ("taxon_query", ""),
    ("taxon_gbif", None),
    ("taxon_gbif_status", None),
    ("taxon_papers", []),
    ("taxon_lit_statuses", []),
    ("taxon_compounds", []),
    ("taxon_cmp_status", None),
]:
    if k not in st.session_state:
        st.session_state[k] = default

# Apply pending cross-navigation BEFORE widgets instantiate
if st.session_state.get("_pending_nav"):
    st.session_state.nav_page = st.session_state.pop("_pending_nav")
if st.session_state.get("_pending_lit_query") is not None:
    st.session_state.lit_query = st.session_state.pop("_pending_lit_query")
if st.session_state.get("_pending_compound_query") is not None:
    st.session_state.compound_query = st.session_state.pop("_pending_compound_query")


# ── Shared UI Helpers ─────────────────────────────────────────────────────────
_STATUS_LABEL = {
    "ok": "正常",
    "truncated": "上限打切",
    "empty": "0件",
    "timeout": "タイムアウト",
    "rate_limited": "制限(429)",
    "error": "取得失敗",
}


def render_api_statuses(results: list[QueryResult]) -> None:
    """Display explicit per-API status chips distinguishing ok/truncated/empty/error."""
    if not results:
        return
    chips: list[str] = []
    for r in results:
        label = _STATUS_LABEL.get(r.status, r.status)
        cache_tag = " [cache]" if r.from_cache else ""
        detail = f" — {r.message}" if r.message else ""
        text = html.escape(f"{r.source}: {label}{detail}{cache_tag}")
        chips.append(f'<span class="status-chip status-{r.status}">{text}</span>')
    st.markdown(f'<div class="status-strip">{"".join(chips)}</div>', unsafe_allow_html=True)


def run_parallel(tasks: list[tuple[str, Any]]) -> list[QueryResult]:
    """Execute zero-arg QueryResult callables in parallel while preserving order."""
    if not tasks:
        return []
    out: dict[int, QueryResult] = {}
    with ThreadPoolExecutor(max_workers=min(4, len(tasks))) as ex:
        futs = {ex.submit(fn): (idx, src) for idx, (src, fn) in enumerate(tasks)}
        for fut, (idx, src) in futs.items():
            try:
                out[idx] = fut.result()
            except Exception as exc:
                out[idx] = QueryResult(source=src, status="error", message=f"{src}: {type(exc).__name__}")
    return [out[i] for i in range(len(tasks))]


def render_paper_card(paper: dict[str, Any]) -> str:
    title = html.escape(paper.get("title") or "No title")
    raw_authors = paper.get("authors") or []
    authors_str = "; ".join(raw_authors[:4]) + (" et al." if len(raw_authors) > 4 else "")
    authors = html.escape(authors_str)
    journal = html.escape((paper.get("journal") or "")[:45])
    year = html.escape(str(paper.get("year") or ""))
    doi = (paper.get("doi") or "").strip()
    pmid = (paper.get("pmid") or "").strip()
    abstract = paper.get("abstract") or ""
    abstract_short = html.escape((abstract[:320] + "…") if len(abstract) > 320 else abstract)
    keywords = [html.escape(k) for k in (paper.get("keywords") or [])[:6]]
    citations = paper.get("citations") or 0
    sources = paper.get("sources") or ([paper["source"]] if paper.get("source") else [])

    src_badges = ""
    for src in sources:
        cls = {
            "PubMed": "source-pubmed",
            "CrossRef": "source-crossref",
            "EuropePMC": "source-europmc",
            "OpenAlex": "source-openalex",
        }.get(src, "source-pubmed")
        src_badges += f'<span class="paper-source-badge {cls}">{html.escape(src)}</span> '

    tags_html = "".join(f'<span class="compound-tag">{kw}</span>' for kw in keywords)
    btns = ""
    if doi:
        doi_esc = html.escape(doi)
        btns += (
            f'<a class="btn-scifinder" href="{scifinder_doi_url(doi)}" target="_blank">'
            f'🔬 SciFinder-n</a>'
            f'<a class="btn-doi" href="https://doi.org/{doi_esc}" target="_blank">🔗 DOI</a> '
        )
    if pmid:
        pmid_esc = html.escape(pmid)
        btns += f'<a class="btn-doi" href="https://pubmed.ncbi.nlm.nih.gov/{pmid_esc}/" target="_blank">PubMed</a>'

    cite_html = (
        f'<span style="font-size:0.74rem;color:rgba(180,220,255,0.6);margin-left:0.4rem;">'
        f'📚 {int(citations)} citations</span>'
        if citations
        else ""
    )

    return f"""
<div class="paper-card">
  <div style="margin-bottom:0.45rem;">
    {f'<span class="paper-journal-badge">{journal}</span>' if journal else ''}
    {f'<span class="paper-year-badge">{year}</span>' if year else ''}
    {src_badges}{cite_html}
  </div>
  <div class="paper-title">{title}</div>
  {f'<div class="paper-authors">{authors}</div>' if authors else ''}
  {f'<div class="paper-abstract">{abstract_short}</div>' if abstract_short else ''}
  {f'<div style="margin-bottom:0.65rem;">{tags_html}</div>' if tags_html else ''}
  <div style="margin-top:0.4rem;">{btns}</div>
</div>
"""


def build_literature_results(
    query: str,
    clients: dict[str, Any],
    use_oa: bool,
    use_epmc: bool,
    use_pm: bool,
    use_cr: bool,
    max_per_src: int,
    tiabs_only: bool = False,
    journal_filter: str | None = None,
) -> tuple[list[QueryResult], list[dict[str, Any]]]:
    tasks: list[tuple[str, Any]] = []
    if use_oa:
        tasks.append(("OpenAlex", lambda: clients["openalex"].search(query, max_results=max_per_src, title_abstract_only=tiabs_only)))
    if use_epmc:
        epmc_q = f'(TITLE:({query}) OR ABSTRACT:({query}))' if (tiabs_only and "TITLE:" not in query) else query
        tasks.append(("EuropePMC", lambda: clients["epmc"].search(epmc_q, max_results=max_per_src)))
    if use_pm:
        tasks.append(("PubMed", lambda: clients["pubmed"].search(query, max_results=max_per_src)))
    if use_cr:
        jf = None if journal_filter in (None, "All journals") else journal_filter
        tasks.append(("CrossRef", lambda: clients["crossref"].search(query, max_results=max_per_src, journal_filter=jf)))
    statuses = run_parallel(tasks)
    return statuses, merge_papers(statuses)


def execute_compound_search(query: str, clients: dict[str, Any]) -> tuple[list[QueryResult], list[dict[str, Any]]]:
    q = query.strip()
    if not q:
        return [], []

    if is_cas_number(q):
        pub_res = clients["pubchem"].search_compound(q, max_results=5)
        coc_guard = clients["coconut"].search_by_name(q)  # returns guard message (no 500)
        statuses = [pub_res, coc_guard]
        extra: list[QueryResult] = []
        seen_iks = {it["inchikey"] for it in pub_res.items if is_inchikey(it.get("inchikey", ""))}
        for ik in list(seen_iks)[:3]:
            extra.extend(run_parallel([
                ("LOTUS", lambda _ik=ik: clients["lotus"].search_by_name(_ik, max_results=5)),
                ("COCONUT", lambda _ik=ik: clients["coconut"].search_by_inchikey(_ik)),
            ]))
        merged = merge_compounds([pub_res] + extra)
        statuses.extend(extra)
    elif is_inchikey(q):
        ik = q.upper()
        statuses = run_parallel([
            ("PubChem", lambda: clients["pubchem"].search_compound(ik, max_results=5)),
            ("LOTUS", lambda: clients["lotus"].search_by_name(ik, max_results=5)),
            ("COCONUT", lambda: clients["coconut"].search_by_inchikey(ik)),
        ])
        merged = merge_compounds(statuses)
    else:
        # Compound name: PubChem, LOTUS, and COCONUT all searched independently
        statuses = run_parallel([
            ("PubChem", lambda: clients["pubchem"].search_compound(q, max_results=5)),
            ("LOTUS", lambda: clients["lotus"].search_by_name(q, max_results=10)),
            ("COCONUT", lambda: clients["coconut"].search_by_name(q, max_results=10)),
        ])
        merged = merge_compounds(statuses)

    # Enrich top 3 merged compounds having valid 27-char InChIKey with Wikidata organisms+DOIs (if missing)
    for rec in merged[:3]:
        ik = rec.get("inchikey", "")
        if not is_inchikey(ik):
            continue
        if not rec["organisms"]:
            wd_res = clients["lotus"].get_organisms_by_inchikey(ik, limit=30)
            if wd_res.items:
                rec["organisms"] = wd_res.items
                if "LOTUS" not in rec["sources"]:
                    rec["sources"].append("LOTUS")
                if not rec.get("lotus"):
                    rec["lotus"] = {"wikidata_url": wd_res.items[0].get("wikidata_url", "")}
            if wd_res.status in ("timeout", "rate_limited", "error"):
                statuses.append(wd_res)
        if not rec.get("coconut"):
            coc_ik = clients["coconut"].search_by_inchikey(ik)
            if coc_ik.items:
                rec["coconut"] = coc_ik.items[0]
                if "COCONUT" not in rec["sources"]:
                    rec["sources"].append("COCONUT")
                note = coc_ik.items[0].get("attribution_note")
                if note and note not in rec["attribution_notes"]:
                    rec["attribution_notes"].append(note)

    return statuses, merged


def render_mol_svg_html(smiles: str, width: int = 230, height: int = 155) -> str:
    svg = render_smiles_svg(smiles, width=width, height=height)
    if svg:
        return f'<div class="mol-svg-box">{svg}</div>'
    return (
        '<div style="height:90px;display:flex;align-items:center;justify-content:center;'
        'color:rgba(180,210,255,0.35);font-size:1.6rem;">⚗️ 構造データなし</div>'
    )


def navigate_to(page: str, lit_query: str | None = None, compound_query: str | None = None, auto_run: bool = False) -> None:
    st.session_state._pending_nav = page
    if lit_query is not None:
        st.session_state._pending_lit_query = lit_query
        if auto_run:
            st.session_state._auto_run_lit = True
    if compound_query is not None:
        st.session_state._pending_compound_query = compound_query
        if auto_run:
            st.session_state._auto_run_compound = True
    st.rerun()


# ── Initialize Clients ────────────────────────────────────────────────────────
clients = get_clients()
cache = get_cache()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ 検索設定")
    st.markdown("### 📚 文献データベース")
    use_openalex = st.checkbox("OpenAlex", value=True)
    use_europepmc = st.checkbox("Europe PMC", value=True)
    use_pubmed = st.checkbox("PubMed (NCBI)", value=True)
    use_crossref = st.checkbox("CrossRef (任意)", value=False)

    journal_filter = "All journals"
    if use_crossref:
        journal_filter = st.selectbox(
            "CrossRef: 雑誌フィルタ (任意)",
            ["All journals"] + clients["crossref"].get_available_journals(),
        )

    max_lit_results = st.slider("文献 最大件数 / DB", 5, 50, 20, 5)

    st.markdown("---")
    st.markdown("### 🔑 APIキー設定状況 (.env / Secrets)")
    oa_ok = "設定済み ($1/日)" if get_config_value("OPENALEX_API_KEY") else "未設定 (匿名IP共有)"
    ncbi_ok = "設定済み (10 req/s)" if get_config_value("NCBI_API_KEY") else "未設定 (3 req/s)"
    cr_ok = "設定済み (Polite)" if get_config_value("CROSSREF_EMAIL") else "未設定"
    st.caption(f"OpenAlex: {oa_ok}  \nNCBI: {ncbi_ok}  \nCrossRef: {cr_ok}")

    st.markdown("---")
    st.markdown("### 💾 ローカルキャッシュ (SQLite)")
    st.caption(f"有効エントリ数: **{cache.count()}** 件")
    if st.button("🗑️ キャッシュをクリア", use_container_width=True):
        removed = cache.clear()
        st.toast(f"キャッシュ {removed} 件を削除しました")
        st.rerun()

# ── Hero & Navigation ─────────────────────────────────────────────────────────
st.markdown("""
<div class="cdh-hero">
  <h1>⚗️ Chemistry Discovery Hub</h1>
  <p class="subtitle">天然物化学 公開データベース横断検索ツール</p>
</div>
""", unsafe_allow_html=True)

nav_page = st.radio(
    "Navigation",
    NAV_PAGES,
    horizontal=True,
    label_visibility="collapsed",
    key="nav_page",
)
st.markdown('<div class="cdh-divider"></div>', unsafe_allow_html=True)


# ==============================================================================
# PAGE 1: 文献検索
# ==============================================================================
if nav_page == "📄 文献検索":
    st.subheader("📄 文献検索 (OpenAlex / Europe PMC / PubMed)")
    with st.form("lit_search_form", clear_on_submit=False):
        c1, c2 = st.columns([5, 1.3])
        with c1:
            lit_input = st.text_input(
                "検索クエリ",
                key="lit_query",
                placeholder='例: "Carex" AND "oligostilbene", quercetin antioxidant, swertiamarin',
            )
        with c2:
            st.markdown("<br>", unsafe_allow_html=True)
            lit_submit = st.form_submit_button("🚀 検索", use_container_width=True)

        o1, o2 = st.columns(2)
        with o1:
            lit_tiabs = st.checkbox("タイトル・抄録に限定 (OpenAlex / Europe PMC)", value=False)
        with o2:
            lit_gbif_expand = st.checkbox("植物学名として GBIF シノニム展開を併用", value=False)

    auto_lit = st.session_state.pop("_auto_run_lit", False)
    if (lit_submit or auto_lit) and lit_input.strip():
        effective_q = lit_input.strip()
        gbif_info = None
        if lit_gbif_expand:
            with st.spinner("🌿 GBIFで学名シノニムを確認中..."):
                gbif_res = clients["gbif"].match_plant(effective_q)
                if gbif_res.items:
                    gbif_info = gbif_res.items[0]
                    terms = [gbif_info["accepted_name"]] + gbif_info.get("synonyms", [])[:5]
                    terms = [f'"{t}"' for t in dict.fromkeys(terms) if t]
                    if terms:
                        effective_q = "(" + " OR ".join(terms) + ")"
        st.session_state.lit_gbif_info = gbif_info

        with st.spinner("🔍 公開文献データベースを検索中..."):
            statuses, papers = build_literature_results(
                effective_q,
                clients,
                use_oa=use_openalex,
                use_epmc=use_europepmc,
                use_pm=use_pubmed,
                use_cr=use_crossref,
                max_per_src=max_lit_results,
                tiabs_only=lit_tiabs,
                journal_filter=journal_filter,
            )
        st.session_state.lit_statuses = statuses
        st.session_state.lit_papers = papers

    if st.session_state.lit_gbif_info:
        gi = st.session_state.lit_gbif_info
        syns_txt = ", ".join(gi.get("synonyms", [])[:5]) or "なし"
        st.info(f"GBIF シノニム展開: **{gi['accepted_name']}** ({gi.get('family','')}) | 追加シノニム: {syns_txt}")

    render_api_statuses(st.session_state.lit_statuses)
    papers = st.session_state.lit_papers
    if papers:
        f1, f2, f3 = st.columns([3, 2, 2])
        with f1:
            flt_txt = st.text_input("🔎 結果内絞り込み", placeholder="タイトル・抄録・キーワードで絞込...")
        with f2:
            avail_srcs = sorted({s for p in papers for s in (p.get("sources") or [])})
            src_flt = st.selectbox("出典DB", ["All"] + avail_srcs)
        with f3:
            sort_opt = st.selectbox("並び順", ["Relevance", "Year (newest)", "Citations"])

        filtered = papers
        if flt_txt:
            ft = flt_txt.lower()
            filtered = [
                p for p in filtered
                if ft in (p.get("title") or "").lower()
                or ft in (p.get("abstract") or "").lower()
                or ft in " ".join(p.get("keywords") or []).lower()
            ]
        if src_flt != "All":
            filtered = [p for p in filtered if src_flt in (p.get("sources") or [])]
        if sort_opt == "Year (newest)":
            filtered = sorted(filtered, key=lambda p: str(p.get("year") or ""), reverse=True)
        elif sort_opt == "Citations":
            filtered = sorted(filtered, key=lambda p: int(p.get("citations") or 0), reverse=True)

        st.caption(f"DOI重複除去後: **{len(filtered)} / {len(papers)}** 報を表示")
        for p in filtered:
            st.markdown(render_paper_card(p), unsafe_allow_html=True)
    elif st.session_state.lit_statuses:
        st.info("該当する文献が見つかりませんでした。")


# ==============================================================================
# PAGE 2: 化合物検索（化合物名・CAS・InChIKey）
# ==============================================================================
elif nav_page == "🧪 化合物検索":
    st.subheader("🧪 化合物検索（化合物名・CAS番号・27文字InChIKey）")
    st.caption(
        "PubChem・LOTUS・COCONUTを独立検索し、**27文字InChIKey完全一致のみ**統合します"
        "（同名の立体異性体・別構造は統合しません）。"
    )

    with st.form("compound_search_form", clear_on_submit=False):
        c1, c2 = st.columns([5, 1.3])
        with c1:
            cmp_input = st.text_input(
                "化合物名 / CAS番号 / InChIKey",
                key="compound_query",
                placeholder="例: quercetin, 117-39-5, nepalensinol D, REFJWTPEDVJJIY-UHFFFAOYSA-N",
            )
        with c2:
            st.markdown("<br>", unsafe_allow_html=True)
            cmp_submit = st.form_submit_button("🚀 検索", use_container_width=True)

    auto_cmp = st.session_state.pop("_auto_run_compound", False)
    if (cmp_submit or auto_cmp) and cmp_input.strip():
        q_clean = cmp_input.strip()
        if is_cas_number(q_clean):
            st.caption("入力判定: **CAS番号**（PubChem経由で構造・InChIKeyを解決しLOTUS/COCONUTへ照会）")
        elif is_inchikey(q_clean):
            st.caption("入力判定: **27文字InChIKey**")
        else:
            st.caption("入力判定: **化合物名**（PubChem / LOTUS / COCONUT を独立検索）")

        with st.spinner("🧪 化合物データベースを検索中..."):
            statuses, merged = execute_compound_search(q_clean, clients)
        st.session_state.compound_statuses = statuses
        st.session_state.compound_results = merged

    render_api_statuses(st.session_state.compound_statuses)
    compounds = st.session_state.compound_results
    if compounds:
        st.caption(f"統合後レコード数: **{len(compounds)}** 件（27文字InChIKey一致のみ統合）")
        for idx, rec in enumerate(compounds):
            ik = rec.get("inchikey", "")
            name = rec.get("name") or ik or "Unnamed"
            pub = rec.get("pubchem") or {}
            lot = rec.get("lotus") or {}
            coc = rec.get("coconut") or {}
            card_key = ik or f"cmp_{idx}_{name}"

            with st.container(border=True):
                col_img, col_info = st.columns([1.3, 3.2])
                with col_img:
                    st.markdown(render_mol_svg_html(rec.get("smiles", "")), unsafe_allow_html=True)
                with col_info:
                    badges = "".join(
                        f'<span class="paper-source-badge source-{s.lower()}">{html.escape(s)}</span> '
                        for s in rec.get("sources", [])
                    )
                    st.markdown(f"### {html.escape(name)} &nbsp; {badges}", unsafe_allow_html=True)
                    props = []
                    if rec.get("formula"):
                        props.append(f"分子式: `{rec['formula']}`")
                    if rec.get("mol_weight"):
                        props.append(f"MW: `{rec['mol_weight']}`")
                    if rec.get("cas"):
                        props.append(f"CAS: `{rec['cas']}`")
                    if ik:
                        props.append(f"InChIKey: `{ik}`")
                    else:
                        props.append("InChIKey: *未取得（非統合）*")
                    st.markdown(" | ".join(props))

                    if rec.get("iupac_name"):
                        st.caption(f"IUPAC: {rec['iupac_name']}")

                    # External links (existing SciFinder-n + source DBs)
                    ext_links = []
                    if pub.get("pubchem_url"):
                        ext_links.append(f"[PubChem (CID:{pub.get('cid','')})]({pub['pubchem_url']})")
                    if lot.get("lotus_url"):
                        ext_links.append(f"[LOTUS ({lot.get('lotus_id','')})]({lot['lotus_url']})")
                    if lot.get("wikidata_url"):
                        ext_links.append(f"[Wikidata]({lot['wikidata_url']})")
                    if coc.get("coconut_url"):
                        ext_links.append(f"[COCONUT ({coc.get('coconut_id','')})]({coc['coconut_url']})")
                    ext_links.append(f"[SciFinder-n]({scifinder_substance_url(rec.get('cas') or name or ik)})")
                    st.markdown(" · ".join(ext_links))

                    # LOTUS organisms + DOIs
                    orgs = rec.get("organisms", [])
                    if orgs:
                        with st.expander(f"🌿 LOTUS 基原生物・出典 ({len(orgs)} 件表示)", expanded=len(orgs) <= 5):
                            for o in orgs[:15]:
                                d = o.get("doi", "")
                                doi_part = f" — [{d}](https://doi.org/{d})" if d else ""
                                st.markdown(f"- *{o.get('name', '')}*{doi_part}")
                    elif ik:
                        if st.button("🌿 LOTUS基原生物をWikidataで照会", key=f"wd_btn_{idx}_{card_key}"):
                            wd_res = clients["lotus"].get_organisms_by_inchikey(ik, limit=30)
                            if wd_res.items:
                                rec["organisms"] = wd_res.items
                                if "LOTUS" not in rec["sources"]:
                                    rec["sources"].append("LOTUS")
                            else:
                                st.info(wd_res.message or "Wikidata上に基原生物データなし")
                            st.rerun()

                    # COCONUT M:N note
                    if coc:
                        st.caption(
                            f"🥥 COCONUT参考統計: 生物数={coc.get('organism_count', '?')} / "
                            f"文献数={coc.get('citation_count', '?')} （※M:N集計のため個別対応は原著要確認）"
                        )

                    # Action row: ChEMBL on-demand + Literature search
                    b1, b2 = st.columns(2)
                    with b1:
                        if st.button("🧬 ChEMBL 生物活性を取得", key=f"chembl_btn_{idx}_{card_key}"):
                            with st.spinner("ChEMBL照会中..."):
                                ch_res = clients["chembl"].get_bioactivity(inchikey=ik, name=name)
                            st.session_state.chembl_results[card_key] = ch_res
                    with b2:
                        if st.button("📄 この化合物名で文献検索", key=f"lit_jump_{idx}_{card_key}"):
                            navigate_to("📄 文献検索", lit_query=name, auto_run=True)

                    ch_res: QueryResult | None = st.session_state.chembl_results.get(card_key)
                    if ch_res is not None:
                        render_api_statuses([ch_res])
                        if ch_res.items:
                            ch_item = ch_res.items[0]
                            acts = ch_item.get("activities", [])
                            if acts:
                                st.markdown(
                                    f"**ChEMBL**: [{ch_item.get('chembl_id')}]({ch_item.get('chembl_url','')}) "
                                    f"({ch_item.get('match_type','')})"
                                )
                                for a in acts[:8]:
                                    st.markdown(
                                        f"- `{a.get('type')} {a.get('relation','')}{a.get('value')} {a.get('units')}` "
                                        f"— {a.get('target')} *({(a.get('assay') or '')[:80]})*"
                                    )
    elif st.session_state.compound_statuses:
        st.info("該当する化合物が見つかりませんでした。")


# ==============================================================================
# PAGE 3: 分子式検索
# ==============================================================================
elif nav_page == "⚗️ 分子式検索":
    st.subheader("⚗️ 分子式検索 (LOTUS / COCONUT + 任意PubChem)")
    st.caption("27文字InChIKey完全一致のみ統合し、立体異性体はすべて別エントリとして表示します。")

    with st.form("formula_search_form", clear_on_submit=False):
        c1, c2 = st.columns([5, 1.3])
        with c1:
            mf_input = st.text_input(
                "分子式 (Hill記法推奨)",
                key="formula_query",
                placeholder="例: C15H10O7, C20H28O6, C42H32O9",
            )
        with c2:
            st.markdown("<br>", unsafe_allow_html=True)
            mf_submit = st.form_submit_button("🚀 検索", use_container_width=True)

        include_pubchem_mf = st.checkbox(
            "PubChem も含める（※合成化合物を含み、件数が非常に多くなる場合があります）",
            value=False,
        )

    if mf_submit and mf_input.strip():
        mf_norm = normalize_formula(mf_input)
        tasks = [
            ("LOTUS", lambda: clients["lotus"].search_by_formula(mf_norm, max_results=50)),
            ("COCONUT", lambda: clients["coconut"].search_by_formula(mf_norm, max_results=50)),
        ]
        if include_pubchem_mf:
            tasks.append(("PubChem", lambda: clients["pubchem"].search_by_formula(mf_norm, max_results=30)))

        with st.spinner(f"⚗️ 分子式 {mf_norm} を検索中..."):
            statuses = run_parallel(tasks)
        st.session_state.formula_statuses = statuses
        st.session_state.formula_results = merge_compounds(statuses)

    render_api_statuses(st.session_state.formula_statuses)
    mf_hits = st.session_state.formula_results
    if mf_hits:
        st.caption(f"候補構造数: **{len(mf_hits)}** 件（27文字InChIKey一致のみ統合）")
        for row_start in range(0, len(mf_hits), 3):
            cols = st.columns(3)
            for offset, (col, rec) in enumerate(zip(cols, mf_hits[row_start : row_start + 3])):
                idx = row_start + offset
                ik = rec.get("inchikey", "")
                name = rec.get("name") or ik or "Unnamed"
                with col:
                    with st.container(border=True):
                        st.markdown(render_mol_svg_html(rec.get("smiles", ""), width=210, height=140), unsafe_allow_html=True)
                        st.markdown(f"**{html.escape(name[:55])}**")
                        st.caption(
                            f"出典: {', '.join(rec.get('sources', []))}  \n"
                            f"分子式: `{rec.get('formula', '')}`  \n"
                            f"InChIKey: `{ik or '未取得'}`"
                        )
                        target_q = ik or name
                        if st.button("🧪 化合物詳細を検索", key=f"mf_jump_{idx}_{target_q}", use_container_width=True):
                            navigate_to("🧪 化合物検索", compound_query=target_q, auto_run=True)
    elif st.session_state.formula_statuses:
        st.info("該当する分子式の化合物が見つかりませんでした。")


# ==============================================================================
# PAGE 4: 基原植物検索（種・属・科）
# ==============================================================================
elif nav_page == "🌿 基原植物検索":
    st.subheader("🌿 基原植物検索（種・属・科）")
    st.caption(
        "GBIF（Plantae限定）で承認学名・シノニムを確認し、関連文献と LOTUS (Wikidata) 既報化合物を照会します。"
        " ※科レベルの既報化合物一括取得は公開APIのタイムアウト回避のため対象外です。"
    )

    with st.form("taxon_resolve_form", clear_on_submit=False):
        c1, c2 = st.columns([5, 1.5])
        with c1:
            taxon_input = st.text_input(
                "植物の学名 (種・属・科)",
                key="taxon_query",
                placeholder="例: Carex distachya, Carex, Fimbristylis, Cyperaceae, Ecklonia",
            )
        with c2:
            st.markdown("<br>", unsafe_allow_html=True)
            resolve_btn = st.form_submit_button("🔎 学名確認", use_container_width=True)

    if resolve_btn and taxon_input.strip():
        with st.spinner("🌿 GBIF (Plantae) で学名を照合中..."):
            g_res = clients["gbif"].match_plant(taxon_input.strip())
        st.session_state.taxon_gbif_status = g_res
        st.session_state.taxon_gbif = g_res.items[0] if g_res.items else None
        st.session_state.taxon_papers = []
        st.session_state.taxon_lit_statuses = []
        st.session_state.taxon_compounds = []
        st.session_state.taxon_cmp_status = None

    if st.session_state.taxon_gbif_status is not None:
        render_api_statuses([st.session_state.taxon_gbif_status])

    gbif_rec = st.session_state.taxon_gbif
    if gbif_rec:
        with st.container(border=True):
            st.markdown(
                f"**承認学名:** *{gbif_rec['accepted_name']}* "
                f"(`{gbif_rec.get('rank','')}` / `{gbif_rec.get('status','')}` / "
                f"科: `{gbif_rec.get('family','')}`) — "
                f"[GBIF]({gbif_rec.get('gbif_url','')})"
            )
            candidates = [gbif_rec["accepted_name"]] + gbif_rec.get("synonyms", [])
            candidates = list(dict.fromkeys(c for c in candidates if c))
            selected_names = st.multiselect(
                "文献検索に含める学名・シノニム（選択可能）",
                options=candidates,
                default=candidates[:6],
            )
            add_np_kw = st.checkbox(
                "成分・単離関連キーワードで文献を補助絞り込み（phytochemical / isolated / constituents 等）",
                value=True,
            )
            if st.button("🚀 関連文献 ＋ LOTUS既報化合物を検索", use_container_width=True):
                search_names = selected_names or [gbif_rec["accepted_name"]]
                name_clause = "(" + " OR ".join(f'"{n}"' for n in search_names[:8]) + ")"
                if add_np_kw:
                    lit_q = (
                        f"{name_clause} AND (phytochemical OR constituents OR isolated "
                        f"OR flavonoid OR stilbene OR terpenoid OR alkaloid OR \"essential oil\")"
                    )
                else:
                    lit_q = name_clause

                with st.spinner("📚 文献検索および LOTUS (Wikidata) を照会中..."):
                    lit_statuses, t_papers = build_literature_results(
                        lit_q,
                        clients,
                        use_oa=use_openalex,
                        use_epmc=use_europepmc,
                        use_pm=use_pubmed,
                        use_cr=use_crossref,
                        max_per_src=max_lit_results,
                        tiabs_only=False,
                        journal_filter=journal_filter,
                    )
                    lotus_tax_res = clients["lotus"].search_by_taxon(
                        gbif_rec["accepted_name"],
                        rank=gbif_rec.get("rank", "SPECIES"),
                        limit=80,
                        gbif_id=gbif_rec.get("accepted_usage_key"),
                    )
                st.session_state.taxon_lit_statuses = lit_statuses
                st.session_state.taxon_papers = t_papers
                st.session_state.taxon_cmp_status = lotus_tax_res
                st.session_state.taxon_compounds = lotus_tax_res.items

    # Show LOTUS Taxon Compounds & Literature in two clear sections
    if st.session_state.taxon_cmp_status is not None or st.session_state.taxon_lit_statuses:
        st.markdown("### 🧪 LOTUS (Wikidata) 既報化合物・出典DOI")
        if st.session_state.taxon_cmp_status is not None:
            render_api_statuses([st.session_state.taxon_cmp_status])
            if st.session_state.taxon_cmp_status.status == "empty" and st.session_state.taxon_cmp_status.message:
                st.info(st.session_state.taxon_cmp_status.message)

        t_cmps = st.session_state.taxon_compounds
        if t_cmps:
            st.caption(f"取得件数: **{len(t_cmps)}** ペア（化合物 × 種 × DOI）")
            for idx, item in enumerate(t_cmps[:40]):
                with st.container(border=True):
                    c_svg, c_body = st.columns([1.1, 3.5])
                    with c_svg:
                        st.markdown(render_mol_svg_html(item.get("smiles", ""), width=190, height=130), unsafe_allow_html=True)
                    with c_body:
                        cname = item.get("name", "")
                        ik = item.get("inchikey", "")
                        doi = item.get("doi", "")
                        st.markdown(f"**{html.escape(cname)}** &nbsp; (`{item.get('formula','')}`)")
                        st.caption(
                            f"種: *{item.get('taxon','')}* | "
                            f"InChIKey: `{ik or '未取得'}`"
                        )
                        links = []
                        if doi:
                            links.append(f"[DOI: {doi}](https://doi.org/{doi})")
                            links.append(f"[SciFinder-n (文献)]({scifinder_doi_url(doi)})")
                        if item.get("wikidata_url"):
                            links.append(f"[Wikidata]({item['wikidata_url']})")
                        if cname or ik:
                            links.append(f"[SciFinder-n (物質)]({scifinder_substance_url(cname or ik)})")
                        if links:
                            st.markdown(" · ".join(links))

                        jump_q = ik or cname
                        if jump_q and st.button("🧪 化合物詳細へ", key=f"tax_cmp_jump_{idx}_{jump_q}"):
                            navigate_to("🧪 化合物検索", compound_query=jump_q, auto_run=True)
            if len(t_cmps) > 40:
                st.caption(f"※ UI表示は先頭40件までです。全 {len(t_cmps)} 件は「📤 エクスポート」タブからCSV出力できます。")

        st.markdown('<div class="cdh-divider"></div>', unsafe_allow_html=True)
        st.markdown("### 📄 関連文献")
        render_api_statuses(st.session_state.taxon_lit_statuses)
        t_papers = st.session_state.taxon_papers
        if t_papers:
            st.caption(f"DOI重複除去後: **{len(t_papers)}** 報")
            for p in t_papers:
                st.markdown(render_paper_card(p), unsafe_allow_html=True)
        elif st.session_state.taxon_lit_statuses:
            st.info("該当する文献が見つかりませんでした。")


# ==============================================================================
# PAGE 5: エクスポート
# ==============================================================================
elif nav_page == "📤 エクスポート":
    st.subheader("📤 検索結果のエクスポート (CSV / Markdown)")
    exporter = get_clients()["exporter"]

    lit_papers = st.session_state.lit_papers
    cmp_results = st.session_state.compound_results
    mf_results = st.session_state.formula_results
    tax_papers = st.session_state.taxon_papers
    tax_cmps = st.session_state.taxon_compounds

    if not any([lit_papers, cmp_results, mf_results, tax_papers, tax_cmps]):
        st.info("エクスポート対象のデータがありません。いずれかの検索を実行してください。")
    else:
        if lit_papers:
            st.markdown(f"### 📄 文献検索結果 ({len(lit_papers)} 報)")
            st.dataframe(exporter.papers_to_dataframe(lit_papers), use_container_width=True, height=240)
            c1, c2 = st.columns(2)
            c1.download_button(
                "⬇️ 文献 CSV ダウンロード",
                data=exporter.papers_to_csv(lit_papers),
                file_name="cdh_literature.csv",
                mime="text/csv",
                use_container_width=True,
            )
            c2.download_button(
                "⬇️ 文献 Markdown ダウンロード",
                data=exporter.papers_to_markdown(lit_papers).encode("utf-8"),
                file_name="cdh_literature.md",
                mime="text/markdown",
                use_container_width=True,
            )

        if cmp_results:
            chembl_map = {
                k: v.items[0]
                for k, v in st.session_state.chembl_results.items()
                if v.items
            }
            st.markdown(f"### 🧪 化合物検索結果 ({len(cmp_results)} 件)")
            st.dataframe(exporter.compounds_to_dataframe(cmp_results, chembl_map), use_container_width=True, height=240)
            c1, c2 = st.columns(2)
            c1.download_button(
                "⬇️ 化合物 CSV ダウンロード",
                data=exporter.compounds_to_csv(cmp_results, chembl_map),
                file_name="cdh_compounds.csv",
                mime="text/csv",
                use_container_width=True,
            )
            c2.download_button(
                "⬇️ 化合物 Markdown ダウンロード",
                data=exporter.compounds_to_markdown(cmp_results, chembl_map).encode("utf-8"),
                file_name="cdh_compounds.md",
                mime="text/markdown",
                use_container_width=True,
            )

        if mf_results:
            st.markdown(f"### ⚗️ 分子式検索結果 ({len(mf_results)} 件)")
            st.dataframe(exporter.compounds_to_dataframe(mf_results), use_container_width=True, height=220)
            st.download_button(
                "⬇️ 分子式候補 CSV ダウンロード",
                data=exporter.compounds_to_csv(mf_results),
                file_name="cdh_formula_compounds.csv",
                mime="text/csv",
                use_container_width=True,
            )

        if tax_cmps or tax_papers:
            st.markdown("### 🌿 基原植物検索結果")
            if tax_cmps:
                st.markdown(f"#### LOTUS 既報化合物 ({len(tax_cmps)} 件)")
                st.dataframe(exporter.taxon_compounds_to_dataframe(tax_cmps), use_container_width=True, height=220)
                st.download_button(
                    "⬇️ 基原植物 化合物 CSV ダウンロード",
                    data=exporter.taxon_compounds_to_csv(tax_cmps),
                    file_name="cdh_taxon_compounds.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            if tax_papers:
                st.markdown(f"#### 基原植物 関連文献 ({len(tax_papers)} 報)")
                c1, c2 = st.columns(2)
                c1.download_button(
                    "⬇️ 基原植物 文献 CSV ダウンロード",
                    data=exporter.papers_to_csv(tax_papers),
                    file_name="cdh_taxon_literature.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
                c2.download_button(
                    "⬇️ 基原植物 文献 Markdown ダウンロード",
                    data=exporter.papers_to_markdown(tax_papers).encode("utf-8"),
                    file_name="cdh_taxon_literature.md",
                    mime="text/markdown",
                    use_container_width=True,
                )
