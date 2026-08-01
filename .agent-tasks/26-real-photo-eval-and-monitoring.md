# Task 26: 銘柄認識の評価を実写真で回せるようにし、継続監視を設計する（Issue #25）

## 背景

Issue #25:

> LLMを使用しているが、継続的な監視と品質保証をするにはどうすればよいか。まずは検討する必要がある。
> 反復的なフィードバックループについても検討したい

評価ハーネス `scripts/eval/run_brand_eval.py` は既にあり（テスト `tests/eval/test_run_brand_eval.py` 47件通過）、
`--target dev` で実際の `drink-log-analyze-dev` を呼んで採点できる。**足りないのは2つ**:

1. **評価に使う画像が合成ラベル10枚しかない**。`scripts/eval/make_synthetic_labels.py` 自身が
   「実写真の代替にはならない」と明記している。実写真27枚は 621 のローカルにあるが、
   マニフェスト化されていない。
2. **継続実行の設計が無い**。いつ・何を契機に走らせ、どう劣化を検知し、結果をどこに残すかが未定義。

## 動かせない制約（設計の前提）

- **リポジトリは PUBLIC**（`kter/whiskey`）。
- **実写真には GPS EXIF が入っている**（確認済み）。このアプリは「座標を永続化しない」を
  設計の背骨にしており、その検証用写真を public リポジトリに置くのは自己矛盾。
- したがって **実写真のバイト列は絶対にコミットしない**。git に入るのはラベルと
  ハッシュだけ。

## スコープ

`scripts/eval/` `tests/eval/` `docs/` `.gitignore` `scripts/requirements.txt`。
**`lambda/` `infra/` `frontend/` は変更しない**。既存ハーネスの採点ロジック
（`score_evaluation`）とその契約も変更しない。

---

## 変更1: 実写真の取り込みスクリプト

新規 `scripts/eval/import_real_photos.py`。

```
python scripts/eval/import_real_photos.py <入力ディレクトリ...> --out scripts/eval/images-real
```

振る舞い:

- 入力ディレクトリから HEIC/HEIF/JPEG/PNG/WebP を再帰的に集める（動画等は無視）。
- **`pillow-heif` を使って HEIC を読む**（621 承認済み。`scripts/requirements.txt` に
  ピン止めして追加する。`pillow_heif.register_heif_opener()` が必要）。Pillow は既存依存。
- 正規化は **`lambda/common/python/whiskey_common/images.py` と同じ順序・同じ上限**に揃えること
  （ヘッダーから寸法検査 → デコード → `exif_transpose` → RGB 化 → 必要なら縮小 →
  メタデータ無しで JPEG 再エンコード、最終 3.5MB 以下）。評価対象は analyze が実際に
  受け取るバイト列と同じ性質でなければ、測っている対象がずれる。
  **実装を写経せず import して使うこと**（`sys.path` に `lambda/common/python` を足す。
  既存スクリプトの流儀を確認して合わせる）。
- **出力画像に EXIF/XMP/ICC が1バイトも残らないことを検証**し、残っていたら異常終了する。
  特に GPS。検証は書き出したファイルを読み直して行う（「渡さなかったから大丈夫」ではなく実測）。
- 出力ファイル名は入力名に依存させない。**内容の sha256 の先頭16文字**（例: `a1b2c3d4e5f60718.jpg`）
  にする。元ファイル名は撮影場所や日付を含みうるうえ、public な manifest に載る。
- 各画像の sha256（全長）、出力サイズ、元形式を記録した**取り込みレポート**を stdout に出す。

## 変更2: 実写真は git に入れない

- `.gitignore` に `scripts/eval/images-real/` を追加する。
- `git check-ignore` で無視されることを受入条件に含める。
- `scripts/eval/images/`（合成10枚）は**そのまま残す**。形式確認と CI 用の下限測定に使う。

## 変更3: 下書きマニフェストの生成

正解ラベルを 621 が27枚ぶんゼロから書くのは負担が大きい。**現行モデルの出力を下書きにして、
621 は誤りだけ直す**流れにする。

`run_brand_eval.py` に `--emit-manifest <path>` を追加する（`--target dev` と併用）。

- 各ケースの analyze 応答から `candidates[0]` の銘柄名と `whiskey_id` を
  `expected_canonical_name` / `expected_whiskey_id` の**下書き**として書き出す。
- **`"needs_review": true` を全ケースに必ず立てる**（`manifest.schema.json` に
  boolean プロパティとして追加）。`load_manifest` は `needs_review` が真のケースが
  1件でもあれば**採点を拒否して異常終了**すること。モデルの出力を正解として採点すると
  常に満点になり、測定器として無意味になる。621 が確認して false にしたものだけ採点対象。
- `condition` は自動判定できないので `"bottle_front"` を入れたうえで
  `notes` に「要確認: 撮影条件を実際の写真に合わせて修正すること」と書く。
- 下書き生成には**実写真のパスが必要**なので、入力は「画像ディレクトリ」を受け取る形にする
  （既存の manifest 必須の CLI 構造と衝突しないよう、引数設計は既存に合わせて整えること）。

## 変更4: 継続監視の設計ドキュメント

新規 `docs/LLM_QUALITY.md`。**実装ではなく設計と運用手順**を書く。以下を必ず含めること。

1. **LLM の使用箇所**（現状の事実を書く。憶測を書かない）
   - `lambda/drink-log-analyze/index.py` — 実行時。写真から銘柄・飲み方を判別。
     Bedrock Converse、既定 `jp.anthropic.claude-sonnet-4-6`、`BEDROCK_MODEL_ALLOWLIST` で二重に制限。
   - `scripts/extract_whiskey_names_claude_sonnet.py` — オフライン。楽天商品名から構造化抽出。
   - IAM は `infra/lib/bedrock-models.ts` で APAC の推論プロファイル3本に固定。
     **環境変数だけで切り替えられるのはこの3本の中だけ**である旨を明記。
2. **何を測るか**: 既存の `score_evaluation` が出す指標をそのまま説明する（勝手に増やさない）。
3. **いつ走らせるか**: 以下を提案として明記し、それぞれの費用（1回 = 画像枚数ぶんの
   Bedrock 呼び出し + AppState カウンタ消費）を書く。
   - `BEDROCK_MODEL_ID` / allowlist / プロンプトを変更する PR の前後（必須）
   - モデルの世代交代を検討するとき（Issue #27 の判断材料）
   - 定期実行は**推奨しない**理由も書く（入力が固定なら結果は動かない。動くのはモデル側の
     変更時であり、それは AWS のリリースを追う方が安い）
4. **回帰の見つけ方**: 結果 JSON を `scripts/eval/results/` に日付付きでコミットし、
   diff で劣化が見えるようにする運用を書く。**ベースラインの更新は人の判断で行う**こと。
5. **反復的なフィードバックループ**: 実運用の失敗をどう評価セットに還流させるか。
   **重要な制約を明記すること** — ユーザーの写真は `logs/{user_id}/` に本人のものとして
   保存されており、**開発者が評価目的で流用してはならない**。還流は「621 自身が自分の写真を
   意図的に評価セットへ追加する」経路に限る。
6. **限界**: 27枚は統計的に十分な数ではない。指標は「同一入力での相対比較」にのみ使える。

`README.md` か `CLAUDE.md` の適切な箇所から `docs/LLM_QUALITY.md` へ1行リンクする。

---

## テスト（`tests/eval/`）

- `import_real_photos.py`:
  - 合成した GPS EXIF 付き JPEG を入力すると、**出力に EXIF が1バイトも残らない**こと
  - 出力ファイル名が内容の sha256 由来で、入力ファイル名に依存しないこと
  - 同じ内容の画像を2回取り込んでも同じ名前になること（冪等）
  - 3.5MB / 20MP / 8000px の上限が効くこと
  - 動画など対象外ファイルを無視すること
  - **HEIC はテストで実バイナリを用意しにくいので、pillow-heif の登録が行われることの
    確認までに留めてよい**（実 HEIC のフィクスチャは追加しない）
- `--emit-manifest`:
  - 生成物が `manifest.schema.json` に適合すること
  - 全ケースに `needs_review: true` が立つこと
  - `needs_review: true` を含むマニフェストで採点しようとすると**異常終了**すること
  - `needs_review` を全て false にすれば従来どおり採点できること

## 受入条件

- `python -m pytest tests` が全通過
- `git check-ignore scripts/eval/images-real/x.jpg` が無視を報告すること
- `git diff` が `scripts/` `tests/` `docs/` `.gitignore` `README.md`/`CLAUDE.md` のみ。
  **`lambda/` `infra/` `frontend/` は無変更**
- 追加依存は `pillow-heif` のみ（621 承認済み）。`scripts/requirements.txt` にバージョンを
  ピン止めすること
- **実写真そのものがコミット対象に入っていないこと**（`git status` で確認）
- 既存の `score_evaluation` の採点ロジックと結果 JSON の `result_version` を変更していないこと

## 実装メモ

- 621 の実写真は `~/Downloads/Photos-1-001` と `~/Downloads/Photos-1-001 (2)` にある（HEIC 計27枚）。
  **スクリプトにこのパスをハードコードしないこと。** 引数で受け取る。
- このタスクでは実際の取り込み実行と 621 のラベル確認は行わない。**道具を作るところまで**。
