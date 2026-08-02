# Task 33: 共有蒸留所の抑制をテストで固定する

## スコープ

`tests/lambda/test_drink_log_analyze.py` と、
`lambda/drink-log-analyze/index.py` の**コメントのみ**。
**照合の挙動は一切変えないこと。**
`brands.json`（2ファイル）・`infra/` `lambda/drink-logs/` `frontend/` `scripts/` は変更しない。

## 背景

`_load_brand_catalog` は、蒸留所名に由来する照合名のうち **複数ブランドが共有するもの**、
および **他ブランドの固有名と衝突するもの** を登録しない仕組みを持っている。
実カタログ60件では以下が該当する（実在の事実であり、データの誤りではない）。

| 蒸留所名 | 共有するブランド |
|---|---|
| Midleton / ミドルトン | `jameson`, `redbreast` |
| Nikka Whisky / ニッカウヰスキー | `nikka`, `taketsuru` |
| Buffalo Trace | `blantons`, `buffalo_trace` |
| Bruichladdich | `bruichladdich`, `port_charlotte` |

**1つの蒸留所が複数ブランドを作る**ため、蒸留所名だけではブランドを特定できない。
勝手に一方を選ばない現在の挙動は正しい。

しかしこの仕組みには**テストが無く**、
`test_real_brand_catalog_has_no_normalized_name_collisions` は抑制**後**の
`_normalized_names` を見ているため、蒸留所側については常に通ってしまう。
ブランドを追加した将来の担当者にとって、失敗は**静かな不一致**として現れる。

## 追加するテスト

1. **共有蒸留所の抑制**（実カタログに対して）:
   `brand_ja="ミドルトン蒸溜所"` / `brand_en="Midleton Distillery"` /
   `brand_en="Midleton"` / `brand_ja="ニッカウヰスキー"` / `brand_en="Nikka Whisky"`
   が、いずれも **`brand_key` の付かない候補**になること。
2. **同名ブランドが優先されること**:
   `brand_en="Bruichladdich Distillery"` → `bruichladdich`（`port_charlotte` ではない）、
   `brand_en="Buffalo Trace Distillery"` → `buffalo_trace`（`blantons` ではない）。
3. **削りすぎの防止**:
   `brand_ja="蒸溜所"` / `brand_en="The "` / `brand_en="Distillery"` が
   いずれも `brand_key` を付けないこと。加えて、`BRAND_CATALOG` のどのブランドの
   `_normalized_names` にも**空文字が含まれない**こと。
4. **接辞のアンカー**:
   `brand_en="Yuza Distillery Co."` と `brand_ja="遊佐蒸溜所です"` が
   `yuza` に解決**されない**こと（末尾・先頭以外では削らない）。
5. **`_normalized_brand_name_variants` の直接テスト**:
   `"The Yuza Distillery"` の結果に `yuza` の正規化形が含まれること、
   `"遊佐蒸溜所"` に `遊佐` の正規化形が含まれること、
   `"蒸溜所"` の結果に空文字が含まれないこと、
   `"Theakston"` が接頭辞除去の対象にならないこと（空白が無いため）。
6. **接頭辞のみの英語名**: `brand_en="The Glenlivet"` → `glenlivet`。

## 既存テストの修正

`test_real_brand_catalog_has_no_normalized_name_collisions` の
`assert len(analyze.BRAND_CATALOG) == 60` を**衝突判定の後ろへ移す**
（または `>= 60` に緩める）。ブランドを1件足しただけで件数不一致が先に落ち、
本来の衝突レポートが見えなくなるため。

## コメントの追記

`index.py` の抑制処理の箇所に、**複数ブランドが共有する蒸留所名は意図的に
登録しない**ことと、実データの例（Midleton → jameson/redbreast、
Nikka Whisky → nikka/taketsuru）を明記する。将来ブランドを追加した担当者が、
自分の蒸留所名が突然マッチしなくなった理由を追えるようにする。

## 受入条件

- `python -m pytest tests` が全通過
- **既存の照合結果が全て不変**。次の点検が通ること:
  `遊佐蒸溜所` / `The Yuza Distillery` / `遊佐` → `yuza`、
  `厚岸蒸留所` / `厚岸` → `akkeshi`、`マクリームーア` → `arran`、
  `The Glenlivet` → `glenlivet`、`新潟亀田蒸溜所` → `otani`
- `git diff --stat -- infra/ lambda/drink-logs/ frontend/ scripts/` が**空**
- `brands.json` 2ファイルが**無変更**かつ相互にバイト一致
- `index.py` の変更が**コメントのみ**であること
- 依存追加なし
