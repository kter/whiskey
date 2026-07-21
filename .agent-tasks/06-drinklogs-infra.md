# Task 06: 飲酒ログ機能インフラ + 最小ハンドラスタブ

Phase 4 の土台。**インフラ定義 + 全 Function の実在ハンドラファイル（501スタブ）** をこのタスクで作る。実装本体はタスク07/08が置き換える。`Code.fromAsset` は実在ディレクトリ必須のため、スタブが無いと synth も通らない。

前提: Phase 4 着手前チェック完了済み（`docs/COST_MATRIX.md`）。確定モデル・配送先ARN・上限値は同ファイルが正。**このタスクはそのマトリクスの数値を環境変数・IAM に落とすのが役目。マトリクスと矛盾する値を入れない**こと。

## 既存資産（変更・参照のベース）

- `infra/lib/whiskey-infra-stack.ts`: `imagesBucket`(L81, CORS済/tmp・logs 未分離)、`placesSecret`(L614, `whiskey-places-${env}` を fromSecretNameV2 済)、`appStateTable`(L168, PK `pk`/TTL `ttl`)、`appStatePrefixStatement(actions, prefixes)` ヘルパー(L298)、`bundledPythonCode(dir)`(L334)、`commonLayer`(L359)、`createLambdaRole(id,name,logGroup)`(L275)、ranking の Scheduler パターン（`CfnScheduleGroup`+target role+DLQ+`CfnSchedule` L457-499）、API の `authenticated`/`publicMethod`/`integration()`/methodOptions throttling(L514-599)。**これらを新設せず再利用する**。
- `lambda/common/python/whiskey_common/`: logger, responses, jwt_utils, normalize, clients。画像正規化 `images.py` は**タスク08で新設**（このタスクでは触らない）。

## 1. 新規 Lambda アセット（スタブ + requirements）

**`lambda/drink-logs/`**:
- `index.py`: `def lambda_handler(event, context)` — 全ルート（upload-url/create/timeline GET/detail/update/delete）に対し `501 Not Implemented` を共通レスポンスヘルパー経由で返すスタブ。
- `reconciler.py`: `def lambda_handler(event, context)` — 501 ではなく**何もせず `{"status":"noop"}` を返す**スタブ（Scheduler が起動しても失敗しないよう）。ハンドラ名は `reconciler.lambda_handler`。
- `requirements.txt`: `boto3`/`botocore`（レイヤーと同一固定版）+ **`Pillow`（固定版、例 `Pillow==11.0.0` — タスク07の画像サニタイズで使用。ここで同梱しないと後続 synth で ImportError）**。

**`lambda/drink-log-analyze/`**:
- `index.py`: analyze の 501 スタブ（`index.lambda_handler`）。
- `places.py`: places の 501 スタブ（`places.lambda_handler`）。
- `requirements.txt`: `boto3`/`botocore` + `Pillow`（同一固定版）+ `requests`（固定版、Places HTTP 用）。

**受入**: `bundledPythonCode` は install + `cp -au . /asset-output` で全 `.py` を同梱するため、**バンドル成果物（test 用 local bundling）に各 Function の handler ファイルが存在するテスト**を追加（`index.py`/`reconciler.py`/`places.py`）。欠落したまま deploy すると Runtime.ImportModuleError。

## 2. DynamoDB: DrinkLogs テーブル

```
DrinkLogs-${env}: PK id(S), PAY_PER_REQUEST, removalPolicy=retainResources準拠
GSI UserDatetimeIndex: PK user_id(S), SK datetime(S)  // datetime は RFC3339 UTC 正規化文字列
```
- **TTL は定義しない**（pending/deleting の掃除はリコンサイラ専管。TTL は回復情報を先に消す）。
- アイテム形状（`API_REFERENCE.md` / `swagger.yml` にも記載）: `id, user_id, status(pending|complete|deleting), datetime(RFC3339 UTC), s3_image_key, tmp_s3_key?, quota_allocated(bool), whiskey_id?, brand_text, brand_source(ai|manual|matched), serving_style, store{name(ユーザー入力・空可), place_id?}, notes?, rating?, ai{model_id,confidence}?, created_at, updated_at`。
- **GPS 座標（lat/lng）は保存しない**。Google 表示名も保存しない（D13）。日次/割当カウンタは AppState-${env}（DrinkLogs ではない）。

## 3. imagesBucket の拡張（既存バケットに追加）

- **tmp/ プレフィックスに2日ライフサイクル**: `lifecycleRules: [{ prefix: 'tmp/', expiration: Duration.days(2) }]`（生EXIF入り未サニタイズ画像の保持最小化）。logs/ はライフサイクルなし。
- **MetricsConfiguration 2件**（`metrics` プロパティ、FilterId 付き）: ① `tmp/`（PostRequests + BytesUploaded 観測用、prefix `tmp/`）② `logs/`（GetRequests + BytesDownloaded、prefix `logs/`）。リクエストメトリクスはオプトイン有償・ベストエフォートである旨コメント。
- **`versioned: false` を維持**（CDK テストで固定 — presigned POST 再送が「同一キー上書きのみ」で済む前提）。CORS は既存のまま（POST 含む）。

## 4. 新規 Lambda 関数（4つ・値は COST_MATRIX 準拠）

共通: runtime PYTHON_3_11 / arch X86_64 / layers=[commonLayer] / 専用 logGroup（`/whiskey/${env}/<fn>` 形式・既存パターン）/ 専用ロール。

| 関数 | handler | timeout | memory | reservedConcurrency | asset |
|------|---------|---------|--------|--------------------|-------|
| `drink-logs-${env}` | `index.lambda_handler` | 25s | 1024 | envConfig 経由（任意） | drink-logs |
| `drink-log-analyze-${env}` | `index.lambda_handler` | 28s | 1024 | 2（`envConfig.lambdaReservedConcurrency?.analyze`） | drink-log-analyze |
| `drink-log-places-${env}` | `places.lambda_handler` | 10s | 256 | 3（`...?.places`） | drink-log-analyze |
| `drink-log-reconciler-${env}` | `reconciler.lambda_handler` | 300s | 512 | 1 | drink-logs |

memory は「CDK assertion で固定 + Phase 4 実測で調整」の初期値（D9）。CDK テストで memory/timeout を assert。

**環境変数（COST_MATRIX の確定値）**:
- 共通: `ENVIRONMENT`, `APP_STATE_TABLE`, `DRINKLOGS_TABLE`, `IMAGES_BUCKET`, `ALLOWED_ORIGINS`, `COGNITO_USER_POOL_ID`/`COGNITO_CLIENT_ID`（claims 再検証用、認証系関数）。
- drink-logs: `WHISKEY_SEARCH_TABLE`, `UPLOAD_USER_DAILY_LIMIT=30`/`UPLOAD_GLOBAL_DAILY_LIMIT=100`, `CREATE_USER_DAILY_LIMIT=30`/`CREATE_GLOBAL_DAILY_LIMIT=100`, `STORAGE_USER_LIMIT=2000`/`STORAGE_GLOBAL_LIMIT=20000`, `IMAGE_MAX_BYTES=1572864`(1.5MB), `UPLOAD_MAX_BYTES=3670016`(3.5MB)。
- analyze: `WHISKEY_SEARCH_TABLE`, `BEDROCK_MODEL_ID=jp.amazon.nova-2-lite-v1:0`（既定）, `BEDROCK_MODEL_ALLOWLIST=jp.amazon.nova-2-lite-v1:0,jp.anthropic.claude-haiku-4-5-20251001-v1:0`, `ANALYZE_USER_DAILY_LIMIT=20`/`ANALYZE_GLOBAL_DAILY_LIMIT=50`/`ANALYZE_GLOBAL_MONTHLY_LIMIT=1000`, `IMAGE_MAX_BYTES=1572864`, `UPLOAD_MAX_BYTES=3670016`。
- places: `PLACES_USER_DAILY_LIMIT=30`/`PLACES_GLOBAL_DAILY_LIMIT=15`/`PLACES_GLOBAL_MONTHLY_LIMIT=150`, `PLACES_SECRET_NAME=whiskey-places-${env}`。
- reconciler: `DRINKLOGS_TABLE`, `IMAGES_BUCKET`, `APP_STATE_TABLE`, `RECONCILE_AGE_HOURS=48`。

## 5. Bedrock IAM（型付き・両候補 profile 型）

`docs/COST_MATRIX.md` 確定分。両候補とも `type: profile`。analyze ロールに**2ステートメント**を付与:
1. プロファイルARN への `bedrock:InvokeModel`:
   - `arn:aws:bedrock:${region}:${account}:inference-profile/jp.amazon.nova-2-lite-v1:0`
   - `arn:aws:bedrock:${region}:${account}:inference-profile/jp.anthropic.claude-haiku-4-5-20251001-v1:0`
2. 配送先 foundation-model ARN への `bedrock:InvokeModel`（`bedrock:InferenceProfileArn` 条件で上記プロファイルに限定）:
   - `arn:aws:bedrock:ap-northeast-1::foundation-model/amazon.nova-2-lite-v1:0`
   - `arn:aws:bedrock:ap-northeast-3::foundation-model/amazon.nova-2-lite-v1:0`
   - `arn:aws:bedrock:ap-northeast-1::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0`
   - `arn:aws:bedrock:ap-northeast-3::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0`

型を配列データ（`{type:'profile', profileArn, destinationArns[]}`）で持ち、direct 型（素モデルARN直接）も生成できる分岐を実装（現状候補は両方 profile だが将来 in-region 直接候補に備える。両型の jest テスト付き）。`GetInferenceProfile` は**ランタイムに付与しない**（デプロイ担当の列挙用のみ）。**起動時 allowlist 照合はランタイム側（タスク08）**、IAM はここ。

## 6. IAM ロール権限マトリクス（AppState は「アクション×LeadingKeys プレフィックス」で相互隔離）

新規 AppState プレフィックス定数を追加（既存の `SCAN_COUNTER_PREFIX` 等に倣う）:
- `DRINKLOG_COUNTER_PREFIX = 'drinklog-counter#*'`（日次 upload/create/analyze/places カウンタ、月次含む）
- `DRINKLOG_QUOTA_PREFIX = 'drinklog-quota#*'`（生涯=現在割当数カウンタ）
- `AI_RESULT_PREFIX = 'ai-result:*'`（解析結果短期キャッシュ）

| 関数 | DynamoDB | S3 | AppState | その他 |
|------|----------|----|----|--------|
| drink-logs | DrinkLogs RW、WhiskeySearch 読取 | tmp/* と logs/* の Get+Put+Delete（copy はコピー元 Get+先 Put 必須） | `DRINKLOG_COUNTER`(UpdateItem)、`DRINKLOG_QUOTA`(UpdateItem)、`AI_RESULT`(GetItem+条件付き UpdateItem/DeleteItem = create が結果を消費) | — |
| analyze | WhiskeySearch 読取 | tmp/* 読取 | `DRINKLOG_COUNTER`(UpdateItem/GetItem)、`AI_RESULT`(UpdateItem = 解析結果保存) | Bedrock（§5） |
| places | DrinkLogs BatchGet（resolve 所有確認） | — | `DRINKLOG_COUNTER`(places カウンタ UpdateItem/GetItem) | Places シークレット読取（**この関数のみ**） |
| reconciler | DrinkLogs RW | logs/* **と** tmp/* の ListBucket(prefix 条件)+Get+Delete | `DRINKLOG_QUOTA`(UpdateItem = 返金トランザクション) | — |

**negative/positive IAM テスト必須**: ① places シークレットは analyze ロールに**付かない** ② analyze は Bedrock 両型でどちらの候補も invoke 可、allowlist 外モデルARNは拒否 ③ drink-logs と analyze の `AI_RESULT` 相互権限 ④ reconciler の ListBucket が logs/ と tmp/ 両 prefix で許可 ⑤ 各関数が他用途キープレフィックスへの操作を拒否。ranking/reviews 等**既存ロールの権限は変更しない**（タスク01/03で確定済み）。

## 7. リコンサイラ Scheduler（日次）

ranking の Scheduler パターンを複製:
- `CfnScheduleGroup`（`drink-log-reconciler-${env}`）+ target role（`scheduler.amazonaws.com` assume、`aws:SourceArn`=**schedule-group ARN**、`aws:SourceAccount`=account）+ `lambda:InvokeFunction`(reconciler) + `sqs:SendMessage`(DLQ) + DLQ(SQS_MANAGED, 14日) + `CfnSchedule`（`rate(1 day)` or `cron(...)`、flexibleTimeWindow OFF、retry 3/3600s、DLQ 設定）。
- 合成テンプレートで target role が InvokeFunction + DLQ SendMessage を持つことを検証。

## 8. API ルート（/api/drink-logs/*）

既存 `apiResource`(=`/api`) に `drink-logs` リソースを追加。全ルートに `authenticated`（Cognito authorizer）+ methodOptions throttling を装着:
- `POST /api/drink-logs/upload-url` → drink-logs
- `POST /api/drink-logs/analyze` → analyze
- `POST /api/drink-logs/places` → places（**GET でなく POST** — GPS を body で受け URL ログ永続化を防ぐ）
- `POST /api/drink-logs/places/resolve` → places（タスク08実装、ルート/オーソライザー/スロットリング/ローカルアダプタ配線はここ）
- `POST /api/drink-logs` / `GET /api/drink-logs`（limit,next_token,brand,store,place_id）→ drink-logs
- `GET|PUT|DELETE /api/drink-logs/{id}` → drink-logs

throttling（methodOptions、保守的）: upload-url/analyze/places 系は `throttlingRateLimit: 2, burst: 5` 目安、GET は `5/10`。**REST のスロットルはベストエフォート・保証上限でない**旨コメント（保証はカウンタ）。

## 9. WhiskeyObservability-${env} スタック（独立・新設）

**アプリスタックに置かない**（最終形のクリーン再デプロイで「通知→アプリ→Observability」の順序を保つ）。新規 `infra/lib/observability-stack.ts`:
- 東京通知トピック ARN（`WhiskeyNotifications-Tokyo` の SSM/Export 参照）+ アプリスタックの imagesBucket 名/リコンサイラ関数名を props で受ける。
- CloudWatch アラーム: ① S3 tmp PostRequests / logs GetRequests の異常増（FilterId メトリクス、missing-data=notBreaching）② reconciler Errors ≥1。全て東京トピックへ通知（通知であり遮断でない旨）。
- `bin/infra.ts` に Observability スタックを追加（app + tokyo notifications に依存、`crossRegionReferences: true` 明示）。**Phase 4 でのみデプロイ**。
- `deploy.sh` / `package.json` に **`--observability` 対象**を追加（通知→アプリ→Observability の依存順・STS アカウント検証・単独 diff/deploy）。対象指定に載せ忘れるとガード経路からデプロイ不能になるため受入条件に含める。

## テスト（jest, `cd infra && npx tsc --noEmit && npx jest && npx cdk synth -c env=dev`）

- DrinkLogs テーブル + UserDatetimeIndex、TTL 無し
- imagesBucket: tmp/ 2日ライフサイクル、MetricsConfiguration 2 FilterId、versioned:false
- 4 関数の memory/timeout/reservedConcurrency/handler/logGroup
- Bedrock IAM 両型（profile/direct）、allowlist ARN 一致、GetInferenceProfile 不付与
- AppState プレフィックス隔離（§6 の negative/positive）
- リコンサイラ Scheduler target role（InvokeFunction + DLQ SendMessage、SourceArn=group）
- API ルート6種の authorizer 装着 + throttling
- Observability スタックに AWS::Route53::HostedZone 等が無い / 依存順
- バンドル成果物に index.py/reconciler.py/places.py が存在
- 全 dev フラグ組合せ + prd（フラグなし）で lookup なし synth 成功

## してはならないこと

- ハンドラ本体ロジックの実装（07/08 の担当。ここは 501/noop スタブのみ）。
- `lambda/common/images.py` の新設（タスク08）。
- reviews/ranking/list/search の既存ロール・テーブル・ルートの変更。
- 実 AWS アクセス、コミット作成、`docs/COST_MATRIX.md` の数値変更（矛盾させない）。
- Places/Bedrock シークレットや API キーをコード・テストにハードコード。
