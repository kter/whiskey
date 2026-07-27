# Task 31: ブランド提案の昇格ツール（出現件数による足切りと品質フラグ）

## 背景

楽天 1,000 件の抽出が完走し、未知ブランドの提案が 341 件（重複統合後）出た。
全件を人手で承認するのは非現実的なので、**出現件数で足切りして承認する**方針を採る。

実測したトレードオフ:

| 閾値 | ブランド数 | 未知出現のカバー率 |
|---|---|---|
| >=1 | 341 | 100% |
| **>=2** | **78** | **48.7%** |
| >=3 | 31 | 30.4% |

**`>=2`（78 件）を既定とする。** 取りこぼしたブランドは、実際にユーザーが撮影して
`ambiguous` になった時点で個別に追加する運用にする。

抽出結果は `scripts/catalog/extracted_expressions.json`（802 件、`brand_ja` / `brand_en` /
`source_title` を保持）にあり、**Bedrock を再度呼ばずに再グループ化できる。**

### 78 件を目視して判明した品質問題（対処必須）

1. **企業名がブランドとして出ている**: `サントリー` / `ニッカウヰスキー` / `キリン` / `マルス`
2. **商品名の断片**: `ニッカ ウイスキー シングルモルト 余市`（本来は「余市」）、
   `シングルモルト静岡`（本来は「静岡」）、`キリンウイスキー 陸`（本来は「陸」）
3. **統合し損ねた重複**: `マツイ` / `マツイウイスキー`、`ザ フェイマスグラウス` / `フェイマス グラウス`

3 は正規化の取りこぼしである。`normalize_label`
（`scripts/extract_whiskey_names_claude_sonnet.py:89-92`）は空白を 1 つに畳むだけで
**除去しない**ため、`フェイマスグラウス` と `フェイマス グラウス` が別物になる。

## 対象リポジトリ

`/home/ttakahashi/workspace/whiskey`（ブランチ `fix/brand-detection-canonical-name`）

## スコープ

新規スクリプト `scripts/catalog/promote_proposals.py` と `tests/` のみ。
`lambda/` `infra/` `frontend/` は触らないこと。
**`scripts/catalog/brands.json` を自動で書き換えないこと**（後述の `--apply` を明示したときのみ）。

## 実装内容

### 1. 空白非依存の比較キーを追加

日本語のブランド名は空白の有無が揺れる。比較用のキーに
**空白を完全に除去した形**を追加し、`フェイマス グラウス` と `フェイマスグラウス` が
同一グループになるようにする。

**ただし英語名では空白除去を適用しない**（`Glen Grant` と `Glengrant` は同一視してよいが、
過度な結合で別ブランドを誤統合する危険があるため、CJK を含む文字列に限ること）。

既存の `comparison_keys`（冠詞 `the ` / `ザ・` の除去）は維持する。

### 2. 昇格ツール `scripts/catalog/promote_proposals.py`

```
python scripts/catalog/promote_proposals.py \
  --extracted scripts/catalog/extracted_expressions.json \
  --min-occurrences 2 \
  [--apply]
```

動作:

1. `extracted_expressions.json` を読む
2. 既知ブランド（`brands.json`）に一致するものを除外
3. 新しい比較キーでグループ化し、出現件数を合算
4. `--min-occurrences`（既定 2）未満を除外
5. **レビューファイル `scripts/catalog/pending_brands.json` を出力**する
6. `--apply` を明示したときのみ `brands.json` へマージする。
   **既定では絶対にマージしないこと**

`--apply` 時の追記内容:

- `brand_key`: 英語表記があればそこから決定論的なスラッグ、無ければ日本語からの安定キー
- `brand_ja` / `brand_en`: 最も出現数の多い表記
- `aliases`: **観測された表記のみ**。モデルに生成させたものを含めないこと
- 既存 `brands.json` のエントリは**変更しない**（追記のみ）
- `brand_key` が既存と衝突する場合はエラーで中断する

### 3. 品質フラグ（人手レビューを助ける）

レビューファイルの各エントリに `warnings` を付ける。
**特定の企業名・ブランド名をコードにリテラルで書かないこと**（Task 28 の教訓）。
構造的なルールで判定する:

- `contains_generic_term`: 表記に `ウイスキー` / `ウィスキー` / `シングルモルト` /
  `whisky` / `whiskey` / `single malt` 等の一般語を含む → 商品名の断片の疑い
- `prefix_of_other_candidate`: 正規化後の表記が、他の候補の**先頭に一致**する
  → 企業名・親ブランドの疑い（`サントリー` が `サントリー ローヤル` の先頭にある等）
- `single_variant_only`: 表記のバリエーションが 1 つしかない → 検証材料が乏しい
- `very_short`: 正規化後 2 文字以下

一般語のリストは `bottlers.json` と同様に**設定として持つ**こと
（コード中のリテラルではなく、`scripts/catalog/generic_terms.json` 等）。

警告が付いたエントリも**除外はしない**。人が判断できるよう並べて出すだけにする。
出力は出現件数の降順、警告付きは末尾にまとめるか明示的にマークすること。

### 4. サマリ出力

- 抽出総件数 / 既知一致で除外 / 閾値未満で除外 / 昇格候補数
- 警告種別ごとの件数
- `--apply` 時は追記したブランド数

## テスト（Bedrock を呼ばないこと）

1. **`フェイマス グラウス` と `フェイマスグラウス` が 1 グループに統合される**
2. **`ザ フェイマスグラウス` も同じグループに入る**（冠詞 + 空白の複合）
3. 英語名では過度な空白除去による誤統合が起きないこと
   （`Arran` と `Aran` が別グループのままであること）
4. `--min-occurrences 2` で 1 件のみのブランドが除外される
5. **既定（`--apply` なし）では `brands.json` が一切変更されない**
6. `--apply` で追記され、既存エントリが変更されないこと
7. `brand_key` の衝突でエラー終了すること
8. `aliases` に観測されていない表記が入らないこと
9. 品質フラグ:
   - 一般語を含む表記に `contains_generic_term` が付く
   - 他候補の先頭に一致する表記に `prefix_of_other_candidate` が付く
   - **企業名・ブランド名がコードにリテラルで書かれていないこと**
     （`generic_terms.json` から 1 語削除したら、その語の判定が効かなくなる）

## 検証コマンド（必ず全て実行して結果を報告すること）

```bash
cd /home/ttakahashi/workspace/whiskey
python -m pytest tests -q
python scripts/catalog/promote_proposals.py --extracted scripts/catalog/extracted_expressions.json --min-occurrences 2
git diff --stat scripts/catalog/brands.json   # 変更が無いことを確認
```

## 禁止事項

- `lambda/` `infra/` `frontend/` の変更
- `--apply` 無しで `brands.json` を変更すること
- 企業名・ブランド名・一般語をコードにリテラルで書くこと（設定ファイルから読む）
- fuzzy スコアによるブランドの自動統合
- モデルに別名を生成させること
- Bedrock の呼び出し（このツールは一切呼ばない）
- コミット・プッシュ・マージ

## 完了条件

- `python -m pytest tests -q` が全て通る
- 既定実行で `brands.json` が変更されないことを `git diff` で確認できる
- `pending_brands.json` が出力され、78 件前後の候補が出現件数降順で並ぶ
- 空白・冠詞の複合ケースが統合されるテストが通る
- `git diff` の変更が `scripts/catalog/` と `tests/` に収まっている
