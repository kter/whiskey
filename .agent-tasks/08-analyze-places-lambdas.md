# Task 08: AI解析 Lambda + Places Lambda（2ハンドラ）

タスク06の analyze/places 501スタブを実装で置換。対象: `lambda/drink-log-analyze/index.py`（Bedrock解析、`index.lambda_handler`）、`lambda/drink-log-analyze/places.py`（`drink-log-places-{env}` のハンドラ `places.lambda_handler` — `/places` と `/places/resolve` を排他所有）、テスト。**インフラ・IAM・ルート・envはタスク06確定・変更しない**。画像正規化は**タスク07で新設済みの `whiskey_common/images.py` を import**（重複実装禁止）。

正典: `docs/COST_MATRIX.md`（上限・モデル）、タスク06 env、タスク07が消費する `ai-result` スキーマ（下記§。**この形で保存しないと create が消費できない**）。

## analyze `index.py`（`POST /api/drink-logs/analyze`）

body: `{s3_key}`（**座標は受け取らない** — 精密位置は places 専管）。処理順:
1. **認証再検証**: claims `aud==COGNITO_CLIENT_ID` かつ `token_use=='id'`（reviews/drink-logs と同方針、jwt_utils 使用）。
2. **所有権**: `s3_key` が `tmp/{caller_uid}/` 始まり（不一致 403）。
3. **サイズ+形式**: `head_object` で ContentLength ≤ `UPLOAD_MAX_BYTES`(3.5MB)、ETag 取得。**マジックバイト検証**: `get_object(Range="bytes=0-15")` のバイトを `whiskey_common.images.sniff_format` に渡し jpeg/png/webp 以外は 400。
4. **正規化**: `get_object(IfMatch=etag)` で全体取得（解析後に差し替えられたバイトを扱わない来歴保証）→ `whiskey_common.images.normalize_image(raw, max_bytes=IMAGE_MAX_BYTES)`（exif_transpose・画素/1辺上限・RGB・メタ無しJPEG・最終≤1.5MB）。**生バイトを Bedrock に渡さない**（GPS入りEXIF送信・Converse上限超過の防止）。
5. **カウンタ + サーキットブレーカー**（全て AppState、fail-closed = カウンタ書込失敗時は Bedrock を呼ばない）:
   - 日次解析上限（user/global、`drinklog-counter#analyze#user#{uid}#{date}` / `#global#{date}`、TTL 2日、超過429）。
   - **月次グローバル上限**（`drinklog-counter#analyze#global-month#{YYYY-MM}`、TTL ~35日、`ANALYZE_GLOBAL_MONTHLY_LIMIT=1000` 超過は503サーキットブレーカー）。
   - **グローバルカウンタは Bedrock 呼び出し試行ごとに1消費**（malformed-JSON リトライ含む）。ユーザーカウンタはリクエスト単位。
6. **モデル allowlist 照合**: 起動時に `BEDROCK_MODEL_ID` ∈ `BEDROCK_MODEL_ALLOWLIST`（カンマ区切り）でなければ**起動エラー**（import 時 or ハンドラ先頭）。
7. **Bedrock Converse**: 画像ブロック（format=jpeg）+ 厳格JSONプロンプト。
   - **時間予算**: `context.get_remaining_time_in_millis()` から動的算出。起動〜呼び出しオーバーヘッド込みで **~20秒以内**に応答。Bedrock クライアントは**共有ファクトリの固定値でなくリクエスト単位で生成**し read timeout を残時間から設定、残時間不足なら invoke せず degrade。**`total_max_attempts=1`**（SDK自動リトライ無効）。**`inferenceConfig.maxTokens=512`**（未指定の大デフォルトはクォータ予約とタイムアウトを毀損）。
   - **重要（pre-check知見）**: Nova/Haiku とも JSON応答を ` ```json … ``` ` フェンスで包む → **`json.loads` 前にコードフェンスを除去**するヘルパーを実装（先頭/末尾の ```/```json を剥がす）。テストベクタにフェンス付き/無し両方。
8. **出力スキーマ検証**: `{brand_candidates:[{name_ja,name_en,confidence}], serving_style, glass_type}` を検証（候補数上限 例5・各文字列長≤200・`serving_style`∈{NEAT/ROCKS/WATER/SODA/COCKTAIL}（AI の highball/soda は SODA へマップ）・confidence 0〜1）。不正/欠落は**空候補に degrade**（Lambda残時間に余裕がある場合のみ1回リトライ=解析カウント消費）。
9. **WhiskeySearch 照合**: `whiskey_common.normalize` で正規化し `NameIndex` 完全一致 → 無ければ部分一致 scan（ページ上限付き）で `whiskey_id` 付与。
10. **ai-result 保存 + 応答**（§スキーマ）。応答は `{analysis_id, candidates:[…], serving_style, model_id, confidence}`（**画像バイトや生EXIFは返さない**）。

### ai-result スキーマ（タスク07消費契約・厳守）

AppState item を key `ai-result:{caller_uid}:{upload_uuid}`（`upload_uuid` は `s3_key` から抽出）で put:
```
pk:          "ai-result:{uid}:{uuid}"
user:        "{uid}"                      # 属性名は user（sub ではない）
s3_key:      "tmp/{uid}/{uuid}.{ext}"     # 解析した tmp キー
ETag:        "\"<head_object の ETag そのまま・引用符込み>\""   # create が head_object で厳密一致比較
candidates:  [ { "brand_text": "<表示名≤200>", "name_ja": "", "name_en": "",
                 "confidence": <Decimal 0..1>?, "whiskey_id": "<matched>"? }, … ]
serving_style: "NEAT|ROCKS|WATER|SODA|COCKTAIL"   # トップレベル
model_id:    "{BEDROCK_MODEL_ID}"
confidence:  <Decimal>?                    # トップレベル任意（候補側 confidence 優先）
whiskey_id:  "<matched>"?                  # トップレベル任意（候補側優先）
expires_at:  <epoch int, 例 now+30分>      # create が expires_at > now を検証
ttl:         <expires_at と同値>            # AppState TTL 属性
analysis_id: 応答では "ai-result:{uid}:{uuid}"（create はこの形 or 素の uuid を受理、ANALYSIS_ID_RE 準拠）
```
注意: create は `candidates[index]` を**オブジェクト等価**で条件照合する（自己整合なので追加制約なし）。**Decimal で保存**（DynamoDB は float 不可）。`brand_text`/`name`/`label` のいずれかが表示名として読まれる（`_candidate_brand`）。`whiskey_id` は空文字禁止（None か非空文字列）。

## places `places.py`

**MOCK ガード**: `MOCK_AI`/`MOCK_PLACES` は `ENVIRONMENT==local` のときのみ有効、dev/prd で設定されていたら起動時例外。MOCK_PLACES は決定的モック候補を返しフロー完走可能に。

### `POST /api/drink-logs/places` {lat,lng}
- **入力検証**: lat∈[-90,90]、lng∈[-180,180]、有限値のみ、非数/範囲外400。
- **Places API (New) searchNearby**（D13厳密仕様）: `POST https://places.googleapis.com/v1/places:searchNearby`、body `{includedTypes:["bar","restaurant"], rankPreference:"DISTANCE", maxResultCount:8, languageCode:"ja", regionCode:"JP", locationRestriction:{circle:{center:{latitude,longitude},radius:300}}}`、ヘッダー `X-Goog-Api-Key`（必須）+ `X-Goog-FieldMask: places.id,places.displayName,places.formattedAddress,places.attributions`（**`places.location` は要求しない**）。
- **HTTP**: connect 2s / read 5s、**暗黙リトライなし**。タイムアウト/不正応答/期限超過テスト。
- **日次+月次 places 上限**（AppState、`drinklog-counter#places#…`、超過429）。
- **APIキー**: `PLACES_SECRET_NAME` の Secrets Manager から取得（`{"apiKey":"…"}` 厳密スキーマ、起動時検証、欠落/不正はエラー）。**モジュールグローバルにキャッシュ可**（シークレット値でありPlacesコンテンツではない）、**クライアントに絶対返さない**。
- **displayName のリクエスト横断キャッシュ禁止**（Placesポリシー）。応答は候補 `[{place_id, display_name, formatted_address, attributions}]`（エフェメラル、保存しない）。`attributions` は必ず伝搬。
- **ロガーの redact**: lat/lng・座標含みフィールド + `store`/`brand` フィルタ値をパラメータ名のみ記録（レイヤー logger に redact フィルタ追加、保持方針をドキュメント化）。

### `POST /api/drink-logs/places/resolve` {items:[{log_id,place_id}]}（最大10、超過400）
- **所有権**: DrinkLogs BatchGet で log_id 所有 + place_id 一致確認（place_id 単独は全走査になるため log_id 必須）。BatchGet は log_id 重複排除、`UnprocessedKeys` は deadline 内有限リトライ。
- **カウンタ事前予約**: リクエスト内で place_id 重複排除し、件数分を user/global/**月次** places カウンタへ原子的事前予約（Place Details 1件=1リクエスト、横断キャッシュ無し）。
- **Place Details**: `GET https://places.googleapis.com/v1/places/{URLエンコード済みID}?languageCode=ja&regionCode=JP`、ヘッダー `X-Goog-Api-Key` + `X-Goog-FieldMask: displayName,attributions`（**Nearmy式のbody方式では失敗** — 契約テスト必須）。全体 deadline 付き並列。
- **応答**: `{results:[{log_id, display_name, name_source:"google", attributions:[…]}]}`（**DynamoDB に書かない** — 永続化はポリシー違反）。**NOT_FOUND（閉店/ID失効）はプレースホルダ**、部分失敗はその項目のみプレースホルダ。
- **SKU注意**: `displayName` の Place Details は **Details Pro**、Nearby は **Nearby Search Pro** で課金。上限は COST_MATRIX の予算逆算値（places 日次15/月次150）を厳守。

## 検証

`pytest tests/lambda/test_drink_log_analyze.py tests/lambda/test_drink_log_places.py`（Bedrock/HTTP/Secrets は stub、実呼び出ししない）。**ai-result スキーマの往復テスト**: analyze が保存した item を drink-logs の消費ロジック（`_consume_analysis` 相当）が受理できることを結合テストで検証（分離実装の齟齬を防ぐ）。`cd infra && npx jest`（infra不変確認）。

## してはならないこと

- インフラ/IAM/ルート/env/Scheduler の変更（タスク06確定）。`images.py` の再実装（タスク07の共有版を import）。
- drink-logs/reviews/ranking/list/search の変更。実 AWS/Bedrock/Places アクセス（stub のみ）。コミット作成。
- Bedrock/Places シークレット・APIキーのハードコードやログ出力。GPS座標のDrinkLogs保存、Google表示名の永続化。Global推論プロファイルの使用（JP固定のみ、IAMはタスク06確定）。
