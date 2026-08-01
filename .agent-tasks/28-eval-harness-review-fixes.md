# Task 28: 評価ハーネスのレビュー指摘を是正する

## 背景

タスク26・27 の成果に対する独立レビューで、**重要4件**の指摘が出た。いずれも happy path の
バグではないが、①手作業のラベルを消し飛ばす ②検証に落ちた画像が評価セットに紛れ込む
③public リポジトリにコミットする JSON に開発者のホームディレクトリが載る、という実害がある。

## スコープ

`scripts/eval/run_brand_eval.py` `scripts/eval/import_real_photos.py` `tests/eval/`
`docs/LLM_QUALITY.md` のみ。**`lambda/` `infra/` `frontend/` は変更しない。**
`normalize_image` と `score_evaluation` のロジック、`RESULT_VERSION` の意味は変えない。

---

## 変更1: メタデータ検証に落ちた出力を残さない

`import_real_photos.py` の `import_photo` は `_write_atomic` で書き出した**後**に
`verify_metadata_free_jpeg` を呼ぶ。検証が落ちると `import_photos` が失敗として記録して
続行するが、**ファイルは `scripts/eval/images-real/` に残る**。

`build_draft_seed_manifest` は取り込みレポートではなく**ディレクトリを glob する**ため、
EXIF 検査に落ちた画像が次回の評価でマニフェストに載り、S3 にアップロードされる。

- 検証が例外を投げたら、**再送出の前に出力ファイルを削除する**。
- **冪等分岐にも適用すること**: 既存ファイルとバイト列が一致してスキップした場合でも、
  その後の検証に落ちたなら削除する。メタデータを持つファイルが実行後に生き残ってはならない。

**テスト**: `verify_metadata_free_jpeg` を失敗するようスタブし、
①出力パスが実行後に存在しないこと ②次のファイルの取り込みは続行されること
③終了コードが 1 であること。

## 変更2: レビュー済みマニフェストを黙って上書きしない

`main()` は `save_json_atomic(args.emit_manifest, draft)` を無条件に呼ぶ。
`docs/LLM_QUALITY.md` が案内する手順どおりに進めると事故が起きる:

1. 2日目の実行で `scripts/eval/manifest.real.json` が生成される
2. 621 が27件を手作業で確認し `needs_review` を false にする
3. **同じコマンドをもう一度叩く**（全件成功済みなので `if not selected_indices:` の
   早期 emit 分岐に入る）→ 記録から下書きを作り直し、**手書きラベルを全消去**

Bedrock 呼び出しゼロ・確認プロンプトなし・差分表示なしで消える。しかも
`manifest.real.json` は `.gitignore` で救済済み（コミット対象）なので、
コミット前なら復旧手段がない。

- `--emit-manifest` の出力先が**既に存在する場合は書き込みを拒否**し、
  「レビュー済みラベルを含む可能性がある。置き換えるには `--force`」という趣旨の
  `ValueError` を投げる。
- `--force` フラグを追加し、指定時のみ上書きを許可する。
- **書き込み箇所は2つある**（`if not selected_indices:` の早期 emit と、
  完走後の emit）。**両方に適用すること。**

**テスト**: ①既存ファイルに対する2回目の `--emit-manifest` が終了コード 1 で、
ファイルが**バイト列として不変**であること ②`--force` を付ければ上書きされること。

## 変更3: 結果 JSON に絶対パスを書かない

`build_result_document` の `"manifest": str(manifest_path.resolve())` は
`/home/<ユーザー名>/workspace/whiskey/scripts/eval/manifest.real.json` を出力する。

このフィールド自体は既存だが、今回の変更で **`scripts/eval/results/*.json` が
gitignore から救済され、`docs/LLM_QUALITY.md` が「完了した結果JSONは
`scripts/eval/results/` へコミットします」と案内している**ため、public リポジトリに
開発者のホームディレクトリ構成と OS ユーザー名が載る経路ができた。

- **リポジトリルートからの相対パス**を書く。リポジトリ外なら `manifest_path.name` に落とす。
- 絶対パスを期待している既存テストがあれば追随させる。

## 変更4: 下書き実行の結果 JSON を見分けられるようにする

下書き用の seed マニフェストは全ケースの `expected_whiskey_id` が `None` なので、
`score_evaluation` は確定候補をすべて `confirmed_wrong` / `false_confirmation` として採点する。
emit 経路はこの指標を表示しないが、**結果ドキュメントには通常の実行と同じ
`result_version`・同じ既定ファイル名で残る**。本物の評価結果と取り違えられる。

- `--emit-manifest` が有効な実行の結果ドキュメントに `"mode": "manifest_draft"` を追加する
  （それ以外は `"evaluation"`）。
- **`RESULT_VERSION` の意味と `score_evaluation` は変更しないこと。** 追加フィールドのみ。

## 変更5: 部分実行ガードのテストを追加

挙動は既に正しいが、テストが無い。**この経路が壊れると、不完全な自己生成マニフェストが
正解として固定される**ため、最も価値の高い未テスト分岐だ。

- 全件に満たない `--emit-manifest` 実行が、**マニフェストファイルを1つも書かない**こと
- pending 件数のメッセージを出すこと
- `build_draft_manifest` が、200 応答の無いケースがあれば例外を投げること

## 変更6: `docs/LLM_QUALITY.md` の是正

- **帰属の訂正**: `infra/lib/bedrock-models.ts` が組み立てるのは **IAM ステートメント**で、
  3本の推論プロファイル ARN の定義は `infra/lib/whiskey-infra-stack.ts` にある。
- **警告を1文追加**: 1日目と2日目の下書き実行の間に写真を追加すると
  マニフェストのダイジェストが変わり、`--resume` ファイルが無効になる
  （完了済みの Bedrock 呼び出しが捨てられる）。
- 下書き生成の節に **`--force` の必要性**を書く。

---

## 受入条件

- `python -m pytest tests` が全通過
- `git check-ignore -v scripts/eval/images-real/x.jpg scripts/eval/manifest.example.json scripts/eval/results/x.json`
  が期待どおり（前2つは救済済み＝報告なし、images-real は無視）
- `git diff --stat` に `lambda/` `infra/` `frontend/` が現れないこと
- 依存追加なし
- **入力パスと元ファイル名は引き続き stderr にのみ出ること**（stdout のレポートにも
  書き出すファイルにも入らない）
- **emit される下書きの全ケースが `needs_review: true` を保ち、`load_manifest` が
  1件でも残っていれば採点を拒否し続けること**
- `CLIENT_RESIZE_ATTEMPTS` と 3,670,016 バイト上限が
  `frontend/utils/imageResize.ts` と一致し続けること
