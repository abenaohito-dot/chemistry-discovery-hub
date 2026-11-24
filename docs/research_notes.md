# Chemistry Discovery Hub — 公開データベース実測調査記録 (2026-11-24)

将来の機能拡張（ローカル索引DB化や分類群俯瞰機能など）に備え、設計検討時に実測・検証した公開API仕様およびデータ特性を記録する。

---

## 1. 既存実装（v1.0 / tag `v1.0-pre-refactor`）で判明した不具合

1. **`coconut_client.py`**: 実装されていた `GET` 3種（`/api/search/compounds`, `/api/v2/search`, `/api/search`）がすべて `HTTP 404 / 405` を返し、常時 `found: False` で機能停止していた。現行は `POST https://coconut.naturalproducts.net/api/search` のみが未認証で利用可能（`GET /api/molecules` は `401 Unauthorized`）。
2. **`lotus_client.py`**: Wikidata SPARQL クエリ内で `p:P1059` を参照していたが、Wikidata `P1059` は「デンマークの企業登録番号（CVR number）」であり無関係。さらに化合物名テキスト検索（`wbsearchentities`）のみで InChIKey 照合・出典DOI取得を行っておらず、10件で打ち切られていた。
3. **`chebi_client.py`**: `app.py` 内でインスタンス化されていたが UI から未使用で、エンドポイント `/webservices/chebi/2.0/test/getLiteEntity` も `HTTP 500` を返却。
4. **`journal_fetcher.py`（Scrapling）**: 出版社Webサイトのスクレイピングは規約・IPブロックリスクが高く、`planta_medica` の設定に `{query}` プレースホルダ欠落バグも存在した。
5. **`compound_extractor.py` & `app.py`**: 約110語の正規表現で文献から化合物名を自動抽出し、最大30件×4DBへ直列APIコールしていた（`lru_cache` は import のみで未使用）。一般語（`"Compound 1"`, `"Fraction III"`, `"triterpenoid"`）の誤抽出が多かった。

---

## 2. 公開API仕様・制約の実測メモ

### 化合物・天然物・生物分類・活性API

* **PubChem (PUG REST)**
  * **制限**: 最大 `5 req/s`、`400 req/min`、同期タイムアウト `30s`。
  * **仕様変更**: `IsomericSMILES` / `CanonicalSMILES` をプロパティ指定した場合、応答 JSON では `SMILES` / `ConnectivitySMILES` キーとして返却されるケースがある（複数キーへのフォールバックが必須）。
  * **CAS番号検索**: `/compound/xref/rn/{CAS}/cids/JSON`（例 `117-39-5` で3 CID返却、先頭が Quercetin CID `5280343`）。塩や水和物で複数CIDが返ることや、CAS未登録の天然物も多い点に注意。CAS RN 自体は CAS (ACS) の知的財産であり大量収集・再配布は禁止。
  * **分子式検索**: `/compound/fastformula/{formula}/cids/JSON` は同期 200 OK（例 `C15H10O7` で 292 CID）だが合成化合物ノイズを含む。

* **LOTUS（Web API & Wikidata SPARQL）**
  * **Web API**: `GET https://lotus.naturalproducts.net/api/search/simple?query=...` は化合物名・分子式（`C15H10O7` → 37件）を高速に返す。`naturalProducts` 各要素には `lotus_id`, `wikidata_id`, `inchikey`, `smiles`, `molecular_formula`, `traditional_name`, `taxonomyReferenceObjects`（キーの `.` が `$x$x$` に置換された DOI）が含まれる。
  * **Web API の罠**: `query=Curcuma` 等の属名検索はページングなしで巨大JSONを返し 22秒以上応答未完了となるため、分類群検索には使えない。
  * **Wikidata SPARQL**: 60秒制限あり。InChIKey (`wdt:P235`) → 基原生物 (`p:P703`) ＋ 出典DOI (`prov:wasDerivedFrom/pr:P248/wdt:P356`) や、種 (`wdt:P225`)・直接の子である属1ホップ (`wdt:P171`) の取得は 1.8〜3.0秒程度で動作するが、再帰階層探索（`wdt:P171*`）や科レベル一括取得はタイムアウトするため避けるべき。また `wdt:P274` の分子式には `C₄₂H₇₀O₇` のような Unicode 下付き数字が含まれる。

* **COCONUT v2 API**
  * `POST https://coconut.naturalproducts.net/api/search`（JSON `{"query": ..., "page": 1}`）は未認証でページング応答（`data.data`, `data.total`, `data.last_page`）。
  * **返却フィールド**: `identifier`, `canonical_smiles`, `name`, `iupac_name`, `organism_count`, `citation_count` 等を含む一方、`standard_inchi_key` や `molecular_formula` は検索結果行に直接含まれないため、`canonical_smiles` から RDKit で算出する必要がある。
  * **非対応入力の罠**: CAS番号文字列をそのまま `query` へ送るとサーバー側が SMILES として解釈しようとして **`HTTP 500`（`SQLSTATE[22000]: could not create molecule from SMILES`）** を返す。また `type` パラメータへの `molecular_formula` や `organisms` 指定は `HTTP 400`。したがって CAS や生物名を直接送らないこと。
  * **データ構造の限界**: 化合物ごとに `organisms` と `dois` が独立したリスト（M:N）になっており、どの文献がどの生物からの単離を報告したかは一意に決まらない。

* **GBIF Species API**
  * `GET https://api.gbif.org/v1/species/match?name=...&kingdom=Plantae` で学名正規化（承認学名・上位分類・`acceptedUsageKey`）が可能。
  * **`kingdom=Plantae` 指定が必須**：例えば `Ecklonia` は植物界カヤツリグサ科（Cyperaceae）とクロミスタ界褐藻（Lessoniaceae）に同名承認属（ホモニム）が存在するため、界限定なしでは褐藻側へ誤結合するリスクがある。
  * シノニム取得: `GET /v1/species/{accepted_usage_key}/synonyms`。

* **ChEMBL REST API**
  * 27文字 InChIKey（`molecule_structures__standard_inchi_key`）による照合に対応。
  * 実測で連続クエリ時に 15秒タイムアウトが頻発したため、一括エンリッチメントには使わず詳細画面でのオンデマンド取得とする。

### 文献検索API（実測比較）

* **OpenAlex**: 2026年にクレジット制へ移行済み。APIキーなしでは同一IP全体で `$0.10/日` 共有のため即 `HTTP 429` になる。無料個人キー設定で `$1/日`。化学主要誌（*Org. Lett.*, *Chem. Pharm. Bull.*, *Chem. Biodivers.* 等）の回収率が高い。アブストラクトは転置インデックス形式（`abstract_inverted_index`）。
* **Europe PMC**: 認証不要。PubMed レコードを包含しつつ OA 全文や薬学・天然物誌の回収に強い。
* **PubMed (NCBI E-utilities)**: `Automatic Term Mapping` と MeSH 展開により同義語・語形揺れの回収特性が Europe PMC と異なる（実測で *Isodon* クエリ等で独自ヒット多数）。
* **Crossref**: 全体としてアブストラクト欠損率が高く（テストでは 74〜92% 欠損）、希少化合物名で 0件・429 制限も起きやすいため、デフォルト文献検索では任意オプション（OFF）とした。

---

## 3. 将来拡張に向けた実データ検証サマリー（ローカルDB・分類群比較）

将来、研究室ローカル（Mac mini M4 Pro 等）で分類群全体の俯瞰・比較を行う場合の参考データとして記録する。

### 3.1 LOTUS vs COCONUT 凍結スナップショット比較（2026年実測）
* **LOTUS**（`260413_frozen_metadata.csv.gz`, 86.1 MB 圧縮）
  * 709,740 トリプレット（構造–基原生物–出典DOI が厳密な 1:1:1 対応）
  * ユニーク 27文字 InChIKey: **227,298**（植物由来 152,418）、14文字: 151,885
  * 生物あり 100.0%、DOIあり ~100.0%（91,377 DOI、37,467 生物）
  * ただし `manual_validation` は多くが未検証（`NA`）で、最新年は 2011〜2020年前後の欠落も多い。
* **COCONUT**（`coconut_csv-11-2026.zip`, 236.5 MB 圧縮 / 699.9 MB 展開）
  * 738,793 行、ユニーク 27文字 InChIKey: **728,389**（14文字: 479,689）
  * 生物あり: **269,655 (37.0%)**、DOIあり: **239,309 (32.9%)**、CAS列あり: 51,857
  * 収録源には `TCMDB-Taiwan` (54,223)、`KNApSaCK` (47,475)、`CMAUP` (44,165)、`NPASS` (81,798) 等が含まれる一方、約半数は `Super Natural II` や `ZINC NP` 等の商業/仮想ライブラリ由来。
* **重複と相互補完**:
  * 27文字 InChIKey 重複: 190,986（LOTUSの84.0%、COCONUTの26.2%）、Union: **764,701**。
  * COCONUT 独自のうち生物あり 79,016件・DOIあり 48,793件。LOTUS 独自 36,312件（ほぼ全件に生物・DOI紐付き）。

### 3.2 カヤツリグサ科（Cyperaceae）での検証結果と課題
* **GBIF基準**: Cyperaceae 承認種数 7,181種（118属）、*Carex* 2,816種、*Fimbristylis* 355種。
* ***Carex* 属**: Union 273化合物（LOTUS 142 / 32 DOI、COCONUT 261）。ただし LOTUS 出典DOIの最新年は **2011年** であり、2012年以降の *Carex* 原著単離論文（*Carex praecox* の carexines A–E [2024], *Carex acuta/lepidocarpa* のスチルベノイド [2024], *Carex baccans* [2024], *Carex kobomugi* kobochromone A [2025] 等）は未収録だった。
  * また COCONUT 独自 *Carex* 131件中には `CMNPD`（海洋天然物DB）25件・`Scalarane sesterterpenoids` 38件が含まれ、異界由来/誤帰属の疑義があること、さらにシノニム分裂（例: *Kobresia nepalensis* が LOTUS では *Carex neesii*、COCONUT では *Carex unciniiformis* として集計される）や M:N 切断（*Carex* の 63.2%、*Fimbristylis* の 100% で生物–文献対応が一意に特定不能）が確認された。
* ***Fimbristylis* 属**: Union わずか 18化合物（COCONUT独自 0件）、LOTUS 出典は 1978〜1985年の4報（広域定性スクリーニングや種子油脂肪酸分析）のみ。1986年以降の文献母集団を OpenAlex・Europe PMC・PubMed で検証しても、多くは抽出物スクリーニング・LC-MS/GC-MS・雑草学・植物ゲノム研究であり、新規単離・NMR構造決定論文の絶対数自体が極めて少ないことが確認された。
* **文献母集団の検索再現率**:
  * LOTUS *Carex* 主要単離原著 19報のうち、PubMed・Europe PMC のインデックス収載率は **10/19（52.6%）**（1976–1991年の *Heterocycles*, *Agric. Biol. Chem.*, *Tet. Lett.*, *Phytochemistry* 等が未収載）。ただしインデックス済みの 10報は **シノニム（*Kobresia*, *Cymophyllus*）展開ありのクエリで 10/10（100%）回収** できた（シノニムなしでは EPMC 8/10）。OpenAlex は古い化学誌・*Org. Lett.*・*Chem. Pharm. Bull.* 等の回収に強く、PubMed/EPMC と相互補完する。
* **将来拡張時の設計指針**:
  * 27文字 InChIKey 厳密一致のみでレコード統合し、14文字（平面骨格）は立体異性体グルーピング・参照用に分離すること。
  * 天然物DBの未収録（特に2012年以降の論文）や非単離論文・疑義データを自動で隠蔽せず、文献検索結果と出典（DOI・1論文あたり紐づけ件数・データ由来）を並置して最終的な科学的判断を研究者に委ねること。
