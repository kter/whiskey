# Task 25 (Phase 0 是正): 評価ハーネスを実際に動く状態にする

## 背景

Task 24 で作った評価ハーネス（`scripts/eval/`）のレビューで、**測定器として機能しない欠陥**が
2 件見つかった。いずれも実際に再現済み。

**① `--target dev` が全ケース 401 になる。**

`build_analyze_event` が生成する claims は `{"sub", "token_use"}` のみで、`aud` が無い。
`lambda/common/python/whiskey_common/jwt_utils.py:80-92` の `validate_authorizer_claims` は
`claims["aud"] == COGNITO_CLIENT_ID` を要求するため、`extract_user_id_from_event` が `None` を返し、
analyze は `401 Authentication required` を返す。

実測: `extract_user_id_from_event(build_analyze_event(...))` → `None`

結果、画像を 20 枚アップロード・削除し、Lambda を 20 回叩いた上で、全指標が「該当なし」になる。
（`_reserve_analysis_budget` の手前で落ちるのでカウンタは消費しない＝課金事故ではないが、機能しない）

`tests/lambda/test_drink_log_analyze.py` の `_event` は `"aud": "client-123"` を含んでいる。

**② 指標のバケツが分割（partition）になっておらず、抜け穴がある。**

「確定」は `candidates[0]` で判定しているが（`score_evaluation:180-188`）、
`rejected` は「どの候補にも `whiskey_id` が無い」で定義されている（同 189 行）。
そのため**先頭候補が未照合で 2 番目が照合済みのレスポンスは、誤確定にも棄却にも計上されず消える。**

実測: 先頭未照合 + 2番目照合済み → `false_confirmation_rate: 0.0` / `rejection_rate: 0.0`

`lambda/drink-log-analyze/index.py:715-729` の `_resolve_candidates` はモデルの候補順を保つため、
これは正常に起こりうる。**「常にゴミ候補を 1 つ先頭に出す」システムが誤確定 0%・棄却 0% の満点を取れる。**

## 対象リポジトリ

`/home/ttakahashi/workspace/whiskey`（ブランチ `fix/brand-detection-canonical-name`）

## スコープ

**`scripts/eval/` と `tests/eval/` と `.gitignore` のみ。**
`lambda/` `infra/` `frontend/` および依存マニフェストは**一切触らないこと**。

## 実装内容

### 1. 認証クレームの修正（最優先・これが直らないと何も測れない）

`build_analyze_event` が `validate_authorizer_claims` に受理される claims を生成すること:
`sub`（評価用ユーザー）/ `token_use: "id"` / **`aud`（analyze Lambda の `COGNITO_CLIENT_ID`）**。

**`aud` の値をハードコードしないこと。** 実行時に解決する:

```python
lambda_client.get_function_configuration(
    FunctionName="drink-log-analyze-dev"
)["Environment"]["Variables"]["COGNITO_CLIENT_ID"]
```

（`infra/lib/whiskey-infra-stack.ts:500` で設定されている。Cognito のクライアント ID は
公開識別子でありシークレットではない。）

- `--aud` CLI オプションで上書きできるようにする
- 解決できない場合は**明確なエラーメッセージで即座に中断**する（黙って 401 を量産しない）

### 2. 系統的失敗での fail-fast

現在 `execute_evaluation` は 429/503 でしか中断しない。①のような系統的失敗があると
20 ケース全てを走らせてしまう。

- **429/503 以外の非 200（特に 401/403/400）が出たら、チェックポイントを保存して即座に中断**する
- 中断メッセージにステータスコードとレスポンス本文を含める

### 3. 指標を真の分割にする

`candidates[0]` を基準とした**三分割**を各分母に対して出す:

- `confirmed_correct` — 確定し、かつ正しい
- `confirmed_wrong` — 確定したが誤り（＝現行の false confirmation）
- `not_confirmed` — 確定しなかった（`not confirmed`。**`rejected` ではなく**これを使う）

そして:

- **`correct_abstention` は `rejected` ではなく `not_confirmed` を基準にする**
- `rejected`（どの候補にも `whiskey_id` が無い）は**別立ての診断列**として残す
- `candidates` が空 / 欠落のケースを **`no_candidates` として別カウント**する
  （`lambda/drink-log-analyze/index.py:862-868` のモデル失敗時の縮退と、
  「候補はあるが照合できなかった」を混同しないため。Bedrock が完全に壊れている状態が
  「棄却率 100% で優秀」に見えるのを防ぐ）
- **取りこぼし率（miss rate）を retrievable ケースに対して**、
  **`correct_abstention_rate` を unanswerable ケースに対して**、それぞれ別に出す
  （現在の `rejection_rate` は「正しい棄却」と「取りこぼし」を足し合わせており、
  上がったのが良いことか悪いことか読めない）

**以下は既存の正しい挙動なので維持すること:**

- top-1 / top-3 の分母は `expected_whiskey_id` が非 null のケースに限る
- 誤確定の分母は全スコア対象ケース
- 分母 0 のときは 0% ではなく `該当なし` と表示する（overall / by_condition の両方）

### 4. 画像の事前検証

`--dry-run` と、課金が発生するループの直前の**両方**で検証する:

- ファイルが存在し、空でないこと
- **3,670,016 バイト以下**であること（analyze の `UPLOAD_MAX_BYTES`、
  `infra/lib/whiskey-infra-stack.ts:569`。**スマホ写真は普通にこれを超える**）
- jpeg / png / webp としてマジックバイトが妥当であること

問題のあるケースを**まとめて全部報告**して非ゼロ終了する（1 件ずつ課金して 400 を食わない）。

現状 `--dry-run scripts/eval/manifest.example.json` は、**参照画像が 1 枚も存在しないのに exit 0** になる。

### 5. コスト上限の正しい提示

`MIN_COUNTER_INCREMENTS_PER_CASE = 3` は下限としては正しいが、モデルのリトライが 1 回あるため
**上限は 1 ケースあたり 5**（user 日次 1 + モデル試行ごとに global 2 × 最大 2 回）。
既定 20 ケースなら **global 日次 50 枠のうち最大 40 を消費**しうる。

- 確認メッセージに**下限と上限の両方**を明示する
- 予測消費が `ANALYZE_GLOBAL_DAILY_LIMIT`（50）の半分を超える場合は警告する
- 可能なら `AppState-dev` の `drinklog-counter#analyze#global#{YYYY-MM-DD}` を
  読み取り専用で `GetItem` し、**残り枠**を表示する

### 6. 堅牢化（軽微）

- 確認プロンプトの `input()` が `EOFError` を投げる（非対話 stdin）のを捕捉し、
  トレースバックではなく「中断しました」で終える
- `execute_case` の `finally` で `CleanupError` が元の例外を握り潰す（`:622-628`）。
  元の例外を chain するか両方記録する
- `_format_table` が空 `rows` で `TypeError` になるのを防ぐ
- `load_resume_results` が `case` を欠くレコードで `KeyError` を投げるのを `ResultFileError` にする
- `manifest.schema.json:37` が大文字拡張子を弾く一方 Python 側は小文字化している乖離を解消。
  「`expected_whiskey_id` が非 null なら canonical name 必須」（`run_brand_eval.py:135-138`）も
  スキーマに反映する
- `.gitignore` に `scripts/eval/synthetic/` と `brand-eval-results-*.json` を追加する

## テスト（すべて AWS を呼ばないこと。スタブのみ）

1. **`build_analyze_event` が実際の認証を通ること（必須）。**
   `tests/lambda_module_loader` で `whiskey_common.jwt_utils` を読み込み、
   `COGNITO_CLIENT_ID` を monkeypatch した上で
   `extract_user_id_from_event(build_analyze_event(...)) == eval_user` を assert する。
   **①がすり抜けたのは、このテストが無かったからである。**
2. 生成される `s3_key` が analyze の `UPDATE`… ではなく `UPLOAD_KEY_RE`
   （`lambda/drink-log-analyze/index.py:50`）にマッチすること
3. 401 で fail-fast し、チェックポイントが保存されること
4. 新しい分割指標:
   - **先頭が未照合で 2 番目が照合済み**のケースが `not_confirmed` に計上されること
     （現状はどこにも計上されない）
   - `candidates: []` が `no_candidates` として別カウントされること
   - 三分割の合計が各分母と一致すること
5. `--resume` の往復（ダイジェスト不一致で拒否、成功ケースをスキップ、失敗ケースは再試行）
6. `CleanupError` が `interrupted` を立てること
7. `create_dev_clients` が `AWS_ENDPOINT_URL*` と `--profile` 欠落を拒否すること
   （既存テストは環境変数に影響されるので、明示的に monkeypatch すること）
8. `invoke_analyze` の `FunctionError` 分岐
9. `make_synthetic_labels._label_parts` の年数・ブランド抽出

## 検証コマンド（必ず全て実行して結果を報告すること）

```bash
cd /home/ttakahashi/workspace/whiskey
python -m pytest tests -q
python scripts/eval/run_brand_eval.py --dry-run scripts/eval/manifest.example.json
```

**`--dry-run` は今後、画像が存在しないため明確に失敗するはずである。**
`manifest.example.json` を合成画像セットを指すようにするか、プレースホルダ画像を同梱するか、
どちらを選んだかを報告すること。

## 禁止事項

- `lambda/` `infra/` `frontend/` の変更
- 依存パッケージの追加
- テストから AWS を呼ぶこと
- **`--target dev` の実行**（実課金とカウンタ消費が発生する）
- `aud` / Cognito クライアント ID のハードコード
- 既存の正しい挙動（分母の分離、`該当なし` 表示）を壊すこと
- コミット・プッシュ・マージ

## 完了条件

- `python -m pytest tests -q` が全て通る
- `build_analyze_event` が実際の `extract_user_id_from_event` を通るテストが存在し、通る
- 「先頭未照合 + 2番目照合済み」が指標の穴に落ちないテストが存在し、通る
- `--dry-run` が存在しない画像・サイズ超過を検出して非ゼロ終了する
- `git diff` / 新規ファイルが `scripts/eval/` `tests/eval/` `.gitignore` に収まっている
