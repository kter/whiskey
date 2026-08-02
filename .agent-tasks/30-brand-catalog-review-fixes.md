# Task 30: ブランド軸のレビュー指摘を是正する

## スコープ

`scripts/catalog/brands.json` / `lambda/drink-log-analyze/brands.json`（両者は**バイト一致**を保つ）、
`lambda/drink-log-analyze/index.py`（変更1箇所のみ）、`tests/lambda/test_drink_log_analyze.py`。

**触ってはならない**: `infra/` `lambda/drink-logs/` `scripts/catalog/expressions.json`
`scripts/catalog/catalog.py`（`BRAND_KEY_PATTERN` は `^[a-z0-9_]+$` のまま）。

---

## 変更1: region の語彙を既存51件に揃える

新規追加分だけ表記が短くなっている。`region` は `to_dynamodb_item` 経由で検索テーブルへ
そのまま流れるため、2つの語彙が混在すると後で効いてくる。

| brand_key | 現在 | 修正後 |
|---|---|---|
| `kilchoman` | `Islay` | `Scotland/Islay` |
| `port_charlotte` | `Islay` | `Scotland/Islay` |
| `loch_lomond` | `Highlands` | `Scotland/Highlands` |

`macrie_moor` の空の `region` は**そのまま**（蒸留所未確認のため意図的に空）。

## 変更2: `macrie_moor` の別名を追加

英語表記が音写からの逆算になっている疑いがある。`aliases` に
**`"Machrie Moor"`** と **`"マクリムーア"`** を追加する。

`brand_en` と、`distillery_ja` / `distillery_en` / `region` / `country` の4つは
**触らないこと**。蒸留所は意図的に未確認のまま空にしてある。

## 変更3: 空の `distillery_ja` をキーごと出さない

`lambda/drink-log-analyze/index.py` の `_build_candidates`（670行付近）は、
カタログの `distillery_ja` が空文字でも `"distillery_ja": ""` を候補に載せてしまう。
`macrie_moor` のように蒸留所が空のブランドで発生する。

**カタログの値が非空のときだけ** `distillery_ja` を設定する。
**`brand_key` は蒸留所が空でも従来どおり付けること。**

この1箇所以外、`index.py` のロジックは変更しない。

## 変更4: 不足しているテスト2件

`tests/lambda/test_drink_log_analyze.py` に追加する。

- **曖昧なブランド名で任意のキーを付けない**こと。
  `analyze.BRAND_CATALOG` を monkeypatch し、正規化後に衝突する2件を入れて、
  候補に `brand_key` も `distillery_ja` も付かないことを検証する。
  既存の `test_duplicate_exact_catalog_names_do_not_attach_an_arbitrary_id` に倣うこと。
  （現行カタログ61件には衝突が無く、この分岐は未到達のまま）
- **ブランドフィールドの型・長さ検証**。`_validate_model_output` が
  `"brand_ja": 123` と 201文字の `brand_en` に対して `None` を返すこと。

あわせて、変更3の回帰テストとして **`macrie_moor` のように蒸留所が空のブランドでは
`distillery_ja` がキーごと存在せず、`brand_key` は付く**ことを検証する。

---

## 受入条件

- `python -m pytest tests` が全通過
- `cd frontend && npm run lint && npm run typecheck && npx vitest run && npm run generate` が全通過
- `cmp scripts/catalog/brands.json lambda/drink-log-analyze/brands.json` が**バイト一致**
- `git diff --stat -- infra/ scripts/catalog/expressions.json scripts/catalog/catalog.py lambda/drink-logs/` が**空**
- 全 `brand_key` が `^[a-z0-9_]+$` に適合
- `brands.json` の整形は既存の `promote_proposals.py` の書き出しに合わせ `indent=2` を維持
- 依存追加なし
- **蒸留所が未確認のブランドに推測を書かないこと**
