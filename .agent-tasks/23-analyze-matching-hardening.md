# Task 23: Phase 2 照合ロジックの堅牢化（レビュー指摘の是正）

## 背景

Task 22（Phase 2）のレビューで、**大規模マスタ（楽天由来 3,037 件）と実ラベルを相手にしたときにだけ
顕在化する実害**が 4 件見つかった。dev のシード 50 件では全てのテストが緑のまま素通りする類のものなので、
本番相当データを想定して潰す。

**絶対に壊してはならない既存の挙動:**

- 一意性ゲート（部分一致で複数マスタに当たったら自動確定しない）
- `match_source` の値（`master:exact` / `master:substring` / `ambiguous` / `ai`）
- カリラ回帰テスト（`カオルイラ` + `Caol Ila` → `brand_text == "カリラ 12年"`）
- 山崎の曖昧性テスト（`山崎` → `ambiguous`、`whiskey_id` なし）
- 日本語 2 文字ブランドのテスト（`白州` → `master:substring` / `響` → `ai`）

## 対象リポジトリ

`/home/ttakahashi/workspace/whiskey`（ブランチ `fix/brand-detection-canonical-name`、Task 21/22 が未コミットで載っている）

---

## 修正 1: 一般漢字語による偽陽性を塞ぐ（最優先）

**再現済みの不具合**（実際に実行して確認した）:

```python
master = [{"id": "genshu", "name_ja": "シングルモルト原酒", "name_en": ""}]
candidate = {"name_ja": "判読不能", "name_en": ""}      # LLM は銘柄を読めていない
label_text = "山崎蒸溜所 貯蔵 原酒 限定 700ml 43%"
_match_whiskey(snapshot, candidate, label_text)["source"]
# 現状 => "master:substring"（自動確定してしまう）
# 期待 => "ai"
```

原因は 2 つの合わせ技:

1. `_brand_core("シングルモルト原酒")` が `"原酒"` を返す（一般語を剥がした残骸が 2 文字漢字になる）
2. `_usable_match_core` の CJK 2 文字緩和が、**ラベル全文経路**（`master_core in label_core`）でも
   効いてしまい、ラベル中の一般語 1 語で確定してしまう

これは Task 22 が `Single Malt → Fuji Single Malt` で潰したはずの偽陽性クラスが、漢字経由で復活したもの。
`原酒` / `新酒` / `古酒` は楽天由来 3,037 件に十分紛れ込む。

### 実装

- `_GENERAL_NOISE`（`lambda/drink-log-analyze/index.py:388-400`）に
  `原酒` / `新酒` / `古酒` / `蒸溜所` / `蒸留所` を追加する。
- **CJK 2 文字の緩和は「候補 core ↔ マスタ core の直接比較」にのみ適用する。**
  `is_substring_match` 後半の `master_core in label_core`（ラベル全文経路）は **3 文字床を維持**すること。
  ラベル全文は語の衝突確率が桁違いに高く、ここが最も危険な経路である。
  `_usable_match_core` に引数（例 `allow_cjk_pair: bool = True`）を足すか、専用ヘルパーに分けること。
- 併せて、ラベル全文経路は `label_core`（全区切りを除去した 1 本の文字列）ではなく
  **行・空白でトークン分割してから** 各トークンに対して判定する。
  `"AGED IN OAK"` → `"agedinoak"` のような隣接語の連結が偶発的な部分文字列を作るのを防ぐ。
  fuzzy 側は既にトークン分割しているので、判定経路も揃える。

### 必須の回帰テスト

- 上記の `原酒` ケースがそのまま `match_source == "ai"` になること
- 既存の `test_japanese_only_brand_name_matching`（`白州` → `master:substring` / `響` → `ai`）が通ること
- 既存の `test_japanese_only_brand_name_keeps_ambiguity_gate`（`山崎` → `ambiguous`）が通ること
- 既存の `test_label_text_can_uniquely_confirm_a_master_name`（`CAOL ILA` = 3 文字以上のラテン core）が通ること
- 漢字の偽陽性負例をパラメトライズドテストに追加すること（現在ラテン系のみ）

---

## 修正 2: `label_text` は棄却ではなくクランプ

**問題**: `_validate_model_output`（`index.py:296-298`）は `label_text` が 200 文字を超えると
`None`（malformed）を返す。`glass_type`（"tumbler" 相当）と同じ扱いにしたが、**リスクが全く違う**。
`label_text` は「ラベルに印字された文字列をそのまま」なので、スコッチの裏ラベルは容易に 200 文字を超える。

超えた瞬間 `None` → `{}` → リトライ → 2 回目も同じ長さになりやすい → 縮退デフォルトで
`brand_candidates: []`。**銘柄候補が 1 つも出ない**という、Phase 1・2 の目的そのものを潰す失敗形になる。

### 実装

- `label_text` が `str` でなければ従来どおり `None`（malformed）を返す
- `str` であれば **200 文字を超えても棄却せず、先頭 200 文字に切り詰めて**返す
  （照合は先頭側の情報で十分成立する）
- `glass_type` の扱いは**変更しないこと**

### テスト

- 201 文字以上の `label_text` を含む応答が **1 回で受理され**、`brand_candidates` が失われないこと
- 切り詰め後の長さが 200 であること
- 既存の `test_invalid_label_text_uses_existing_retry_path` は
  「`label_text` キー欠落」「`label_text` が `str` でない」ケースのみリトライ経路に残すよう更新する

---

## 修正 3: マスタ scan の失敗で 500 にせず縮退させる

**問題**: `_build_master_snapshot` の `table.scan` の例外（スロットリング等）を誰も捕まえておらず、
`analyze_upload` を貫通して `lambda_handler` の総括 `except Exception` で **500** になる。
このとき Bedrock は既に呼ばれ、コストカウンタも消費済み、AppState への保存は未実行 ——
**課金だけ済んでユーザーには何も返らない**最悪の失敗形。

### 実装

- `table.scan` を `except (BotoCoreError, ClientError)` で捕まえ、
  その時点までの items で **`complete=False` のスナップショットを返す**
  （既に「不完全なら照合を諦めて全候補 `ai`」の経路があるので、そこへ合流させる）
- warning ログを出す。**例外の型名のみ**。銘柄名・テーブル内容は出さないこと
- **scan 失敗由来の不完全スナップショットはキャッシュしない**（次のリクエストで再試行させる）。
  一方、安全上限による `complete=False` は再試行しても同じなのでキャッシュしてよい。
  両者を区別できるようスナップショットに理由フラグ（例 `incomplete_reason`）を持たせること

### テスト

- `scan` が `ClientError` を送出するテーブルスタブに対し、レスポンスが **200** であること
- そのとき全候補が `match_source == "ai"` になること
- 次のリクエストで scan が**再度呼ばれる**こと（キャッシュされていないこと）
- 安全上限由来の `complete=False` は 2 回目に scan が走らないこと（キャッシュされること）

---

## 修正 4: shortlist をバジェットで守り、コストを抑える

**問題**: `_build_fuzzy_shortlist`（`index.py:708-719`）は
`全マスタ件数 × 全マスタ core × (候補 core + label トークン)` で `SequenceMatcher.ratio()` を回している。
開発機での実測: 50 件 → 0.02s、**3,037 件 → 0.63〜1.06s**、5,000 件 → 1.84s。
Lambda は `memorySize: 1024`（約 0.6 vCPU 相当）なのでこれより遅い。

`HANDLER_BUDGET_MS = 20_000` は Bedrock 呼び出しまでしか見ておらず、**shortlist はバジェットチェック無しで、
しかも AppState への `put_item` より前**に走る。Bedrock がバジェットを使い切った直後にここで数秒積むと、
Lambda の 28 秒を超えて**解析結果が一切保存されないまま失敗する**。

しかも現在この shortlist の唯一の用途は `shortlist_size` のログ 1 個だ（Phase 3 で使う予定のもの）。

### 実装

- `analyze_upload` から `_build_fuzzy_shortlist` を呼ぶ直前に `_remaining_budget_ms(context, started)` を確認し、
  `MIN_INVOKE_BUDGET_MS` 未満なら **shortlist を計算せず空リストとする**
- `_build_fuzzy_shortlist` に `max_comparison_cores: int = 10` 相当の上限を追加し、
  候補由来の core と `label_text` 由来のトークンをそれぞれ 10 件で打ち切る
- 関数の docstring に「Phase 3 用。スコアは自動確定に使わない」旨を明記して維持すること

### テスト

- マスタ 3,000 件相当の合成スナップショットで shortlist が返ること
- `context.get_remaining_time_in_millis` が小さい場合に shortlist が空になり、
  `shortlist_size` が 0 で記録されること
- `label_text` が非常に長くてもトークン数が上限で打ち切られること

---

## 修正 5: 境界条件とテストの補強

- **`MASTER_SNAPSHOT_MAX_ITEMS` ちょうどで `complete=False` になる**（`index.py:475-477`）。
  5,000 件ぴったりで `LastEvaluatedKey` が無くても不完全扱いになる。
  条件を `len(items) >= MAX and last_key` 相当に修正し、境界テストを追加すること
- `MASTER_SNAPSHOT_MAX_ITEMS` 超過で `complete=False` になり全候補が `ai` に落ちるテストを追加
  （`monkeypatch.setattr(analyze, "MASTER_SNAPSHOT_MAX_ITEMS", 1)` 等）。
  現在テストされているのは `MAX_PAGES` 側だけ
- ambiguous が 11 件以上のときの shortlist のテストを追加
  （forced ids が全件含まれること、`selected[: max(FUZZY_SHORTLIST_SIZE, len(forced_ids))]` の
  切り出し長が `forced_ids` に scored 外の id が混ざってもずれないこと）
- 2 文字ラテン断片（`"sq"` 等）が弾かれることの負例テストを追加（現在 1 文字の `響` のみ covered）
- shortlist が API レスポンスにも AppState にも出ないことの明示的な assertion を追加
  （`label_text` については既に検証済み）
- **`frontend/tests/pages/logsNew.test.ts:233-245` の assertion が弱い。**
  全 option のテキストを `join(' ')` してから 3 つの文字列の存在を見ているだけなので、
  **マッピングが入れ替わっても（`master` → 「AI推定・未照合」、`ai` → 「照合済み」）テストが通ってしまう。**
  `wrapper.findAll('option')` の **index を指定して個別に** 検証する形に書き換えること
  （`options[1]` が `照合済み` を含み `AI推定・未照合` を**含まない**こと、等）

---

## 検証コマンド（必ず全て実行して結果を報告すること）

```bash
cd /home/ttakahashi/workspace/whiskey
python -m pytest tests -q
cd frontend && npm run lint && npx vitest run
```

**`npm test` は watch モードの `vitest` で終わらない。必ず `npx vitest run` を使うこと。**

## 禁止事項

- 依存パッケージの追加（`package.json` / `requirements*.txt` / `pyproject.toml` の変更）
- DynamoDB のスキーマ・GSI 定義の変更
- `infra/` 配下の変更
- **fuzzy スコアによる自動確定**（shortlist 生成のみ）
- **2 段目 LLM の呼び出し実装**（Phase 3 / 後続タスク）
- `label_text` の本文・銘柄名をログや AppState に出すこと
- 一意性ゲート・`match_source` の値・既存の回帰テストを壊すこと
- コミット・プッシュ・マージ

## 完了条件

- `python -m pytest tests -q` が全て通る
- `cd frontend && npm run lint && npx vitest run` が通る
- `原酒` 偽陽性の回帰テストが存在し、`match_source == "ai"` で通る
- カリラ / 山崎 / 白州 / 響 の既存回帰テストが全て通る
- `git diff` の変更が `lambda/drink-log-analyze/index.py`、`tests/lambda/test_drink_log_analyze.py`、
  `frontend/tests/pages/logsNew.test.ts` に収まっている
