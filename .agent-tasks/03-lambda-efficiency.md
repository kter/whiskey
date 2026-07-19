# Task 03: scan 効率化・ランキング事前集計・蒸留所検索残骸の削除

## Goal

未ページネーション scan の解消、ランキングの「スケジュール実行の事前集計 + キャッシュ配信」化、蒸留所検索の残骸削除、公開 scan 経路への費用防御を実装する。**対象は lambda/whiskeys-search・whiskeys-list・新規集計 Lambda + それらの infra 定義 + テスト。フロントは変更しない**（`next_token` UI 追従はタスク04）。

## 背景（必読）

- タスク01/02適用済み前提: AppState テーブル・`scan_utils.py`（ページネーションヘルパー）・`clients.py`・レイヤーが存在。Reviews に `WhiskeyIndex` は無い。
- **DynamoDB 制約**: `NameIndex` は正規化文字列のみを PK に持つ GSI であり、Query は PK 等価条件必須 — **begins_with 部分一致には使えない**。完全一致ルックアップ専用とする。部分一致検索はページネーション完備 scan が正式方式（データ規模 ~3千件）。

## 変更対象

- `lambda/whiskeys-search/index.py` / `lambda/whiskeys-search/python/whiskey_search_service.py`
- `lambda/whiskeys-list/index.py`
- 新規 `lambda/ranking-aggregator/index.py`（+ requirements.txt）
- `infra/lib/whiskey-infra-stack.ts`（集計 Lambda / Scheduler / IAM）
- `scripts/insert_whiskeys_to_dynamodb.py`（bulk writer 移設）
- `tests/lambda/**`

## 要求仕様

### 1. scan のヘルパー集約
- 直接の `.scan(` 呼び出しを全廃し、レイヤーの `scan_utils`（全ページ走査・1リクエスト最大ページ数上限・next_token エンコード）経由に統一。grep 受入は「ヘルパー外の直接 scan ゼロ」。
- search / list の応答に `next_token` 契約を追加。**走査上限到達時は next_token を返し、無言の切り捨てを禁止**。
- レビューごとの `get_item` ループ → `batch_get_item`（100件チャンク + UnprocessedKeys の有限回リトライ）。

### 2. 公開 scan の費用防御
- search / list に AppState のグローバル日次カウンタ（匿名のためユーザー別なし）。超過時はキャッシュ済み応答 or 429。

### 3. ランキング: 事前集計 + キャッシュ配信
- **`ranking-aggregator-{env}` Lambda 新設**: タイムアウト 120s / 512MB / reserved concurrency 1 / 残時間チェック付き。
- **EventBridge Scheduler（15分毎）**: 明示的 ScheduleGroup + `scheduler.amazonaws.com` が引き受ける専用ターゲットロール（`lambda:InvokeFunction` + DLQ への `sqs:SendMessage`、confused-deputy 条件の `aws:SourceArn` は **schedule-group ARN**）+ リトライ + DLQ（SQS）。合成テンプレートで検証。
- **dirty 判定は2系統**: レビュー変更カウンタ（タスク02で書き込み側実装済み）+ **銘柄リビジョンカウンタ**（`insert_whiskeys_to_dynamodb.py` と後続 seed スクリプトが increment）。未変更ならスキップ、**ただし現行世代キャッシュ欠損時は変更有無に関わらず強制再生成**。手動 invoke 用に `--force` 相当のイベントフラグ。
- **集計読み取りはベーステーブルの強整合ページネーション scan（is_public=true フィルタ）**。`PublicDateIndex` は使わない（GSI 伝播レースを避ける）。**scan の前後でカウンタ値を再確認し、途中で変化していたら clean マークしない**。
- **キャッシュ形式**: AppState に世代ID + ページ分割の複数 item（単一 item の 400KB 上限対策）。メタデータ item のみ条件付き更新で世代を原子切替。**ステージングページには書き込み時から掃除用 TTL を付け、世代有効化時に REMOVE**。旧世代は切替後に TTL 付与で遅延削除 + lease 下で放棄世代を掃除。ロックは期限付き owner lease。
- **fail-closed**: メタデータに世代生成時点のカウンタ値 + カウンタ変更時に `dirty_since` を記録。現行世代が `dirty_since` から45分超で古いままなら「集計中」応答。**公開→非公開遷移は即時無効化マーカーで直ちに fail-closed**（タスク02の reviews 側が非公開化時にマーカーを書く — 必要なら reviews 側に1行追加してよい）。
- **whiskeys-search はキャッシュ読み取り専用**（同期集計コードを削除）。キャッシュ未生成時は「集計中」応答（HTTP 200 + `status: "aggregating"`）。
- IAM: aggregator = Reviews ベーステーブル ARN への `dynamodb:Scan` + WhiskeySearch 読み取り + AppState ランキング prefix 読み書き + 変更カウンタ GetItem。search のランキング prefix は GetItem のみ（負のテスト付き）。

### 4. 蒸留所検索の残骸削除
- `DistilleryIndex` GSI を WhiskeySearch 定義から除外（テーブルは新規作成されるため移行不要）。
- `whiskey_search_service.py` の distillery 検索パス・未使用の破壊的メソッド（作成・一括書き込み・全件削除）を削除。
- **`insert_whiskeys_to_dynamodb.py` は削除対象の `bulk_insert_whiskeys` に依存** — batch writer をスクリプト側ヘルパー（`scripts/` 内）へ移設してから削除。スクリプトには `--target local|dev` 必須引数 + STS アカウント検証（dev=031921999648）+ 銘柄リビジョンカウンタ increment を追加。
- 検索 Lambda から DynamoDB 書き込み呼び出しが消えたことを grep で確認（カウンタ書き込みは AppState のみ許可）。

## 受入条件

1. `python -m pytest tests/` 全緑（ページネーション・batch_get・集計世代切替・fail-closed・並行 lease のテストを含む）
2. `cd infra && npx jest && npx cdk synth -c env=dev > /dev/null` 成功（Scheduler/ロール/DLQ の assert 含む）
3. grep: ヘルパー外の直接 `.scan(` ゼロ / distillery 検索パス残存ゼロ
4. フロントエンド未変更

## してはならないこと

- フロントエンド変更・実 AWS アクセス・コミット作成
- reviews のロジック変更（非公開化マーカーの1行を除く）
