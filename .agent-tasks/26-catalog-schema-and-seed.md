# Task 26 (Phase A1): カタログのスキーマ再設計と厳選シードの作り替え

## 背景

写真からの銘柄判定で「アラン 10年」が `Arran` としか出ない。実写真でベースラインを測った結果:

| 写真 | 期待 | 実際 |
|---|---|---|
| カリラ 12年 | `caol-ila-12` | `カリラ 12年` / `master:substring` ✅ |
| アラン 10年 | `arran-10` | `Arran` / id なし / `ambiguous` ❌ |

原因は**カタログの構造**にある。

1. `scripts/local/seed_whiskeys.py` の 50 件シードに**アランが存在しない**
2. カタログが年数を構造化フィールドとして持たず、`name_ja` の文字列に埋もれている
3. 別名（表記揺れ）を持たないため、`Arran` ↔ `アラン` を結べない
4. 本番投入経路 `scripts/insert_whiskeys_to_dynamodb.py:229` は `uuid.uuid4()` で ID を振り、
   `batch_writer()`（同 50 行）は既存項目を削除しない。**再投入は重複行を蓄積する**。
   同一商品が複数行になると一意性ゲートが常に発火し、**全ての判定が `ambiguous` に落ちる**

このタスクではカタログのスキーマを作り替え、厳選シードを新スキーマへ移す。
**楽天データの再抽出は後続タスク（A2）**で、`RAKUTEN_APP_ID` が用意でき次第行う。

## 対象リポジトリ

`/home/ttakahashi/workspace/whiskey`（ブランチ `fix/brand-detection-canonical-name`）

## 重要な制約: 検索 API を壊さないこと

`lambda/whiskeys-search/python/whiskey_search_service.py:71-86` は
`WhiskeySearch-{env}` テーブルを**無条件に scan** し、`record_type` のような絞り込みを持たない。
空クエリは全件を返す。

したがって **Brand を独立したレコードとしてこのテーブルに入れてはならない**
（`/api/whiskeys/search/` の結果にブランド行が混入する）。

代わりに:

- **別名の正本はビルド時のファイル** `scripts/catalog/brands.json` に置く（更新は 1 箇所）
- **DynamoDB 上は Expression 行にブランド情報を展開**して持たせる（検索 API に触らない）
- 逆引き辞書は Lambda 側でスナップショット読み込み時にメモリ構築する（このタスクの範囲外）

## 実装内容

### 1. ブランド定義ファイル `scripts/catalog/brands.json`

別名の正本。1 ブランド 1 エントリ。

```json
{
  "version": 1,
  "brands": [
    {
      "brand_key": "caol_ila",
      "brand_ja": "カリラ",
      "brand_en": "Caol Ila",
      "aliases": ["CAOL ILA", "カリラ", "Caol Ila", "カリラ蒸留所", "Caol Ila Distillery"],
      "distillery_ja": "カリラ蒸留所",
      "distillery_en": "Caol Ila Distillery",
      "region": "Scotland/Islay",
      "country": "Scotland"
    },
    {
      "brand_key": "arran",
      "brand_ja": "アラン",
      "brand_en": "Arran",
      "aliases": ["ARRAN", "アラン", "Arran", "Isle of Arran", "アラン蒸留所"],
      "distillery_ja": "アラン蒸留所",
      "distillery_en": "Isle of Arran Distillers",
      "region": "Scotland/Islands",
      "country": "Scotland"
    }
  ]
}
```

**別名はモデルに生成させず、人手で書くこと。** 幻覚が恒久的な「正解」として登録されるのを防ぐ。
`brand_key` は `^[a-z0-9_]+$`。

既存 50 件シードの全銘柄ぶんのブランド定義を作る（同一蒸留所の複数商品は 1 ブランドに集約）。

### 2. 商品定義ファイル `scripts/catalog/expressions.json`

既存 `scripts/local/seed_data/whiskeys.json` を構造化して置き換える。

```json
{
  "version": 1,
  "expressions": [
    {
      "brand_key": "arran",
      "expression_code": "core",
      "age": 10,
      "edition": null,
      "cask": null,
      "vintage": null,
      "bottler": null,
      "abv": "46",
      "type": "Single Malt",
      "canonical_name_ja": "アラン 10年",
      "canonical_name_en": "Arran 10 Year Old"
    }
  ]
}
```

- **アラン 10年（`arran` / age 10）を必ず含めること。** 本タスクの主目的である
- 既存 50 件を全て移行する。既存の `id`（`yamazaki-12` 等）は §3 の `legacy_id` として保持する
- `age` は整数または `null`（`響 ジャパニーズハーモニー` のような年数無し商品）
- `canonical_name_ja` が表示に使われる唯一のフィールド。`brand_ja` が空なら英語表記でよい

### 3. 決定論的な `catalog_key`

`uuid4()` を廃し、**同じ商品が常に同じキーになる**ようにする。

- 同一性の単位は「同じ液体」。**容量とセット本数は同一性に含めない。**
  ボトラー・ヴィンテージ・カスク・エディションは**含める**
- したがってキーの材料は
  `brand_key` / `expression_code` / `age` / `edition` / `cask` / `vintage` / `bottler`
- 実装は正規化した材料を連結して SHA-256 を取り、先頭 16 桁の hex を使う等の安定な方式にする。
  **`brand_key + age` のような自然キーは使わない**
  （Macallan 12 の Double Cask と Sherry Oak のように、同一年数で別 expression が存在する）
- 既存シードの `id`（`yamazaki-12` 等）は `legacy_id` フィールドに保持し、
  DynamoDB の `id`（パーティションキー）は**既存値をそのまま使い続ける**。
  既存の飲酒ログが `whiskey_id` で参照しているため

### 4. DynamoDB のレコード形

`WhiskeySearch-{env}` に投入する項目:

```python
{
  "id": <既存 ID を維持。新規は catalog_key>,
  "catalog_key": <§3 のハッシュ>,
  "catalog_schema_version": 2,
  "brand_key": "arran",
  "brand_ja": "アラン",
  "brand_en": "Arran",
  "brand_aliases": ["ARRAN", "アラン", ...],   # brands.json から展開
  "expression_code": "core",
  "age": 10,                                   # int または不在
  "edition": ..., "cask": ..., "vintage": ..., "bottler": ...,
  "abv": "46",
  "canonical_name_ja": "アラン 10年",
  "canonical_name_en": "Arran 10 Year Old",
  "distillery_ja": ..., "distillery_en": ..., "region": ..., "type": ...,
  # --- 検索 API 互換のため維持（whiskey_search_service が使う） ---
  "name": "アラン 10年",
  "name_ja": "アラン 10年",
  "name_en": "Arran 10 Year Old",
  "normalized_name": normalize_text("アラン 10年|Arran 10 Year Old"),
  "source": "curated_seed",
  "confidence": Decimal("1"),
  "created_at": ..., "updated_at": ...
}
```

`name` / `normalized_name` / `name_ja` / `name_en` は**必ず維持すること**。
これらが無いと `/api/whiskeys/search/` と現行の照合ロジックが壊れる。

`age` は `null` の場合**フィールド自体を入れない**（DynamoDB の `null` 型を避け、
`attribute_exists` で判定できるようにする）。

### 5. シード投入スクリプトの更新 `scripts/local/seed_whiskeys.py`

- 入力を `scripts/catalog/brands.json` + `scripts/catalog/expressions.json` に変更する
- **「ちょうど 50 件」の検証（`seed_whiskeys.py:82`）を撤廃**する。件数は増減しうる
- `brands.json` に存在しない `brand_key` を参照する expression があればエラー
- `catalog_key` の重複を検出してエラー
- 既存の `--target local|dev` とアカウント検証（`:70-75`）はそのまま維持
- `batch_writer(overwrite_by_pkeys=["id"])` は維持（同一 `id` の上書き）

### 6. 大規模投入スクリプトの是正 `scripts/insert_whiskeys_to_dynamodb.py`

**A2（楽天再抽出）の前提となる是正をここで入れる。**

- `uuid.uuid4()`（`:229`）を廃し、`catalog_key` を ID に使う
- **既存行の重複を検出して報告する機能**を追加する（`--report-duplicates` 等）。
  同じ `catalog_key` や同じ正規化名を持つ行が複数あれば一覧する
- 既存の `--target {local,dev}` は維持

**`CLAUDE.md:65-69` は `ENVIRONMENT=prd python scripts/insert_whiskeys_to_dynamodb.py` と
案内しているが、CLI は `--target {local,dev}` しか受け付けない。**
このドキュメント乖離も併せて是正すること（`CLAUDE.md` の該当箇所を実装に合わせる）。

## テスト

`tests/lambda/test_insert_whiskeys_script.py` の既存テストを壊さないこと。新規に:

1. **アランが投入対象に含まれ、`canonical_name_ja == "アラン 10年"`、`age == 10` になる**
2. `catalog_key` が決定論的（同じ入力を 2 回処理して同じキー）
3. 同一年数・別 expression（Macallan 12 Double Cask / Sherry Oak 相当の合成データ）が
   **異なる `catalog_key`** になる
4. 既存シードの `id`（`yamazaki-12` 等）が維持される（既存ログの参照を壊さない）
5. `name` / `normalized_name` / `name_ja` / `name_en` が全レコードに存在する（検索 API 互換）
6. `age` が `null` の商品では `age` フィールドが**存在しない**
7. `brands.json` に無い `brand_key` を参照する expression でエラー
8. `catalog_key` 重複でエラー
9. 既存 50 銘柄が全て移行されている（銘柄数の回帰）

## 検証コマンド（必ず全て実行して結果を報告すること）

```bash
cd /home/ttakahashi/workspace/whiskey
python -m pytest tests -q
python -c "import json; d=json.load(open('scripts/catalog/expressions.json')); print(len(d['expressions']), 'expressions')"
```

DynamoDB への実投入（`--target dev`）は**このタスクでは行わないこと**。人間が判断して実行する。

## 禁止事項

- `lambda/` `infra/` `frontend/` の変更（**検索 API とスナップショット照合は後続タスク**）
- 依存パッケージの追加
- `WhiskeySearch` テーブルに Brand を独立レコードとして入れること（検索結果が汚染される）
- `name` / `normalized_name` / `name_ja` / `name_en` を削ること（検索 API が壊れる）
- 既存シードの `id` を変えること（既存の飲酒ログの参照が壊れる）
- 別名をモデルに生成させること（人手で書く）
- `--target dev` の実行
- コミット・プッシュ・マージ

## 完了条件

- `python -m pytest tests -q` が全て通る
- `scripts/catalog/brands.json` と `expressions.json` が存在し、**アラン 10年を含む**
- 既存 50 銘柄が全て新スキーマへ移行され、`id` が維持されている
- `catalog_key` が決定論的で、同一年数・別 expression を区別できる
- `CLAUDE.md` の prd 投入手順の乖離が是正されている
- `git diff` の変更が `scripts/catalog/` `scripts/local/` `scripts/insert_whiskeys_to_dynamodb.py`
  `tests/` `CLAUDE.md` に収まっている
