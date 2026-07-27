# Task 21 (Phase 1): マスタ照合時に正典名を採用する + 診断ログ

## 背景

記録機能でカリラ（Caol Ila）の写真を解析したところ、存在しない銘柄「カオルイラ」と判定された。
Bedrock Nova 2 Lite がラベルの `CAOL ILA` を誤って音写した結果だが、**アプリ側にも欠陥がある**。

`lambda/drink-log-analyze/index.py` の `_match_whiskey`（369-413行）は
`WhiskeySearch-{env}` テーブルに照合して **id しか返さない**。
`_build_candidates`（416-431行）は `brand_text = name_ja or name_en`（422行）で
**LLM が返した文字列をそのまま表示名に採用**しており、照合できた正典レコードの名前を捨てている。

実測で確認済み:

```python
normalize_text("Caol Ila") in normalize_text("カリラ 12年|Caol Ila 12 Year Old")  # => True
```

つまりモデルが `name_en: "Caol Ila"` を返していれば `_match_whiskey` の scan 部分一致で
`caol-ila-12` に**照合自体は成功していた**のに、画面には「カオルイラ」と出る。

このタスクではその配線を直し、併せて**今後この種の誤判定を追跡できる診断ログ**を入れる
（現行 Lambda は候補名も照合結果も一切ログしておらず、原因の直接証拠が取れなかった）。

**このタスクのスコープは Phase 1 のみ。** OCR テキスト（`label_text`）の取得、マスタの
スナップショットキャッシュ、あいまい照合、2 段目 LLM 補正は**後続タスクで行うので実装しないこと**。

## 対象リポジトリ

`/home/ttakahashi/workspace/whiskey`（ブランチ `fix/brand-detection-canonical-name`）

## 実装内容

### 1. `lambda/drink-log-analyze/index.py`

#### 1-a. `_match_whiskey` の戻り値を item 全体にする

- シグネチャを `def _match_whiskey(table, candidate) -> Mapping[str, Any] | None:` に変更し、
  id ではなく**マッチしたマスタ item そのもの**を返す。
- 現行の `_whiskey_id`（364-366行）による id 有無チェックは維持する
  （`id` が非空文字列でない item はマッチとみなさない）。
- query 経路（373-382行）は `Limit=1` で `ProjectionExpression` が無く全属性が返るのでそのまま使える。
- scan 経路（384-412行）の `ProjectionExpression` には既に
  `id, #name, name_ja, name_en, normalized_name` が含まれるので追加取得は不要。
- **照合ロジック自体（exact query → 双方向部分一致 scan）は変更しないこと。** 戻り値だけを変える。

#### 1-b. `_build_candidates` で正典名を採用する

マッチした場合、candidate は次の形にする:

```python
{
    "brand_text": <マスタの name_ja → name → name_en の順で最初の非空文字列>,
    "name_ja": <マスタの name_ja（無ければ空文字）>,
    "name_en": <マスタの name_en（無ければ空文字）>,
    "confidence": <LLM の confidence（Decimal のまま。変更しない）>,
    "whiskey_id": <マスタの id>,
    "match_source": "master",
    "ai_name_ja": <LLM が返した name_ja>,
    "ai_name_en": <LLM が返した name_en>,
}
```

マッチしなかった場合:

```python
{
    "brand_text": name_ja or name_en,   # 現行と同じ
    "name_ja": name_ja,
    "name_en": name_en,
    "confidence": <LLM の confidence>,
    "match_source": "ai",
    "ai_name_ja": name_ja,
    "ai_name_en": name_en,
}
```

制約:
- `whiskey_id` は**マッチ時のみ**設定する（現行どおり。未マッチ時にキー自体を作らない）。
- `brand_text` が空文字になってはいけない。マスタ側の名前が全て空という異常データの場合は
  LLM の `name_ja or name_en` にフォールバックする。
- `brand_text` / `name_ja` / `name_en` / `ai_name_ja` / `ai_name_en` は
  いずれも 200 文字を超えないこと（超える場合は切り詰めではなくマスタ値をそのまま使う。
  マスタは自前データなので通常超えないが、念のため 200 文字超なら LLM 値にフォールバックする）。
- `confidence` は必ず `Decimal` のままにすること。`float` は DynamoDB Resource が保存できない。

#### 1-c. 診断ログを追加する

`analyze_upload` にキーワード引数 `logger=None` を追加し、`lambda_handler`（541-553行）から
既存の `logger` を渡す。`logger` が `None` のときは何もログしない（既存テストを壊さないため）。

`_build_candidates` の実行後、`put_item` の前に **1 行だけ** info ログを出す:

```python
logger.info(
    "Brand candidates resolved",
    candidate_count=len(candidates),
    matched_count=<whiskey_id を持つ候補数>,
    match_sources=[c["match_source"] for c in candidates],
    top_match_source=<candidates[0]["match_source"] または None>,
    model_id=model_id,
)
```

**銘柄名・ラベル文字列・ユーザー ID などの本文は絶対にログに出さないこと。**
件数と `match_source` のティア名のみ。

### 2. `frontend/composables/useDrinkLogs.ts`

`DrinkLogCandidate` 型（4-18行付近）に optional フィールドを追加する:

```ts
match_source?: string
ai_name_ja?: string
ai_name_en?: string
```

既存の `applyAnalysis`（`useDrinkLogBatch.ts:124-135`）の挙動は変えないこと。

### 3. `frontend/pages/logs/new.vue`

候補ドロップダウン（286-301行付近）の表示で、照合元が分かるようにする:

- `match_source === 'master'` の候補: 現行表示に加えて「照合済み」を示すラベルを付ける
- `match_source === 'ai'`（またはフィールド未設定）の候補: **「AI推定・未照合」と明示する**

これは任意ではなく必須要件。存在しない銘柄をユーザーが無自覚に確定保存するのを防ぐため。
既存の Tailwind のクラス指定・スタイルの流儀に合わせること。新しい依存やコンポーネントは追加しない。

### 4. テスト `tests/lambda/test_drink_log_analyze.py`

#### 4-a. `WhiskeyTable` スタブを実データ形状に作り直す（重要）

現行スタブ（46-57行）は `query` が常に `{"id": "whiskey-1"}` だけを返し、`scan` は常に空。
これでは正典名の採用も、実際の GSI キー形式も検証できない。

以下の**実データ形状**を持つスタブに置き換える（`scripts/local/seed_whiskeys.py:95-107` と
`scripts/local/seed_data/whiskeys.json:173-180` の実際の形に合わせる）:

```python
CAOL_ILA_ITEM = {
    "id": "caol-ila-12",
    "name": "カリラ 12年",
    "name_ja": "カリラ 12年",
    "name_en": "Caol Ila 12 Year Old",
    # シード投入経路が作る ja|en 連結キー
    "normalized_name": "かりら12年|caolila12yearold",
}
```

- `query` は `KeyConditionExpression` の値が item の `normalized_name` と完全一致したときだけ返す
  （連結キーなので候補名単体ではヒットしない、という現実を再現する）。
- `scan` は保持している item 一覧を返す（ページングは 1 ページで良い）。
- 既存テストが依存している「マッチする / しない」の切り替え（`match=True/False`）は
  保持アイテム一覧の有無で表現し、既存テストが通るよう調整すること。

#### 4-b. 新規テスト

1. **カリラ回帰テスト（このタスクの本体）**
   Bedrock スタブが `{"name_ja": "カオルイラ", "name_en": "Caol Ila", "confidence": 0.8}` を返すとき:
   - `candidates[0]["brand_text"] == "カリラ 12年"`
   - `candidates[0]["whiskey_id"] == "caol-ila-12"`
   - `candidates[0]["match_source"] == "master"`
   - `candidates[0]["ai_name_ja"] == "カオルイラ"`
   - `candidates[0]["confidence"]` が `Decimal` 型であること

2. **未照合候補**
   マスタに無い銘柄を返したとき `match_source == "ai"`、`whiskey_id` キーが存在しないこと、
   `brand_text` が LLM の名前のままであること。

3. **AppState 往復の維持**
   既存の往復テスト（191-244行付近）を拡張し、新フィールドを含む candidate が
   `drink_logs._prepare_initial_record` の消し込み条件を通ることを確認する。

4. **ログに銘柄名が出ないこと**
   ログ出力をキャプチャし、`"カオルイラ"` `"カリラ"` `"Caol Ila"` のいずれの文字列も
   出力に含まれないことを assert する。

## 検証コマンド（必ず全て実行して結果を報告すること）

```bash
cd /home/ttakahashi/workspace/whiskey
python -m pytest tests -q
cd frontend && npm run lint && npm test
```

インフラ側の変更は**このタスクには無い**ので `cd infra && npm test` は不要だが、
もし `infra/` 配下を触ってしまった場合は実行して結果を報告すること。

## 禁止事項

- 依存パッケージの追加（`package.json` / `requirements*.txt` / `pyproject.toml` の変更）
- DynamoDB のスキーマ・GSI 定義の変更
- `infra/` 配下の変更
- `_match_whiskey` の照合アルゴリズム自体の変更（scan ページ数、部分一致の条件など）
- `label_text` / マスタキャッシュ / あいまい照合 / 2 段目 LLM の実装（後続タスク）
- コミット・プッシュ・マージ
- 銘柄名や OCR テキストをログに出力すること

## 完了条件

- `python -m pytest tests -q` が全て通る
- `cd frontend && npm run lint && npm test` が通る
- カリラ回帰テストが存在し、通る
- `git diff` の変更が上記 4 ファイル（+ テスト）に収まっている
