# Task 32: 評価ハーネスの採点軸をブランドへ移す

## 背景

実写真27枚の評価セットに対する照合率:

| 層 | 命中 |
|---|---|
| エクスプレッション（`expected_whiskey_id`、現行の採点軸） | **8/27** |
| ブランド / 蒸留所 | **27/27**（カタログ拡充後、オフラインで確認済み） |

現行の `score_evaluation` は `expected_whiskey_id` だけで採点しているため、
**19件が「IDを確定しないのが正解」として扱われる**。結果としてこの評価セットは
モデルの読字力ではなく**カタログの網羅性**を主に測っており、モデル比較の道具として
機能しない。解析はブランドを返すようになったので、採点軸を移す。

## スコープ

`scripts/eval/run_brand_eval.py` `scripts/eval/manifest.schema.json`
`scripts/eval/manifest.real.json` `tests/eval/` `docs/LLM_QUALITY.md`。
**`lambda/` `infra/` `frontend/` `scripts/catalog/` は変更しない。**

---

## 変更1: マニフェストに `expected_brand_key` を追加

- `manifest.schema.json` に**任意**の `expected_brand_key`（string または null）を追加する。
- `validate_manifest_data` にも同じ検査を足す。
- **既存の `expected_whiskey_id` / `expected_canonical_name` は残す。**
  エクスプレッション層の指標は副次指標として残すため。

**正解データなので、実行時にカタログから導出してはならない。** マニフェストに
書かれた値だけを使うこと。カタログを直したら正解が変わる、という状態にしない。

## 変更2: `expected_brand_key` の提案コマンド

621 が27件を手で埋めるのは非効率なので、提案を生成する。

`--propose-brand-keys <manifest>` を追加する（**AWS を一切呼ばない**ローカル処理）。

- `scripts/catalog/brands.json` を読み、各ケースの `expected_canonical_name` を
  正規化して `brand_ja` / `brand_en` / `distillery_ja` / `distillery_en` / `aliases`
  と部分一致で照合する。
- **一意に決まった場合のみ**値を書き込む。0件または2件以上なら `null` にし、
  そのケースの `notes` に「要確認: ブランドを特定できませんでした」を追記する。
- 標準出力に「ケース番号 / 銘柄名 / 決まった brand_key（または未決定）」の一覧を出す。
- **既存ファイルの上書きは `--force` を要求する**（タスク28 と同じ保護。
  レビュー済みラベルを消さない）。

## 変更3: ブランド指標を追加する

`score_evaluation` に**ブランド層の判定を追加**する。既存のエクスプレッション層の
キーと計算は**変更しない**（`RESULT_VERSION` の意味も変えない）。

先頭候補の `brand_key` を `expected_brand_key` と比較し、以下を足す:

- `brand_confirmed_correct`: 先頭候補に `brand_key` があり、期待値と一致
- `brand_confirmed_wrong`: 先頭候補に `brand_key` があるが、期待値と不一致
- `brand_not_confirmed`: 先頭候補に `brand_key` が無い
- `actual_brand_key`: 実際の値（診断用）

`expected_brand_key` が `null` のケースは**ブランド指標の分母から除外**すること
（「正解が不明」と「正解が無い」を混同しない）。除外件数を集計に出す。

集計（`_aggregate_records`）とレポート出力にも、ブランド層の
**正解率・誤確定率・未確定率**を追加する。**全体と撮影条件別の両方**で出すこと。

## 変更4: ドキュメント

`docs/LLM_QUALITY.md` の「測定する指標」に、ブランド層が**主指標**、
エクスプレッション層が**副次指標（カタログ命中率）**であることと、その理由
（エクスプレッションは無限に増え続けるためカタログを完成できない）を追記する。

`--propose-brand-keys` の使い方も手順に加える。

---

## テスト（`tests/eval/`）

- `expected_brand_key` を持つマニフェストが検証を通ること、型違いが弾かれること
- ブランド一致・不一致・未確定の3分岐が正しく分類されること
- **`expected_brand_key` が null のケースがブランド指標の分母に入らない**こと
- `--propose-brand-keys` が一意のときだけ値を入れ、曖昧・不一致では `null` にして
  `notes` に印を残すこと
- `--propose-brand-keys` が既存ファイルを `--force` 無しで上書きしないこと
- 既存のエクスプレッション層の指標が**値として変わらない**こと（回帰）

## 受入条件

- `python -m pytest tests` が全通過
- `git diff --stat -- lambda/ infra/ frontend/ scripts/catalog/` が**空**
- `score_evaluation` の既存キーと `RESULT_VERSION` が変わっていないこと
- `--propose-brand-keys` が AWS を呼ばないこと
- 依存追加なし
