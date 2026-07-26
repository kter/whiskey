# Task 24 (Phase 0): 銘柄認識の評価ハーネス

## 背景

写真からの銘柄判定で誤判定が続いている（カリラ→「カオルイラ」、アラン10年→「Arran」）。
コミット `770b3cd` で照合ロジックを改善したが、**精度を測る手段が無い**ため、
次の大きな設計変更（転写ベースへの作り替え）の効果を判定できない。

このタスクでは**評価ハーネスだけ**を作る。認識ロジックには一切手を入れない。

飲酒ログというドメイン上、**最重要指標は「誤確定率」**である。
黙って間違えて記録するより、棄却してユーザーに選ばせる方が良い。
したがって単純な正解率ではなく、後述の 4 指標を分けて測る。

## 対象リポジトリ

`/home/ttakahashi/workspace/whiskey`（ブランチ `fix/brand-detection-canonical-name`）

## スコープ外（絶対に触らないこと）

- `lambda/` 配下の一切の変更（認識ロジック・プロンプト・照合）
- `infra/` 配下の変更
- `frontend/` 配下の変更
- カタログ（DynamoDB）のスキーマやデータの変更

**このタスクの成果物は `scripts/eval/` 配下の新規ファイルとそのテストのみ。**

## 実装内容

### 1. マニフェスト形式 `scripts/eval/manifest.schema.json` と実例

評価セットは「画像 + 正解 + 撮影条件」の一覧で定義する。

```json
{
  "version": 1,
  "cases": [
    {
      "image": "images/yamazaki12_front.jpg",
      "condition": "bottle_front",
      "expected_whiskey_id": "yamazaki-12",
      "expected_canonical_name": "山崎 12年",
      "notes": "任意"
    }
  ]
}
```

`condition` は以下の列挙とする（プランで洗い出した、転写だけでは解けない条件を含む）:

`bottle_front` / `bottle_angle` / `reflection_or_condensation` / `partially_occluded` /
`box_only` / `miniature` / `glass_only` / `multiple_bottles` / `low_resolution` / `back_label_only`

- `expected_whiskey_id` が `null` の場合は「カタログに存在しない商品」を意味し、
  **正しい挙動は「確定しないこと」**とする（`glass_only` などで使う）。
- 画像パスはマニフェストからの相対パス。

`scripts/eval/manifest.example.json` に、上記の条件を一通り含む記入例を置く。

### 2. 実行スクリプト `scripts/eval/run_brand_eval.py`

マニフェストの各画像を **dev の analyze Lambda に通し**、結果を集計する。

**実行モード:**

- `--target dev`（必須の明示指定）: 実際に S3 へアップロードして Lambda を invoke する
- `--dry-run`: AWS を一切呼ばず、マニフェストの妥当性検証と件数レポートのみ

**dev 実行の手順（1 ケースあたり）:**

1. 画像を `tmp/{eval_user}/{uuid4}.{ext}` として `whiskey-images-dev-{account}` へアップロード
2. `drink-log-analyze-dev` を `Invoke` する。イベントは API Gateway 形式で、
   `requestContext.authorizer.claims.sub` を `{eval_user}` にする
   （既存のテストイベント形状は `tests/lambda/test_drink_log_analyze.py` の `_event` を参照）
3. レスポンス JSON を保存する
4. **アップロードした画像を必ず削除する**（成功・失敗いずれの場合も）

**アカウント検証必須**: `scripts/local/seed_whiskeys.py:70-75` と同じ要領で
`sts:GetCallerIdentity` を呼び、アカウントが dev（`031921999648`）であることを確認してから実行する。
違えば即座に中断する。

**コスト上限の保護（重要）:**

analyze Lambda には `ANALYZE_GLOBAL_DAILY_LIMIT = 50`（1 日あたり全体 50 回）のカウンタがあり、
1 解析で user 枠 1 + global 枠 1 以上を消費する（`lambda/drink-log-analyze/index.py:178-236`）。
評価セットが大きいと**通常利用の枠を食い潰す**。したがって:

- デフォルトの最大実行件数を **20 件**とし、超える場合は `--max-cases` の明示を要求する
- 実行前に「何件・推定でカウンタをいくつ消費するか」を表示し、`--yes` が無ければ確認を求める
- レスポンスが 429 / 503（枠超過）だった場合は**即座に中断**し、それまでの結果を保存する
- `--resume <結果ファイル>` で、既に成功したケースをスキップして続行できるようにする

### 3. 指標の算出

各ケースについて、レスポンスから以下を判定する。
現行のレスポンス形状は `{candidates:[{brand_text, whiskey_id?, match_source, confidence, ...}], ...}`。

**「確定した」の定義**: `candidates[0]` に `whiskey_id` が存在すること。

| 指標 | 定義 |
|---|---|
| **top-1 正解率** | `candidates[0].whiskey_id == expected_whiskey_id` の割合 |
| **top-3 正解率** | 先頭 3 候補のいずれかの `whiskey_id` が期待値と一致する割合 |
| **誤確定率** | 確定したが `whiskey_id != expected_whiskey_id` の割合（**最重要**）。`expected_whiskey_id` が `null` のケースで確定した場合も誤確定に数える |
| **棄却率** | どの候補にも `whiskey_id` が無い割合 |

**全体と `condition` 別の両方**を出す。分母が 0 の条件は「該当なし」と表示し、0% と誤解させない。

### 4. レポート出力

- 標準出力に人間が読める表（全体 → 条件別 → 誤確定したケースの一覧）
- `--json <path>` で機械可読な結果を保存（`--resume` の入力にもなる）
- 誤確定ケースは「期待値 / 実際の brand_text / `match_source`」を並べて出す

**銘柄名は評価用データなのでレポートには出してよい**が、
`label_text` は analyze のレスポンスに含まれないので扱わない。

### 5. 合成画像ジェネレータ `scripts/eval/make_synthetic_labels.py`

実写真が揃うまでのつなぎとして、`bottle_front` 条件の合成ラベル画像を生成する。

- `scripts/local/seed_data/whiskeys.json` から銘柄を読み、
  ラベル風の画像（ブランド名・年数・`SINGLE MALT` 等）を Pillow で描画する
- 生成と同時に、対応するマニフェストを出力する
- **これは `bottle_front` の下限を測るためのものであり、実写真の代替にはならない**旨を
  スクリプトの docstring と生成物の `notes` に明記すること

Pillow は既に Lambda レイヤーと開発環境で使われている（新規依存ではない）。

### 6. テスト `tests/eval/test_run_brand_eval.py`

**AWS を呼ばないこと。** 集計ロジックを純粋関数として切り出し、それをテストする。

- top-1 / top-3 / 誤確定 / 棄却 の 4 指標が、作り込んだレスポンス群に対して正しく出る
- `expected_whiskey_id: null` のケースで確定したら誤確定に数えられる
- `condition` 別集計で、分母 0 の条件が 0% ではなく「該当なし」になる
- マニフェストの検証（未知の `condition`、画像パス欠落、必須フィールド欠落）でエラーになる
- `--max-cases` の既定 20 を超えるマニフェストが、明示フラグ無しでは実行を拒否する
- 429/503 で中断し、それまでの結果が保存される（Lambda クライアントはスタブ）

既存のテストの流儀（`tests/lambda/test_insert_whiskeys_script.py` がスクリプトのテスト例）に合わせること。

## 検証コマンド（必ず全て実行して結果を報告すること）

```bash
cd /home/ttakahashi/workspace/whiskey
python -m pytest tests -q
python scripts/eval/run_brand_eval.py --dry-run scripts/eval/manifest.example.json
```

`--target dev` の実行は**このタスクでは行わないこと**（実際の Bedrock 課金とカウンタ消費が発生するため、
人間が判断して実行する）。

## 禁止事項

- `lambda/` `infra/` `frontend/` の変更
- 依存パッケージの追加（`requirements*.txt` / `pyproject.toml` / `package.json`）
- テストから AWS を呼ぶこと
- 評価スクリプトを `--target dev` で実際に実行すること
- アップロードした評価画像を消さずに残すこと
- コミット・プッシュ・マージ

## 完了条件

- `python -m pytest tests -q` が全て通る
- `--dry-run` がマニフェスト例に対して動作し、件数と条件別内訳を表示する
- 4 指標の算出が純粋関数として切り出され、テストで固定されている
- コスト上限の保護（既定 20 件、429/503 での中断、`--resume`）が実装されている
- `git diff` の変更が `scripts/eval/` と `tests/eval/` に収まっている
