# Task 22 (Phase 2): OCR テキスト取得とマスタスナップショット照合

## 背景

Task 21（Phase 1）で、マスタ照合に成功した候補は `WhiskeySearch-{env}` の正典名を
`brand_text` に採用するようになった。カリラ（Caol Ila）が「カオルイラ」と表示される問題は
これで解消する見込みだが、レビューで**新たなリスク**が判明した。

`_match_whiskey` の scan フォールバックは双方向部分一致（`name in normalized_item or normalized_item in name`）で、
**最初に当たった 1 件を返して打ち切る**。Phase 1 以降この誤爆は「ユーザーに見え、保存される名前」を書き換える。

実測（`scripts/local/seed_data/whiskeys.json` と `normalize_text` で確認済み）:

- `normalize_text("Caol Ila")` = `"caolila"` ⊂ `"かりら12年|caolila12yearold"` → **カリラが直る理屈**
- `normalize_text("山崎")` = `"山崎"` ⊂ `"山崎12年|yamazaki12yearold"` → **18年のボトルが「山崎 12年」に化ける**

同一のルールなので片方だけは潰せない。dev のシード 50 件は各ブランド 1 件ずつなので顕在化しないが、
楽天由来の大規模データ（3,000 件超）では `山崎 12年` / `山崎 18年` / `山崎 25年` が同居するため確実に事故る。

このタスクでは以下を実装する:

1. **一意性ゲート** — 部分一致で複数のマスタに当たったら自動確定しない（上記リスクの解決策）
2. **OCR 生テキスト（`label_text`）の取得** — モデルの音写ではなくラベルの実文字列を手元に持つ
3. **マスタスナップショットのキャッシュ** — 1 解析あたり最大 15 scan という現状の無駄を解消
4. **fuzzy shortlist の生成** — Phase 3（2 段目 LLM 補正）の入力を作る。**自動確定には絶対に使わない**

## 対象リポジトリ

`/home/ttakahashi/workspace/whiskey`（ブランチ `fix/brand-detection-canonical-name`、Task 21 の変更が未コミットで載っている）

## 重要な前提: fuzzy を自動確定に使ってはならない

`difflib.SequenceMatcher(...).ratio()` を正規化済みフルネームに適用した実測値:

| 比較 | ratio | 意味 |
|---|---|---|
| `Caol Ila` vs `Caol Ila 12 Year Old` | **0.609** | 真陽性なのに低い |
| `カオルイラ` vs `カリラ 12年` | 0.364 | 真の対象だが拾えない |
| `Single Malt` vs `Fuji Single Malt` | **0.833** | **偽陽性**。銘柄未読なのに富士へ化ける |
| `Aberlour 12 Year Old` vs `Aberfeldy 12 Year Old` | **0.800** | 別銘柄同士が高スコア |

**真陽性より偽陽性の方が高くなる**ため、どんな閾値を選んでも自動確定には使えない。
fuzzy の用途は Phase 3 に渡す shortlist の生成のみ。

## 実装内容

### 1. `label_text` の取得（`lambda/drink-log-analyze/index.py`）

#### 1-a. プロンプト（51-57行）

出力スキーマに `"label_text":""` を追加する。指示は
「ラベルに印字されている文字列をそのまま返す。翻字・翻訳・推測をしない。読めなければ空文字」
という趣旨にすること。既存のキー・制約（最大 5 候補、confidence 0〜1、highball は SODA、markdown 禁止）は変えない。

#### 1-b. `_validate_model_output`（248-290行）

- キー集合を `{brand_candidates, serving_style, glass_type, label_text}` に変更
- `label_text` は `str` かつ 200 文字以下（`glass_type` と同じ扱い）。空文字は許容
- 戻り値の dict にも `label_text` を含める

#### 1-c. 追随が必要な箇所（漏らすと必ず落ちる）

- MOCK_AI の戻り値（325-332行）に `"label_text": ""` を追加
- 解析失敗時の縮退デフォルト（486-487行）に `"label_text": ""` を追加
- `tests/lambda/test_drink_log_analyze.py` の**全ての** Bedrock スタブ応答 JSON に `"label_text"` を追加

`label_text` は AppState に保存しない（Phase 3 で同一リクエスト内でのみ使う）。
**ログにも出さない**（長さのみ可）。

### 2. マスタスナップショットのキャッシュ

現行は候補ごとに query + 最大 3 ページ scan を実行しており、5 候補で最大 15 scan になる。
これをモジュールスコープの TTL 付きスナップショットに置き換える。

```python
MASTER_SNAPSHOT_TTL_SECONDS = 300
MASTER_SNAPSHOT_MAX_PAGES = 20
MASTER_SNAPSHOT_MAX_ITEMS = 5000
```

要件:

- **`LastEvaluatedKey` が無くなるまでページングする。** DynamoDB Scan は 1 回 1MB 上限のため、
  現行の `MAX_WHISKEY_SCAN_PAGES = 3` では 3,000 件超のマスタを確実に取りこぼす。
- 安全上限（`MASTER_SNAPSHOT_MAX_PAGES` / `MASTER_SNAPSHOT_MAX_ITEMS`）に達した場合は
  **`complete = False` フラグを立てる**。不完全なスナップショットを正常データとして扱い
  「マスタに存在しない」と誤断定するのが最悪の挙動なので、この場合は:
  - warning ログを出す（件数とページ数のみ。銘柄名は出さない）
  - **照合結果を「不明」として扱い、自動確定も Phase 3 の補正もスキップする**
    （＝全候補が `match_source: "ai"` になる。誤った正典名を出すよりマシ）
- キャッシュは**一時変数で完全に構築してから原子的に差し替える**。読み側が半端な状態を見てはならない。
- TTL 切れ、または `WHISKEY_SEARCH_TABLE` 名が変わった場合に再構築する。
- `ProjectionExpression` は現行と同じ `id, #name, name_ja, name_en, normalized_name`。
- 各レコードについて以下を**前計算**して保持する:
  - `normalize_text(name_ja)` / `normalize_text(name_en)` / `normalize_text(name)` を**個別に**
    （マスタの `normalized_name` は投入経路によって `ja|en` 連結キーだったり単体キーだったりして
    信頼できない。`scripts/local/seed_whiskeys.py:103` と `scripts/insert_whiskeys_to_dynamodb.py:246` を参照）
  - 後述の「ブランド核」文字列

テストからキャッシュをリセットできるよう、モジュール関数（例 `_reset_master_cache()`）を用意すること。

### 3. ブランド核（brand core）の抽出

年数表記と一般語がノイズになるため、比較用の文字列を作るヘルパーを実装する。
`normalize_text` を通した**後**に、以下を除去する:

- 年数表記: `12年` / `12 year old` / `12yo` / `aged 12 years` 等（数字 + 年 / year(s) old / yo）
- 一般語: `single malt` / `singlemalt` / `blended` / `blend` / `scotch` / `whisky` / `whiskey` /
  `シングルモルト` / `ブレンデッド` / `ウイスキー` / `ウィスキー` / `純米` は不要
- 容量・度数: `700ml` / `750ml` / `40%` / `43度` 等
- 記号・区切り（`|` を含む）

`normalize_text` はカタカナをひらがなに変換済みなので、日本語の一般語は**ひらがなで**マッチさせること
（例: `シングルモルト` → `しんぐるもると`）。除去した結果が空文字になる場合は、除去前の文字列を使う。

このヘルパーは純粋関数として切り出し、単体テストを書くこと。

### 4. 照合ロジックの再構成

`_match_whiskey` を、スナップショットに対して動く関数に置き換える。
**照合キー**は次の 3 つ: LLM の `name_ja`、LLM の `name_en`、`label_text`。

#### 4-a. 自動確定してよいティア

以下の順で、**マッチした全マスタレコードを集める**（現行のように 1 件目で打ち切らない）:

1. **`exact`** — 正規化後の完全一致。LLM の `name_ja` / `name_en` が
   マスタの正規化済み `name_ja` / `name_en` / `name` のいずれかと完全一致
2. **`substring`** — 双方向部分一致。LLM 名 ⊂ マスタ名、またはマスタ名 ⊂ LLM 名。
   加えて **マスタ名 ⊂ `label_text`**（ラベル全文に正典名が含まれる、という強いシグナル）も含める。
   ただし比較文字列が **3 文字未満のものは使わない**（`sq` のような断片が誤爆するため）

**一意性ゲート（このタスクの中核）:**

- 上位ティアでマッチしたレコードが**ちょうど 1 件**のときだけ自動確定し、
  `match_source` を `"master:exact"` / `"master:substring"` とする
- **2 件以上マッチした場合は自動確定しない。** `match_source` を `"ambiguous"` とし、
  **`whiskey_id` は設定しない**。`brand_text` は LLM の名前のまま（Task 21 の未マッチ時と同じ扱い）
- `exact` で 1 件確定したら `substring` は評価しない（上位ティア優先）

これが「山崎 18年 が 山崎 12年 に化ける」を防ぐ仕掛けである。
`山崎` は `山崎 12年` と `山崎 18年` の両方に当たるので曖昧と判定され、
`カリラ` はマスタに 1 件しか無いので確定する。

#### 4-b. `match_source` の値（Task 21 から変更）

- `"master:exact"` — 完全一致で一意に確定
- `"master:substring"` — 部分一致で一意に確定
- `"ambiguous"` — 複数のマスタに当たったため未確定（`whiskey_id` なし）
- `"ai"` — どのマスタにも当たらなかった（`whiskey_id` なし）

Task 21 で追加した `ai_name_ja` / `ai_name_en` と、正典名の採用ルール
（`name_ja` → `name` → `name_en` の順、200 文字超はフォールバック）はそのまま維持する。

#### 4-c. fuzzy shortlist の生成（自動確定には使わない）

自動確定できなかった候補（`ambiguous` / `ai`）のために、Phase 3 へ渡す shortlist を作る:

- ブランド核同士で `difflib.SequenceMatcher(None, a, b).ratio()` を計算
- `label_text` は全文を 1 本の文字列として投げず、**行・空白で分割したトークン単位**でスコアリングする
  （容量・地域・`SINGLE MALT SCOTCH WHISKY` がノイズになるため）
- スコア上位 **10 件**を `[{"id", "name_ja", "name_en", "score"}]` の形で返す
- `ambiguous` で当たったマスタレコード群は shortlist に**必ず含める**
- **この shortlist は今回 AppState にも API レスポンスにも出さない。**
  `analyze_upload` の内部で計算し、Phase 3 が使えるよう関数として切り出しておくだけでよい。
  未使用の関数が lint で怒られる場合は、`analyze_upload` 内で計算してログに件数だけ出す形にする。

### 5. 削除・整理

- `MAX_WHISKEY_SCAN_PAGES` はスナップショット側の定数に統合されるので、
  残す必要が無ければ削除する（残す場合は使われていることを確認すること）
- 標準ライブラリのみを使うこと。**依存パッケージの追加は禁止**（`difflib` は標準）

### 6. 診断ログの拡張

Task 21 で追加した `Brand candidates resolved` ログに以下を足す。**銘柄名・ラベル文字列は出さない**:

- `label_text_length`（本文ではなく長さ）
- `master_snapshot_complete`（bool）
- `master_snapshot_size`（件数）
- `shortlist_size`
- `ambiguous_count`

### 7. フロントエンド

`frontend/pages/logs/new.vue` の候補表示（Task 21 で `照合済み` / `AI推定・未照合` を出した箇所）を
新しい `match_source` に合わせる:

- `master:exact` / `master:substring` → `照合済み`
- `ambiguous` → `候補が複数・未確定`
- `ai` またはフィールド無し → `AI推定・未照合`

判定は文字列の前方一致（`match_source?.startsWith('master')`）で書くこと。
既存の Tailwind の流儀に合わせ、新規コンポーネントや依存は追加しない。

## テスト（`tests/lambda/test_drink_log_analyze.py` ほか）

### 8-a. Task 21 のレビューで指摘された未カバー分（必ず入れる）

1. マスタの `name_ja` が空 / 欠落で `name` がある場合 → `brand_text` がマスタの `name` になる
2. マスタの名前が 200 文字超の場合 → LLM 値にフォールバックする
3. **非空のマスタ**に対して無関係な銘柄名を照合したとき `match_source == "ai"` になる
   （現状のテストは空テーブルを使っており「空マスタ ⇒ ai」しか証明していない）
4. `frontend/tests/pages/logsNew.test.ts` に、候補のラベル文字列
   （`照合済み` / `AI推定・未照合` / `候補が複数・未確定`）が描画されることの assertion を追加

### 8-b. このタスクの新規テスト

5. **カリラ回帰テストの維持**（Task 21 のものを新 `match_source` 値に更新）:
   `name_ja="カオルイラ", name_en="Caol Ila"` → `brand_text == "カリラ 12年"`,
   `whiskey_id == "caol-ila-12"`, `match_source == "master:substring"`
6. **山崎の曖昧性ゲート**: マスタに `山崎 12年` と `山崎 18年` の 2 件を入れ、
   LLM が `name_ja="山崎"` を返したとき → `match_source == "ambiguous"`,
   `"whiskey_id" not in candidate`, `brand_text == "山崎"`（12年に化けないこと）
7. **偽陽性の負例**: LLM が `name_en="Single Malt"` / `name_ja="シングルモルト"` しか読めなかったとき、
   マスタに `Fuji Single Malt` があっても**自動確定しない**こと。
   同様に `Aberlour` と `Aberfeldy` が取り違えられないこと
8. **1 文字 OCR 誤り**: `Caol lla`（i が l）が自動確定はされないが shortlist には載ること
9. **スナップショット不完全時**: 安全上限に達して `complete = False` のとき、
   全候補が `match_source == "ai"` になり、warning ログが出ること
10. **スナップショットが全ページを読むこと**: `LastEvaluatedKey` を 2 回返す fake scan に対し、
    3 ページ全てを読むこと（現行の 3 ページ上限では取りこぼす件数を再現する）
11. **キャッシュが効くこと**: 同一プロセスで 2 回解析したとき scan が 1 回分しか走らないこと
12. **ブランド核抽出の単体テスト**: `カリラ 12年` → `かりら`、
    `Caol Ila 12 Year Old` → `caolila`、`Fuji Single Malt` → `fuji` 等
13. `label_text` 欠落 / 200 文字超で malformed 扱いになり、既存のリトライ経路に乗ること
14. MOCK_AI 経路と縮退デフォルトが `label_text` 込みで検証を通ること
15. ログに `label_text` の本文・銘柄名が含まれないこと（Task 21 のログテストを拡張）
16. AppState 往復（`drink_logs._prepare_initial_record` の消し込み条件）が引き続き成立すること

## 検証コマンド（必ず全て実行して結果を報告すること）

```bash
cd /home/ttakahashi/workspace/whiskey
python -m pytest tests -q
cd frontend && npm run lint && npx vitest run
```

**注意: `npm test` は watch モードの `vitest` で終わらない。必ず `npx vitest run` を使うこと。**

## 禁止事項

- 依存パッケージの追加（`package.json` / `requirements*.txt` / `pyproject.toml` の変更）
- DynamoDB のスキーマ・GSI 定義の変更
- `infra/` 配下の変更
- **fuzzy スコアによる自動確定**（shortlist 生成のみ）
- **2 段目 LLM の呼び出し実装**（Phase 3 / 後続タスク）
- `label_text` の本文・銘柄名をログや AppState に出すこと
- コミット・プッシュ・マージ

## 完了条件

- `python -m pytest tests -q` が全て通る
- `cd frontend && npm run lint && npx vitest run` が通る
- カリラ回帰テスト（`master:substring` で確定）と山崎曖昧性テスト（`ambiguous`）が両方存在し、通る
- `git diff` の変更が `lambda/drink-log-analyze/index.py`、`frontend/pages/logs/new.vue`、
  `tests/lambda/test_drink_log_analyze.py`、`frontend/tests/pages/logsNew.test.ts` に収まっている
