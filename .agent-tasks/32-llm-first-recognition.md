# Task 32: 銘柄認識を LLM 主体に切り替える

## 背景

実写真 27 枚で 3 モデルを比較した結果、設計方針を転換する。

### 音写の失敗は Nova / Haiku では救えない

```
カリラ        nova='カオルイラ 12年'  haiku='カオル・アイラ 12年'  sonnet='カリラ 12年'
ブナハーブン   nova='バナナブハイン 12年' haiku='ブナハブン 12年'    sonnet='ブナハーブン 12年'
イチローズモルト nova='イチローのマルト'   haiku="イチロー's モルト"   sonnet='イチローズモルト'
桜尾          nova='桜正宗'(日本酒の銘柄) haiku=JSONパース失敗       sonnet='桜尾 シングルモルト'
```

**Sonnet 4.6 は目視確認した範囲で全て正しい。** Nova / Haiku は実用に耐えない。

### カタログ照合が「確信を持った誤り」を生んでいる

Nova の出力を現行カタログ（51 件）に照合した結果、25 枚中 9 枚が確定したが、
**そのうち少なくとも 4 件が誤りまたは恣意的**だった。

```
写真のラベル: SHERRY OAK CASK      → カタログ確定 'ザ・マッカラン ダブルカスク 12年'（別商品）
モデルの読み: '山崎'（年数表記なし）  → カタログ確定 '山崎 12年'（年数を捏造）
3本写った写真（グレンフィディック/白州/知多） → 'グレンフィディック 12年' だけを恣意的に確定
2本写った写真（グレンリベット/ラガヴーリン）   → 'ラガヴーリン 16年' だけを恣意的に確定
```

**一意性ゲートはカタログ内の曖昧性しか守らない。** カタログが疎であることは一意性の証拠にならず、
`山崎 12年` しか登録が無ければ NAS の山崎まで 12 年に格上げされる。

飲酒ログにおいて**確信を持った誤記録は棄却より有害**であり、現状はカタログが誤確定を生む側に回っている。

### 複数本の写真は実在する

25 枚中 3 枚（12%）が複数本を含む。「1 枚 1 銘柄」という前提は現実に合っていない。

## 目標

> **モデルが読み取った内容を正とし、カタログはそれを上書きしない。**

カタログは「一致したときに ID を付ける」だけの役割に降格する。
モデルが「山崎」と読んだなら「山崎」と記録し、カタログに `山崎 12年` しか無くても格上げしない。

## 対象リポジトリ

`/home/ttakahashi/workspace/whiskey`（ブランチ `fix/brand-detection-canonical-name`）

## 実装内容

### 1. インフラ: Sonnet 4.6 を許可する

`infra/lib/whiskey-infra-stack.ts` の `bedrockModels`（434-454 行付近）に追加する。
**既存の Nova / Haiku のエントリは残すこと**（切り戻し可能にするため）。

```
profileArn:      arn:aws:bedrock:${region}:${account}:inference-profile/jp.anthropic.claude-sonnet-4-6
destinationArns: arn:aws:bedrock:ap-northeast-1::foundation-model/anthropic.claude-sonnet-4-6
                 arn:aws:bedrock:ap-northeast-3::foundation-model/anthropic.claude-sonnet-4-6
```

（実際の ARN は `aws bedrock get-inference-profile` で確認済み）

`BEDROCK_MODEL_ID`（588 行付近）を `jp.anthropic.claude-sonnet-4-6` に変更する。
`BEDROCK_MODEL_ALLOWLIST` は既存の導出ロジックで自動的に3モデルを含むこと。

**`global.` プロファイルの禁止（`index.py:115-116`）は維持すること。**

`infra/test/infra.test.ts` の Bedrock 権限テストを 3 モデル分に更新する。

### 2. プロンプトと出力スキーマの全面変更

現行の `brand_candidates`（`lambda/drink-log-analyze/index.py:55-62`）を廃止する。

新しい出力:

```json
{
  "whiskeys": [
    {"name_ja": "カリラ 12年", "name_en": "Caol Ila 12 Year Old", "confidence": 0.95}
  ],
  "serving_style": "NEAT|ROCKS|WATER|SODA|COCKTAIL",
  "glass_type": ""
}
```

プロンプトの要点（実写真で検証済みの文面を基にする）:

- 「日本で一般に流通している**正式な日本語表記**で答える」
- 「熟成年数が読み取れる場合は**必ず含める**」
- 「**判別できなければ空配列**を返す。推測しない」
- 「**複数のボトルが写っている場合は全て列挙する**」（最大 5 件）
- ラベルに書かれていない情報（カスク種別・熟成年数）を**補完しない**

`serving_style` の扱いと `SERVING_STYLE_ALIASES` は現行を維持する。

`_validate_model_output` を新スキーマに合わせて書き直す。`whiskeys` は 0〜5 件の配列、
各要素は `{name_ja, name_en, confidence}` で `name_ja` が空でないこと。
`confidence` は `_decimal_confidence` で `Decimal` 化する（float は DynamoDB に保存できない）。

### 3. カタログ照合を「上書きしない」形に変える

**これが本タスクの中核である。**

現行の `_match_whiskey` / `_resolved_candidate` の「正典名で上書きする」挙動を廃止する。

新しい規則:

- `brand_text` は**常にモデルが返した `name_ja`** を使う。カタログで置き換えない
- カタログ照合は **`normalize_text` による完全一致のみ**とする。
  部分一致・ブランド核・fuzzy による確定は**すべて廃止**する
- 完全一致したときだけ `whiskey_id` を付ける
- 一致しなくても記録は成立する（`whiskey_id` なし）

したがって以下は**削除**してよい:
`_brand_core` / `_GENERAL_NOISE` / `_usable_match_core` / `_LABEL_TOKEN_RE` /
証拠ティア / 一意性ゲート / `_build_fuzzy_shortlist` / `label_text`

`_get_master_snapshot`（全ページ走査・`complete` フラグ・scan 失敗の縮退）は**維持する**。
Projection には `id` / `name_ja` / `name_en` / `name` / `normalized_name` が必要。

`match_source` は次の 2 値に簡素化する:
- `"catalog"` — 正規化後の完全一致で `whiskey_id` を付与した
- `"ai"` — カタログに一致が無い（記録は成立する）

### 4. 複数本への対応

`whiskeys` 配列の各要素を候補として返す。既存の
`analysis_id` + `candidate_index` の契約（`lambda/drink-logs/index.py:501-581`）は維持できる。

**フロントは候補が 1 件以上あれば無条件に先頭を自動選択する**
（`frontend/composables/useDrinkLogBatch.ts:124-135`）。
複数本が検出された場合は自動選択せず、ユーザーに選ばせること。
API レスポンスに `multiple_detected: true` 相当の情報を含めるか、
候補数で判断できるようにする。

### 5. 予算とコストの再検討

Sonnet は Nova より入力トークンが約 5 倍（実測 335 → 1658）で、単価も大きく異なる。

- `HANDLER_BUDGET_MS = 20_000` で Sonnet の応答が間に合うか確認し、必要なら調整する
  （Lambda の timeout は 28 秒）
- `ANALYZE_GLOBAL_DAILY_LIMIT`（50）などのコスト上限は**維持する**。
  上限があることで月額が有界に保たれる
- リトライは現行どおり最大 2 回。無闇に増やさないこと

### 6. ログ

既存の構造化ログを新スキーマに合わせる。**銘柄名は出さない**:
検出件数 / `match_source` の内訳 / `whiskey_id` の有無 / モデル ID /
スナップショットの完全性と件数。

## テスト

既存テストは大幅な書き換えが必要になる。以下を必ず含めること:

1. **モデルの読みを上書きしないこと（本タスクの中核）**
   - モデルが `山崎` を返し、カタログに `山崎 12年` しか無い場合、
     `brand_text == "山崎"` であり `12年` に格上げされない
   - このとき `whiskey_id` は付かない（完全一致ではないため）
2. **正規化後の完全一致でのみ ID が付く**
   - モデルが `カリラ 12年`、カタログに `カリラ 12年` → `whiskey_id` 付与、`match_source == "catalog"`
   - モデルが `カリラ`（年数なし）、カタログに `カリラ 12年` のみ → ID なし、`match_source == "ai"`
   - 表記揺れ（`アラン10年` と `アラン 10年`）は `normalize_text` により一致する
3. **複数本**: `whiskeys` に 2 件返ったとき候補が 2 件になり、先頭が自動選択されない
4. カタログに無い銘柄（`厚岸 シングルモルト` 等）でも記録が成立する（`whiskey_id` なし）
5. `whiskeys` が空配列（判別不能）のとき、候補ゼロで 200 が返る
6. `confidence` が `Decimal` として AppState に保存できる
7. `global.` プロファイルが起動時に拒否される（既存の挙動を維持）
8. スナップショットの scan 失敗で 500 にならず縮退する（既存の挙動を維持）
9. ログに銘柄名が出ない

## 検証コマンド（必ず全て実行して結果を報告すること）

```bash
cd /home/ttakahashi/workspace/whiskey
python -m pytest tests -q
cd infra && npm test && npm run synth:dev
cd frontend && npm run lint && npx vitest run   # npm test は watch モードなので使わない
```

デプロイと実写真での評価は人間が行う。

## 禁止事項

- 依存パッケージの追加
- `global.` プロファイルの使用・禁止ロジックの削除
- カタログの正典名でモデルの読みを上書きすること（本タスクの目的に反する）
- 部分一致・fuzzy による `whiskey_id` の付与
- コスト上限（`ANALYZE_*_LIMIT`）の緩和・削除
- 銘柄名をログに出すこと
- Bedrock の実呼び出し（テストはスタブ）
- コミット・プッシュ・マージ

## 完了条件

- `python -m pytest tests -q` / `infra` / `frontend` の検証が全て通る
- 「山崎 → 山崎 12年 に格上げしない」テストが通る
- 完全一致でのみ `whiskey_id` が付くテストが通る
- 複数本で自動選択されないテストが通る
- `git diff` の変更が `lambda/` `infra/` `frontend/` `tests/` に収まっている
