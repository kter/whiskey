# Task 02: Lambda 認証修復・Docker バンドリング・共通レイヤー・レビュー API 修復

## Goal

reviews Lambda の署名検証なし JWT フォールバック（重大脆弱性）を削除し、依存が確実に同梱される Docker バンドリングへ移行、共通コードをレイヤーに集約し、壊れている既存レビュー API（契約不一致・ルート欠落・全件公開）を修復する。**バックエンド（lambda/ + infra のバンドリング/レイヤー定義 + テスト）が対象。フロントエンドは変更しない**（フロント側の追従はタスク04）。

## 背景（必読）

- タスク01適用済みの状態から作業する: API Gateway に Cognito オーソライザー（ID トークン検証）装着済み、AppState テーブル定義済み、関数別ロール分割済み、`GET/DELETE /api/reviews/{id}` ルート定義済み、`PublicDateIndex`（疎 GSI: PK `public_pk`, SK `date`）定義済み。
- **現行の構造的欠陥**: CDK は `lambda.Code.fromAsset` で素の zip を作るだけで `pip install` しないため、reviews の PyJWT/requests が本番に存在せず、`from jwt_utils import ...` が ImportError → `lambda/reviews/index.py:69-90` の**署名検証なし base64 デコード**に落ちる。この経路は削除する。
- フロントは今後 **ID トークン**を送る（タスク04）。オーソライザー未経由のローカル実行では Lambda 側で完全検証する。

## 変更対象

- `lambda/common/` → `lambda/common/python/whiskey_common/` へ再構成（レイヤー化）
- `lambda/reviews/index.py` / `lambda/reviews/jwt_utils.py` / `lambda/reviews/requirements.txt`
- `lambda/whiskeys-list/index.py` / `lambda/whiskeys-search/**`（共通ヘルパー移行のみ — scan 効率化はタスク03）
- `infra/lib/whiskey-infra-stack.ts`（バンドリング + レイヤー装着のみ）
- `tests/lambda/**`、新規 ルート `pyproject.toml` + `requirements-dev.txt`
- `API_REFERENCE.md` / `swagger.yml` / `docs/GOOGLE_AUTH_SETUP.md`

## 要求仕様

### 1. 危険フォールバックの削除と識別順序（H2）
- `lambda/reviews/index.py:69-90` の base64 デコードフォールバックを**完全削除**。
- 識別順序: ① `event.requestContext.authorizer.claims` が存在すればそれを使用 — **ただし claims の `aud == COGNITO_CLIENT_ID` と `token_use == 'id'` を Lambda 側でも再検証**（多層防御）② なければ `whiskey_common.jwt_utils` で完全検証 ③ どちらも失敗なら 401。

### 2. jwt_utils の強化
- ID トークン前提: RS256 署名 + `exp`/`iat` + `iss` + **`aud == COGNITO_CLIENT_ID`** + **`token_use == 'id'`** を検証。環境変数 `COGNITO_CLIENT_ID` を追加（infra 側で渡す）。
- **依存修正: `PyJWT[crypto]`（cryptography）をピン止め** — 素の PyJWT では RS256 検証が実行不能。
- **JWKS キャッシュのローテーション対応**: 未知の `kid` に遭遇したら1回だけ JWKS を再取得（現行は無期限キャッシュ + 未知 kid 即拒否）。ローテーションテスト付き。

### 3. Docker バンドリング（D8）
- 全関数を `Code.fromAsset(path, { bundling: {...} })` に変更。コマンドは**「pip install（requirements.txt が存在する場合）+ ソース一式コピー」の両方**:
  `bash -c 'if [ -f requirements.txt ]; then pip install -r requirements.txt -t /asset-output; fi && cp -au . /asset-output'`
- **全関数に requirements.txt を用意**（whiskeys-list / whiskeys-search は空でよい）。全ランタイム依存はバージョン固定。
- **アーキテクチャ固定**: Docker platform `linux/amd64` + Lambda `architecture: X86_64` を明示（Apple Silicon での arm64 wheel 混入による ImportError 防止）。
- バンドル成果物に `index.py` が存在することのテスト（cdk.out のアセットを検査する jest でよい）。

### 4. 共通レイヤー `lambda/common/python/whiskey_common/`
モジュール構成:
- `logger.py`（既存移設 + **redact 機能**: lat/lng・store・brand 等のクエリ/ボディ値はパラメータ名のみ記録）
- `responses.py`: `create_response` / CORS ヘルパー（`ALLOWED_ORIGINS` 環境変数から動的エコー + **必ず `Vary: Origin` を併記**。認証済み個人データ系には `Cache-Control: private, no-store` を付与するオプション）
- `jwt_utils.py`（上記2）
- `normalize.py`（whiskey_search_service の日本語正規化を移設）
- `decimal_utils.py`（decimal_default の集約）
- `clients.py`: boto3 クライアントファクトリ — 全 AWS クライアントに connect/read タイムアウト + `mode='standard'` + 低 `total_max_attempts` を一律設定。S3 は `AWS_ENDPOINT_URL_S3` + path-style、DynamoDB は `AWS_ENDPOINT_URL_DYNAMODB` を尊重（**グローバル `AWS_ENDPOINT_URL` は参照しない** — whiskey_search_service.py:35 の既存グローバル参照も置換）
- `scan_utils.py`: ページネーション完備の scan ヘルパー（全ページ走査・最大ページ数上限・LastEvaluatedKey → next_token エンコード）。※利用への切替はタスク03
- CDK: `LayerVersion`（Docker バンドリング、`lambda/common` から）を全関数に装着。コピペ重複（SimpleLogger / decimal_default / get_cors_headers / create_response）を排除し、各 index.py はレイヤーから import（ローカルパス用の try/except フォールバックは import 経路のみ許可 — セキュリティ動作のフォールバックは禁止）。

### 5. レビュー API の修復
- **契約統一**: 作成/更新は `whiskey_id` 必須。`whiskey_id` は WhiskeySearch への**強整合存在確認**を通過した場合のみ受理（不存在は 400）。
- **所有者用 `GET /api/reviews/{id}` と `DELETE /api/reviews/{id}` のハンドラ実装**（ルートはタスク01で定義済み）。
- **PUT/DELETE の TOCTOU 排除**: GetItem→無条件 Update をやめ、`ConditionExpression user_id = :caller` で原子的に強制。条件不成立は 404。
- **PUT の不変フィールド**: `whiskey_id` の変更は拒否（ホワイトリスト方式 — 可変は rating/notes/serving_style/date/is_public のみ）。
- **公開一覧の修復**: `GET /api/reviews/public` は `PublicDateIndex` を Query（`limit`/`next_token` ページネーション）→ **候補をベーステーブルの強整合 BatchGet で再読し `is_public == true` を再確認したものだけ返す**（GSI 結果整合による非公開化直後の漏洩対策）→ `user_id` 等の識別子は応答から除外。`?public=true` 分岐は削除。
- **is_public / 疎 GSI 属性の維持**: 作成/更新で `is_public=true` なら `public_pk='PUBLIC'` を SET、false なら REMOVE。**既存レコード（フラグ無し）は非公開扱い**。公開→非公開遷移後に公開 Query から消えるテスト必須。
- **入力検証**: rating（現行フロントの実仕様を確認し範囲固定）、notes ≤2000字、`serving_style` は正準 enum **大文字 `NEAT/ROCKS/WATER/SODA/COCKTAIL`**（swagger.yml の小文字別値を修正）、`date` は `YYYY-MM-DD` の full-date のみ、`is_public` は boolean。違反は 400 + フィールドエラー。
- **`image_url` フィールドの廃止**: 受理しない（送られてきたら無視 or 400）。既存の保存/表示コードパスを削除（写真は将来の飲酒ログ機能が担当）。
- **レビュー書き込みの濫用対策**: POST に AppState のユーザー/グローバル日次カウンタ（TransactWriteItems の条件付き increment、超過 429）。カウンタ item は UTC 日付入り PK + TTL。
- **ランキング dirty カウンタ**: レビューの作成/更新/削除と AppState「レビュー変更カウンタ」の increment を**同一 TransactWriteItems** で原子化（タスク03の集計 Lambda が消費）。
- **ユーザーレビュー一覧のページネーション**: `UserDateIndex` Query に `limit`/`next_token` を追加（現行は 1MB 1ページ目のみ）。
- **500 応答の情報漏洩修正（M2）**: 3 Lambda すべてで `str(e)` を汎用メッセージ + リクエストID に置換（詳細はログのみ）。

### 6. テスト基盤
- ルート `pyproject.toml`: pytest 設定（pythonpath は使わず、**importlib で一意モジュール名ロードするテストヘルパー**を用意 — reviews と whiskeys-search が同名 `index` を import する衝突の解消）。
- `requirements-dev.txt`: pytest / PyJWT[crypto] / requests / boto3 / moto 等をバージョン固定（全 Lambda 依存の和集合）。
- クリーンチェックアウトから `pip install -r requirements-dev.txt && python -m pytest tests/` が全緑。
- 既存テスト（test_reviews / test_jwt_utils / test_logger*）は新構成に合わせて更新。危険フォールバックのテストは削除し、401 経路のテストに置換。

### 7. ドキュメント
- `API_REFERENCE.md`: access→ID トークン、公開パス分離、GET/DELETE 追加、ページネーション、**未実装 `/health/` の記述削除**。
- `swagger.yml`: 同上 + **`ReviewCreateInput` / `ReviewUpdateInput` の分離**（更新は可変フィールドのみ）+ serving_style enum 修正。OpenAPI ↔ Lambda のクロス契約テスト（enum 全値・必須フィールド）。
- `docs/GOOGLE_AUTH_SETUP.md`: シークレットキー名を新契約（SSM `/whiskey/{env}/google-client-id` + Secrets Manager はシークレットのみ）に一致。

## 受入条件

1. `pip install -r requirements-dev.txt && python -m pytest tests/` 全緑（クリーン環境）
2. `cd infra && npx jest && npx cdk synth -c env=dev > /dev/null` 成功、バンドル成果物検査テスト含む
3. grep 検証: base64 JWT デコードの残存ゼロ / `str(e)` が応答ボディに残存ゼロ / `image_url` の受理コード残存ゼロ
4. フロントエンド（frontend/）は未変更

## してはならないこと

- フロントエンド変更・実 AWS アクセス・コミット作成
- scan の効率化/ランキング変更（タスク03の領分 — このタスクでは既存ロジック温存で共通ヘルパー移行のみ）
- 新規依存はレイヤー/関数の requirements と requirements-dev のみ（infra への npm 依存追加は禁止）
