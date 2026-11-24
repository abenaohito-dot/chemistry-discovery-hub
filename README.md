# Chemistry Discovery Hub

天然物化学研究者向けの公開データベース横断検索ツール（Streamlit アプリ）です。  
**文献・化合物（名称/CAS/InChIKey）・分子式・基原植物（種/属/科）**の 4 つの独立した起点から公開データベースを検索し、RDKit による 2D 構造描画、出典付きデータの確認、CSV / Markdown エクスポート、および SciFinder-n への外部遷移を行えます。

---

## 主な機能

1. **📄 文献検索**
   * **OpenAlex / Europe PMC / PubMed**（任意で **CrossRef**）を並列検索し、正規化 DOI に基づいて重複を統合します。
   * 植物学名として **GBIF** シノニム展開を併用するオプションを備えています。
2. **🧪 化合物検索（名称・CAS番号・27文字InChIKey）**
   * **PubChem / LOTUS / COCONUT** を独立して検索し、**27文字 InChIKey が完全一致する場合のみ統合**します（同名の立体異性体・別構造は統合しません）。
   * 構造は **RDKit** でローカル SVG 描画します。**ChEMBL** 生物活性は詳細カード上のボタンからオンデマンドで取得します。
3. **⚗️ 分子式検索**
   * **LOTUS Web API / COCONUT**（任意で PubChem）から候補構造を取得し、立体異性体を保持したまま一覧表示します。
4. **🌿 基原植物検索（種・属・科）**
   * **GBIF**（`kingdom=Plantae` 限定・異界ホモニム防止）で承認学名・シノニムを確認し、関連文献と **LOTUS（Wikidata SPARQL）** の既報化合物・出典 DOI を照会します（※科レベルの一括化合物取得は公開 SPARQL のタイムアウト回避のため対象外です）。
5. **📤 エクスポート**
   * 各検索結果を出典情報・DOI・InChIKey・SciFinder-n リンク付きで CSV / Markdown 出力できます。

---

## ディレクトリとキャッシュ

* 運用ディレクトリ: `/Volumes/Dock_SSD_1TB/chemistry-discovery-hub`
* ローカル API キャッシュ: `.cache/api_cache.sqlite`（SQLite による TTL 付きキャッシュ。文献 24 時間、化合物・分類 7 日間。タイムアウトや HTTP 429/5xx 等のエラー応答はキャッシュしません）
* 調査・設計メモ: `docs/research_notes.md`

---

## セットアップ・起動方法

macOS (Apple Silicon) では `rdkit` 等の互換性のため Python 3.11 仮想環境（`.venv`）を利用します。すでに `.venv` が構築済みの場合は「起動」から実行してください。

### 初回セットアップ（環境再構築時）

```bash
cd /Volumes/Dock_SSD_1TB/chemistry-discovery-hub
/usr/local/bin/python3.11 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

### 起動

```bash
cd /Volumes/Dock_SSD_1TB/chemistry-discovery-hub
.venv/bin/streamlit run app.py
```

ブラウザで表示されたローカル URL（通常 `http://localhost:8501`）を開きます。

---

## APIキーの設定方法（任意・推奨）

すべての機能は公開 API を利用していますが、特に **OpenAlex** は匿名利用だと同一ネットワーク IP 共有で `$0.10/日` に制限され HTTP 429 になりやすいため、無料個人キーの設定を推奨します。

1. テンプレートをコピーして `.env` を作成します（`.env` は `.gitignore` で除外されており Git には含まれません）。

```bash
cd /Volumes/Dock_SSD_1TB/chemistry-discovery-hub
cp .env.example .env
```

2. `.env` を開き、必要な値を設定します。

```env
# OpenAlex API Key（推奨: 無料個人キーで $1/日 の専用枠を取得可能）
# 取得先: https://openalex.org/settings/api
OPENALEX_API_KEY=

# NCBI API Key（任意・推奨: PubMed E-utilities のレート制限が 3 -> 10 req/s に向上）
# 取得先: https://www.ncbi.nlm.nih.gov/account/
NCBI_API_KEY=

# CrossRef Polite Pool（任意: 連絡先メールを設定すると優先プールを利用可能）
CROSSREF_EMAIL=your.email@institution.ac.jp
```

## Streamlit Community Cloud での公開設定

Streamlit Community Cloud（Linux / Python 3.11 想定）で動作させる場合、以下の設定を行います。

- **Python バージョン**: `3.11`（App settings → Advanced settings）
- **システム依存関係**: 同梱の `packages.txt`（`libxrender1`, `libxext6`）により Linux 環境での RDKit 構造描画に対応しています。
- **Secrets 設定**: 管理画面の **App settings → Secrets** に以下を TOML 形式で登録してください（全項目任意・設定時のみレート制限緩和／Polite Pool 有効化）。

```toml
OPENALEX_API_KEY = "your_openalex_key"
NCBI_API_KEY = "your_ncbi_key"
CROSSREF_EMAIL = "your.email@institution.ac.jp"
```

> **注意**: `.env`、`.streamlit/secrets.toml`、および `.cache/`（`*.sqlite`）は絶対に Git へコミット・公開しないでください。
