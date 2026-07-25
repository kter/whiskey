# Task 09: ローカルアダプタ配線（飲酒ログ）+ フルフロー結合テスト

タスク06〜08で drink-logs/analyze/places/reconciler の実装とルーティングは完了済み。**本タスクの穴は3点のみ**: ①ローカル env に不足している drink-log 系変数の追加 ②フルフローの HTTP 結合テスト ③`docs/LOCAL_DEV.md` 更新。対象: `local_api/main.py`（env のみ）、`tests/local_api/test_drink_logs_flow.py`（新規）、`docs/LOCAL_DEV.md`。**ハンドラ本体・ルート定義・インフラは変更しない**（06〜08確定）。

## 背景（調査済みの事実）

- `local_api/main.py` の `configure_local_environment()` はテーブル/エンドポイント/資格情報/`MOCK_AUTH` 経由の `COGNITO_CLIENT_ID=local-client` は設定するが、**drink-log 系の以下が欠落**しており、analyze ハンドラの `_validate_runtime_config()`（`lambda/drink-log-analyze/index.py:98`）が `BEDROCK_MODEL_ID` 不在で `RuntimeError` を送出するため、ローカルで analyze が動かない。
- カウンタ上限 env（`ANALYZE_*`/`UPLOAD_*`/`CREATE_*`/`STORAGE_*`/`PLACES_*`/`IMAGE_MAX_BYTES`/`UPLOAD_MAX_BYTES`）は全ハンドラが `os.environ.get(..., "デフォルト")` で COST_MATRIX 一致のデフォルトを持つため、ローカルでは**設定不要**（設定してもよいが必須ではない）。
- MOCK 経路: analyze は `_invoke_model`（`index.py:325`）が `ENVIRONMENT==local` かつ `MOCK_AI` で決定的候補を返す。places は `_api_key()`（`places.py`）と検索/解決が `_mock_places_enabled()` で早期モックし Secrets/HTTP を叩かない。claims 注入は `_mock_claims()` で機能済み。

## ① ローカル env 追加（`configure_local_environment()` の `fixed` 辞書）

追加:
```
"MOCK_AUTH": os.environ.get("MOCK_AUTH", "1"),          # 既定でモック認証（実JWT検証したい時のみ 0 に）
"MOCK_AI": "1",
"MOCK_PLACES": "1",
"BEDROCK_MODEL_ID": "jp.amazon.nova-2-lite-v1:0",
"BEDROCK_MODEL_ALLOWLIST": "jp.amazon.nova-2-lite-v1:0,jp.anthropic.claude-haiku-4-5-20251001-v1:0",
"PLACES_SECRET_NAME": "whiskey-places-local",
"RECONCILE_AGE_HOURS": "48",
```
注意: 現状 `MOCK_AUTH` は環境から読む前提で `COGNITO_CLIENT_ID` を分岐設定している。**`MOCK_AUTH` を `fixed` に入れる場合、その分岐（`configure_local_environment` の後半）より前に設定されること**を確認（順序依存。既存の分岐ロジックは壊さない）。`AWS_ENDPOINT_URL` 全体設定禁止の既存ガードも維持。**非 local ビルドで MOCK_* が誤って効かないよう、これらは `configure_local_environment`（`ENVIRONMENT=local` 固定の関数）内だけで設定する**。

## ② フルフロー HTTP 結合テスト `tests/local_api/test_drink_logs_flow.py`

FastAPI `TestClient`（既存 `tests/local_api/test_main.py` のパターンに倣う）+ **moto で S3 と DynamoDB を moto サーバ/デコレータでモック**（既存テストの手法に合わせる。`AWS_ENDPOINT_URL_DYNAMODB`/`AWS_ENDPOINT_URL_S3` と moto の両立は既存 test_main.py の方式を踏襲。難しければ moto の `server` モードか、ハンドラを直接呼ぶ結合でもよいが、**HTTP 経由（TestClient）で upload-url→create→timeline を通すこと**）。テーブル/バケットはテスト内で作成（`scripts/local/init_tables.py` 相当の最小定義）。

フロー:
1. `POST /api/drink-logs/upload-url {content_type:"image/jpeg"}` → 200、`upload_url`/`fields`/`s3_key`（`tmp/{uid}/…`）取得。
2. presigned POST の代わりに（moto では presigned POST 検証が限定的なため）**`fields` の `key` に従い S3 put_object で tmp オブジェクトを配置**（実バイトは Pillow で生成した小 JPEG）。ETag 取得。
3. `POST /api/drink-logs/analyze {s3_key}` → MOCK_AI 経路で 200、`analysis_id` + `candidates`（モック銘柄）取得。ai-result item が AppState に保存されていること。
4. `POST /api/drink-logs {analysis_id, candidate_index:0, datetime:<RFC3339 UTC>, store:{name:""}, …}` → 201/200、`status:complete` + `image_url`（`logs/{uid}/…`）。tmp が削除されていること。
5. `GET /api/drink-logs` → タイムラインに当該レコード（`image_url` 付き）、内部フィールド（`s3_image_key`/`tmp_s3_key`/`quota_allocated`）が応答に無いこと。
6. `POST /api/drink-logs/places {lat:35.68,lng:139.76}` → MOCK_PLACES 経路で決定的候補。
7. `DELETE /api/drink-logs/{id}` → 200、`GET` でタイムラインから消えること。
- 認証: `MOCK_AUTH=1` の注入 claims（aud=local-client, token_use=id）で通ること。未認証（claims 無し経路があれば）は 401。

## ③ `docs/LOCAL_DEV.md` 更新

drink-log フローのローカル実行手順（`docker compose up` → `make local-init` → `make api`、`MOCK_AI/MOCK_PLACES` 既定 ON、実 Places キーを使う場合は未追跡 `.env.local` から `MOCK_PLACES=0` + キー投入の手順）、`make local-aggregate` との関係、写真アップロードは MinIO の CORS 経由である旨を追記。

## 検証

`pytest tests/local_api/test_drink_logs_flow.py tests/local_api/test_main.py`（既存緑維持）。`pytest tests/`（全体回帰）。`cd infra && npx jest`（infra 不変確認）。**クリーンチェックアウト + `local_api/requirements-dev` の依存でインポート可能なこと**（moto[dynamodb,s3] が dev 依存にあること、無ければ追加）。

## してはならないこと

- ハンドラ本体・ルート定義・インフラ・IAM・env デフォルト値の変更（06〜08確定）。drink-logs/analyze/places/reviews/ranking/list/search のロジック変更。
- 実 AWS/Bedrock/Places アクセス。コミット作成。シークレット/APIキーのハードコード。
