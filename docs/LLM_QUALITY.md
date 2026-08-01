# LLM品質監視

銘柄認識の変更前後を同じ画像で比較するための評価手順です。
実写真はローカルだけに置き、リポジトリには正解ラベルと画像内容のsha256を使ったファイル名だけを残します。

## 現在LLMを使用している箇所

`lambda/drink-log-analyze/index.py` は実行時に写真から銘柄と飲み方を判別します。
Amazon BedrockのConverse APIを使い、既定モデルは`jp.anthropic.claude-sonnet-4-6`です。
`BEDROCK_MODEL_ID`が`BEDROCK_MODEL_ALLOWLIST`に含まれることを実行時にも検査するため、CDKの設定とLambdaの検査で二重に制限しています。

`scripts/extract_whiskey_names_claude_sonnet.py` はオフライン処理で楽天の商品名からウイスキー情報を構造化抽出します。
こちらもAmazon BedrockのConverse APIを使いますが、銘柄認識の評価対象ではありません。

IAMステートメントは`infra/lib/bedrock-models.ts`の`bedrockInvokeStatements`で組み立てています。
許可対象となる下記3本のAPAC推論プロファイルARNは`infra/lib/whiskey-infra-stack.ts`で定義しています。

* `jp.amazon.nova-2-lite-v1:0`
* `jp.anthropic.claude-haiku-4-5-20251001-v1:0`
* `jp.anthropic.claude-sonnet-4-6`

環境変数だけで切り替えられるのはこの3本の中だけです。
別のモデルを使うにはIAMとallowlistのコード変更が必要です。

## 測定する指標

`scripts/eval/run_brand_eval.py`の既存`score_evaluation`と集計結果をそのまま使います。
新しい指標は追加しません。

* Confirmed correct / Confirmed wrong / Not confirmed
  * 先頭候補が正解ID / 不正解ID / IDなしのどれだったかを全ケースで分割します。
* Top-1 / Top-3 accuracy
  * 正解IDがあるケースだけを分母にし、先頭または上位3候補に正解IDがある割合を出します。
* False confirmation rate
  * 間違ったIDを確定したケースの割合です。正解IDがない写真で何かを確定した場合も含みます。
* Miss rate
  * 正解IDがあるのに先頭候補を確定できなかったケースの割合です。
* Correct abstention rate
  * 正解IDがない写真で先頭候補を確定しなかった割合です。
* Rejection rate / No candidates rate
  * どの候補にもIDがないケースと、候補自体が空だったケースを分けた診断値です。

全体と撮影条件ごとの集計に加えて、誤確定したケースの画像名 / 正解 / 実際の候補も結果JSONに残ります。
HTTPエラーなどで採点できなかった件数はattempted / scored / error casesで確認します。

## 実写真の準備

必要な依存を入れます。

```bash
python -m pip install -r scripts/requirements.txt
```

GPS EXIFを含む元写真は下記でローカル評価用JPEGへ変換します。
HEIC / HEIF / JPEG / PNG / WebPを再帰的に集め、共有の画像正規化処理で向き補正、RGB化、縮小、JPEG再エンコードを行います。
書き出したファイルを再読込してEXIF / XMP / ICCがないことも検査します。

```bash
python scripts/eval/import_real_photos.py <写真ディレクトリ...> \
  --out scripts/eval/images-real
```

出力名は正規化後の内容のsha256先頭16文字です。
`scripts/eval/images-real/`はgitignore対象なので、画像のバイト列はコミットしません。

下書きマニフェストは現在のdevモデルの先頭候補から作ります。
1ユーザーの日次上限は20件（`ANALYZE_USER_DAILY_LIMIT`）なので、27枚は1日で終わりません。
`--max-cases`で分割し、翌日に`--resume`で残りを処理します。

初回はこちら。

```bash
AWS_PROFILE=dev python scripts/eval/run_brand_eval.py scripts/eval/images-real \
  --target dev --profile dev --max-cases 20 --yes \
  --emit-manifest scripts/eval/manifest.real.json \
  --json /tmp/brand-eval-manifest-resume.json
```

翌日以降はこちら。

```bash
AWS_PROFILE=dev python scripts/eval/run_brand_eval.py scripts/eval/images-real \
  --target dev --profile dev --max-cases 20 --yes \
  --emit-manifest scripts/eval/manifest.real.json \
  --resume /tmp/brand-eval-manifest-resume.json
```

1日目と2日目の間に写真を追加するとマニフェストのダイジェストが変わり、`--resume`ファイルが無効になって完了済みのBedrock呼び出しも再利用できなくなります。

全画像の応答が揃うまでマニフェストは出力されません。
生成された全ケースには`needs_review: true`が入ります。
写真を見て`expected_canonical_name` / `expected_whiskey_id` / `condition` / `notes`を直し、確認済みのケースだけ`needs_review: false`に変更します。
1件でもtrueが残っていると採点は始まりません。
既存の`--emit-manifest`出力はレビュー済みラベルを保護するため上書きされません。意図的に下書きを作り直す場合だけ`--force`を追加してください。

確認後はローカル検査を通します。

```bash
python scripts/eval/run_brand_eval.py scripts/eval/manifest.real.json --dry-run
```

## 実行するタイミングと費用

`BEDROCK_MODEL_ID` / `BEDROCK_MODEL_ALLOWLIST` / `lambda/drink-log-analyze/index.py`のプロンプトを変更するPRでは、変更前と変更後に必ず実行します。
N枚の評価を前後で1回ずつ実行すると、合計2N回のBedrock呼び出しと各呼び出しに伴うAppStateカウンタ消費が発生します。

モデルの世代交代を検討するときにも実行します。
結果はIssue #27でモデルを切り替えるか判断する材料にします。
候補モデルごとにN回のBedrock呼び出しとAppStateカウンタ消費が発生します。

固定スケジュールでの定期実行は推奨しません。
入力 / モデルID / allowlist / プロンプトが同じなら比較材料は増えず、毎回N回のBedrock呼び出しとAppStateカウンタを消費します。
変化する可能性があるのはモデル側なので、AWSのモデル更新やリリースを追い、変更があった時点で実行する方が安く済みます。

## 回帰の確認とベースライン

レビュー済みマニフェストでdev評価を実行します。

```bash
AWS_PROFILE=dev python scripts/eval/run_brand_eval.py scripts/eval/manifest.real.json \
  --target dev --profile dev --max-cases 20 --yes \
  --json scripts/eval/results/2026-08-01-sonnet-4-6.json
```

20件を超える場合は翌日以降に同じファイルを`--resume`へ渡します。
完了した結果JSONは`scripts/eval/results/`へ日付とモデルが分かる名前でコミットします。
変更前後のJSONをgit diffで比較し、全体 / 撮影条件別の正解率、誤確定、未確定とケース単位の応答差を確認します。

数値が変わっただけでベースラインを自動更新してはいけません。
改善か許容可能な差かを人が写真とケース単位の結果で判断してから、新しい結果をベースラインとしてコミットします。

## 実運用から評価セットへの還流

実運用で失敗を見つけても、ユーザーがアップロードした写真を評価に流用してはいけません。
写真は`logs/{user_id}/`に本人のデータとして保存されており、開発者が評価目的で流用してはいけません。

評価セットへ追加できる経路は、621自身が自分の写真を評価用として意図的に選ぶ場合だけです。

* 621自身の元写真を`import_real_photos.py`へ渡す
* 正規化後のsha256名と正解ラベルをマニフェストへ追加する
* `condition`に既存10分類のどれかを設定し、失敗理由を`notes`へ残す
* `needs_review: false`まで人が確認する
* 変更前のベースラインを再実行してから修正案を比較する

この流れで失敗例を追加すると、次のモデル / allowlist / プロンプト変更でも同じ入力を再確認できます。

## 限界

実写真27枚は統計的に十分な数ではありません。
利用者全体の認識率や将来の成功率を推定する用途には使えません。
指標は同じ評価画像と正解ラベルを固定した状態で、モデル / allowlist / プロンプト変更の前後を相対比較する場合にだけ使います。
