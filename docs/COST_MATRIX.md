# Phase 4 コスト上限マトリクス（フォトログ機能）

Phase 4 着手前チェックポイント③の確定成果物。タスク06（インフラ・環境変数）/ タスク07（作成カウンタ）/ タスク08（analyze・places カウンタ）/ タスク01の Budgets が参照する。数値は dev アカウント（031921999648, ap-northeast-1）実測・実クエリに基づく。

## 確定モデル（チェックポイント②）

| 用途 | モデル | 推論プロファイル | 配送先（IAM） | 実測レイテンシ |
|------|--------|-----------------|--------------|---------------|
| 既定（最安） | Amazon Nova 2 Lite | `jp.amazon.nova-2-lite-v1:0` | `ap-northeast-1` / `ap-northeast-3` の `amazon.nova-2-lite-v1:0` | 0.89s |
| 精度フォールバック | Claude Haiku 4.5 | `jp.anthropic.claude-haiku-4-5-20251001-v1:0` | `ap-northeast-1` / `ap-northeast-3` の `anthropic.claude-haiku-4-5-20251001-v1:0` | 1.87s |

- 両プロファイルとも配送先は**日本国内リージョンのみ**（東京・大阪）。データ所在地要件を満たす。`global.*` プロファイルは不採用。
- 両モデルとも `type: profile`。IAM は profileARN への `InvokeModel` + 配送先 foundation-model ARN 2件（`bedrock:InferenceProfileArn` 条件付き）の別ステートメント。
- `BEDROCK_MODEL_ID` は上記2つの allowlist と起動時照合。セット外は起動エラー。
- **実装知見**: 両モデルとも JSON 応答を ` ```json … ``` ` フェンスで包む → パーサーはフェンス除去を必須にする。
- Bedrock モデル呼び出しログ設定は**無効**（`loggingConfig=null`、2026-07-21 実確認）。検証呼び出し画像の残存経路なし。

## 実クエリ価格（AWS Pricing API, ap-northeast-1）

| 項目 | 単価 |
|------|------|
| Nova 2 Lite 入力トークン | $0.000396 / 1K = **$0.396 / 1M** |
| Nova 2 Lite 出力トークン | $0.003311 / 1K = **$3.311 / 1M** |
| S3 Standard ストレージ | **$0.025 / GB-月** |

※ Claude Haiku 4.5 のトークン単価は当リージョンの Pricing API データセットに未掲載。フォールバック専用のため概算幅（Nova比 約2倍）で扱い、最悪ケースは Nova で確定・Haiku は上振れ注記とする。

## 1回あたり原価（Nova 2 Lite・保守的見積り）

analyze 1回: サニタイズ後画像（長辺≤1600px, JPEG）≈ 画像1,500 + プロンプト250 = 入力 ~1,750 tokens / 出力 maxTokens 512。
- 入力: 1,750 × $0.396/1M = $0.00069
- 出力: 512 × $3.311/1M = $0.00170
- **≈ $0.0024 / 呼び出し**（Nova）。Haiku 概算 ≈ $0.0044 / 呼び出し。

## 日次・月次上限マトリクス（確定：月次予算 $15 から逆算）

**グローバルカウンタは Bedrock 呼び出し試行ごとに1消費**（malformed-JSON リトライ含む → 最悪 request 上限の2倍が invoke 回数）。ユーザーカウンタはリクエスト単位。環境変数名は各 Lambda に注入（タスク06）。

| 操作 | ユーザー日次 | グローバル日次 | グローバル月次 | 最悪月額（確定経路） |
|------|-------------|---------------|---------------|---------------------|
| upload-url (`UPLOAD_*`) | 30 | 100 | — | S3 PUT 従量（上界なし・低単価・アラーム監視） |
| create (`CREATE_*`) | 30 | 100 | — | ストレージに算入 |
| analyze (`ANALYZE_*`) | 20 | **50** | 1,000 | Nova: 50×2×$0.0024×30 ≈ **$7.2/月**（Haiku 上振れ ≈ $13/月※） |
| places (`PLACES_*`) | 30 | 15 | **150**（拘束的） | Nearby Pro 最悪: 150×$0.032 ≈ **$4.8/月** |

環境変数（例）: `ANALYZE_USER_DAILY_LIMIT=20` / `ANALYZE_GLOBAL_DAILY_LIMIT=50` / `ANALYZE_GLOBAL_MONTHLY_LIMIT=1000` / `PLACES_USER_DAILY_LIMIT=30` / `PLACES_GLOBAL_DAILY_LIMIT=15` / `PLACES_GLOBAL_MONTHLY_LIMIT=150` / `UPLOAD_*`・`CREATE_*` は 30/100。

**ストレージ上界（現在割当数モデル）**: ユーザー 2,000件 / グローバル 20,000件 × 最終1.5MB上限 = 最大30GB → **$0.75/月**。tmp/ は2日ライフサイクルで無視可能（~$0.04/月）。

**確定最悪月額（Nova 既定経路）**: analyze $7.2 + places $4.8 + ストレージ $0.75 + S3リクエスト従量（低単価）≈ **$12.8/月**（< $15 ceiling）。

**※ Haiku 注意**: フォールバックを既定昇格する場合、analyze 経路だけで $13/月に達し ceiling を圧迫する → **Haiku を既定にするなら `ANALYZE_GLOBAL_DAILY_LIMIT` を 30 へ下げる**（精度検証中の一時切替は許容、恒常昇格時は上限を絞る）。

## Places（支配的・要ユーザー確定）

Google Places API (New) は日次クォータを持たない → **費用上界はアプリ側 AppState グローバルカウンタが唯一の保証**。
- Nearby Search **Pro** SKU / Place Details（displayName 要求）**Pro** SKU で課金（IDs-only ではない）。
- 単価は post-cutoff で変動し得るため**現行レートをユーザーが Google Cloud コンソールで確認**する前提。過去実績目安: Nearby Pro ≈ $32/1000、Details Pro ≈ $17/1000。
- 例: グローバル日次400・全て Nearby と仮定すると $32/1000 × 400 × 30 ≈ **$384/月** — 上限を丸数字で置くと破綻する。
- **設計方針（プランD13/D14準拠）**: 店名は原則ユーザー手入力を促し、resolve は「表示要求時 かつ ラベル未入力時のみ」。places グローバル日次/月次は**月次予算ceilingから逆算**して確定済み（下表）。
- **確定**: グローバル日次 15 / **グローバル月次 150（拘束的）** — 全て Nearby Pro 最悪でも月 $4.8。実際は手入力促進で resolve 消費はさらに少ない。単価が現行 Google レートと乖離していたら本値を再逆算する。

## Budgets 閾値（確定：月次 $15）

- 月次予算 ceiling = **$15**（ユーザー確定 2026-07-21）。
- SNS 通知（`WhiskeyNotifications`、us-east-1）を **50% = $7.5 / 80% = $12 / 100% = $15** で発報。
- グローバル閾値超過時は該当エンドポイント 503（サーキットブレーカー、D14）。Budgets は通知のみ・遮断はカウンタ側。

## 費用上界の保証範囲（正直な限定）

- **確定上界あり**: Bedrock（カウンタ）・Places（カウンタ）・DrinkLogs 画像ストレージ（現在割当数カウンタ）。
- **上界なし・残余リスク承認**: S3 PUT（presigned POST 窓）/ GET（presigned GET 窓）のリクエスト課金（低単価・CloudWatch アラームは通知であり遮断ではない）。Reviews は日次上限のみ・総件数上限なし。Cognito セルフサインアップ由来のレート（API GW スロットルは認証系に不適用）。
- カウンタ書き込み失敗時は課金呼び出しの**前に** fail-closed（テストで保証）。
