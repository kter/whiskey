# Task 27 (Phase A2): 楽天商品名からの構造化抽出

## 背景

Task 26 (Phase A1) でカタログを構造化スキーマへ作り替え、アランを追加した。
dev 実機で検証済み: カリラ・アランとも `master:substring` で正典名が出る。

このタスクでは楽天から取得した 1,000 件の商品名を**同じ構造化スキーマへ抽出**し、
カタログのカバレッジを広げる。

取得済みデータ: `rakuten_product_names_20260726_200120.json`（`product_names` に 1,000 件の文字列）

## 実データの実態（必ず踏まえること）

```
【中古・未開栓】【埼玉県内配送限定】イチローズモルト 秩父 オン ザ ウェイ 2019 モルト 700ml 51.5％ ...
ウイスキー4本セット　角、デュワーズ、ブラック＆ホワイト、ベルユニオンジャック40度700ml
グレンリベット　21年【700ml/43%】20250827
ゴールデンカスク マクダフ 10年 2012 63.8% 700ml[ウイスキー][御歳暮 贈り物 御礼 母の日 父の日 御中元]
アラン バレルリザーヴ 700ml 43度 【箱付】
ブナハーブン トチェック ア ガー 46.3度 700ml［並行輸入品］【スコットランド シングルモルト スコッチ ウイスキー アイラ】
```

中古・複数本セット・並行輸入・箱の有無・日付コード・ギフト用語の羅列が混在する。

**現行モデルの実測失敗例（対処必須）:**

```
「ゴールデンカスク マクダフ 10年 2012 63.8%」→ brand: "ゴールデンカスク マクダフ"
```

Golden Cask は**ボトラー**、Macduff が**蒸留所**である。これを 1 つのブランドとして登録すると
存在しないブランドでカタログが汚染される。**`bottler` を独立フィールドに分けること。**

## 対象リポジトリ

`/home/ttakahashi/workspace/whiskey`（ブランチ `fix/brand-detection-canonical-name`）

## 前提

- 抽出モデルは `jp.anthropic.claude-sonnet-4-6`（`EXTRACT_MODEL_ID` で上書き可）。
  **`global.anthropic.claude-sonnet-5` は当アカウントで AccessDenied なので使わないこと。**
  実行は `AWS_PROFILE=dev`。
- Task 26 で作った `scripts/catalog/brands.json` / `expressions.json` のスキーマに合わせる。
- Task 26 の `catalog_key`（商品同一性ハッシュ）生成ロジックを**再利用**すること。重複させない。

## 実装内容

### 1. 抽出スキーマ

`scripts/extract_whiskey_names_claude_sonnet.py` の出力を構造化する。1 商品名につき:

```json
{
  "source_title": "<元の商品名をそのまま>",
  "is_whiskey": true,
  "is_multi_bottle_set": false,
  "brand_ja": "アラン",
  "brand_en": "Arran",
  "distillery_ja": null,
  "bottler_ja": null,
  "bottler_en": null,
  "expression": "バレルリザーヴ",
  "age": null,
  "vintage": null,
  "cask": null,
  "abv": "43",
  "volume_ml": 700,
  "confidence": 0.9
}
```

**抽出の原則:**

- **抽出のみ。発明しない。** 元タイトルに書かれていない情報を補完させない。
  読み取れない項目は `null`
- **`bottler` と `brand`/`distillery` を必ず分離する**（Golden Cask / Macduff 問題）。
  ボトラー物は `brand` を蒸留所名、`bottler` をボトラー名にする
- **`is_multi_bottle_set: true` の商品は除外**（1 タイトルに複数商品が混在するため）
- 中古・並行輸入・箱の有無・配送制限・ギフト用語は**出品の属性であって商品同一性ではない**。
  これらでレコードを分けないこと。ただし除外もしない（商品自体は実在する）
- ウイスキー以外（グラス・つまみ・空瓶等）は `is_whiskey: false` で除外
- 日付コード（`20250827` 等）・型番は無視する

### 2. 別名を生成させない

**`aliases` をモデルに出力させてはならない。** 幻覚が恒久的な「正解」としてカタログに焼き付く。

別名は `scripts/catalog/brands.json`（人手の正本）にのみ存在する。
抽出結果から観測された表記は「候補」として §4 のレビューファイルに出すだけで、
自動で `brands.json` に取り込まないこと。

### 3. 出典の保存

各レコードに以下を保持する:

- `source_title`（元タイトル全文）
- `source`: `"rakuten_bedrock"`
- `extraction_model`: 実際に使ったモデル ID
- `extracted_at`: タイムスタンプ

（`itemCode` / JAN は現在の取得スクリプトが保存していないため対象外。
将来 `fetch_rakuten_names_only.py` が保存するようになったら引き継げる形にしておくこと）

### 4. ブランドの突き合わせとレビューファイル

抽出した `brand_ja`/`brand_en` を既存の `brands.json` に突き合わせる。

- **既知ブランドに一致** → その `brand_key` を使う
- **未知のブランド** → `scripts/catalog/proposed_brands.json` に出力する:
  - 提案する `brand_key`、観測された表記のバリエーション、出現件数、代表的な元タイトル 3 件
  - **`brands.json` には自動でマージしない。** 人手の承認を経てから取り込む

出現件数の多い順に並べること（重要なブランドから承認できるように）。

### 5. 重複排除

Task 26 の `catalog_key` で束ねる。同一性の単位は「同じ液体」:

- **容量・セット本数は同一性に含めない**
- **ボトラー・ヴィンテージ・カスク・エディション・熟成年数は含める**

同じ `catalog_key` が複数の元タイトルから出た場合は 1 レコードにまとめ、
`source_titles` に全てのタイトルを保持する（後から検証できるように）。

### 6. 出力

`scripts/catalog/extracted_expressions.json` に出力する。
**`expressions.json` に直接マージしないこと**（人手の確認を経てから）。

サマリを標準出力に出す: 総件数 / ウイスキー判定件数 / セット除外件数 / 重複排除後の件数 /
既知ブランド一致件数 / 未知ブランド件数。

### 7. コスト保護

- `--limit N` で処理件数を制限できるようにする（既定は全件）
- `--dry-run` で Bedrock を呼ばずにバッチ分割と件数だけ表示
- 実行前に「何バッチ・何コール発生するか」を表示する
- 中断しても途中結果を保存し、再開できるようにする

## テスト

**Bedrock を呼ばないこと。** モデル応答はスタブで与える。

1. `is_multi_bottle_set: true` が除外される
2. `is_whiskey: false` が除外される
3. ボトラー物（Golden Cask / Macduff）で `brand` と `bottler` が分離される
4. 容量違い（700ml / 750ml）の同一商品が**同じ `catalog_key`** に束ねられる
5. ヴィンテージ違い・カスク違いが**異なる `catalog_key`** になる
6. 未知ブランドが `proposed_brands.json` に出力され、`brands.json` は変更されない
7. `aliases` がモデル出力に含まれていても**無視される**（発明した別名を取り込まない）
8. `source_title` が全レコードに保持される
9. 同一 `catalog_key` の複数タイトルが `source_titles` に集約される

## 検証コマンド（必ず全て実行して結果を報告すること）

```bash
cd /home/ttakahashi/workspace/whiskey
python -m pytest tests -q
python scripts/extract_whiskey_names_claude_sonnet.py --input-file rakuten_product_names_20260726_200120.json --dry-run
```

**Bedrock を実際に呼ぶ実行（`--dry-run` なし）はこのタスクでは行わないこと。**
コストが発生するため人間が判断して実行する。

## 禁止事項

- `lambda/` `infra/` `frontend/` の変更
- 依存パッケージの追加
- `brands.json` / `expressions.json` への自動マージ
- モデルに別名を生成させること
- `global.anthropic.claude-sonnet-5` の使用（AccessDenied）
- Bedrock の実呼び出し（`--dry-run` 以外）
- コミット・プッシュ・マージ

## 完了条件

- `python -m pytest tests -q` が全て通る
- `--dry-run` がバッチ数とコール数を表示する
- ボトラー分離・セット除外・重複排除のテストが存在し、通る
- `proposed_brands.json` の出力先が用意され、`brands.json` は自動変更されない
- `git diff` の変更が `scripts/` と `tests/` に収まっている
