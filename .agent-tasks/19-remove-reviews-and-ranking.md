# Task 19: レビュー機能とランキング機能を削除し、飲酒ログ（記録）に一本化する

## 背景

本番稼働後の方針転換で、アプリを**飲酒ログ（記録）機能に一本化**する。
レビュー投稿・閲覧機能と、それに依存するランキング機能を削除する。

ランキングはレビューを入力にしている（`lambda/ranking-aggregator/index.py:168` が
`REVIEWS_TABLE` を読み、`frontend/pages/ranking.vue:46` が `avg_rating` /
`review_count` を表示している）ため、レビュー削除に伴い道連れで削除する。

## 残すもの（絶対に消さないこと）

- **飲酒ログ機能一式** — `logs` 配下のページ、`drink-logs` / `drink-log-analyze` /
  `drink-log-places` / `drink-log-reconciler` Lambda、`DrinkLogs` テーブル、画像バケット
- **銘柄検索機能** — `frontend/pages/search.vue`、`whiskeys-list` / `whiskeys-search`
  Lambda、`/api/whiskeys/` `/api/whiskeys/search/` `/api/whiskeys/suggest/` 系エンドポイント
- **`WhiskeySearch` テーブルとその 2,449 件のデータ** —
  `lambda/drink-log-analyze/index.py:548` が銘柄の突合に使う。記録機能の中核であり、
  検索機能を残す判断とは無関係に必須
- **`AppState` テーブル** — 濫用/コスト防御の原子カウンタが載っている。
  ランキングキャッシュのエントリだけが不要になるが、テーブル自体は残す
- 認証（Cognito、Google ログイン）、プロフィール、利用規約、プライバシーポリシー

## 削除するもの

### 1. フロントエンド

- `frontend/pages/reviews/` 配下の4ページをすべて削除
  - `index.vue` / `new.vue` / `[id]/index.vue` / `[id]/edit.vue`
- `frontend/pages/ranking.vue` を削除
- `frontend/layouts/default.vue` のナビゲーションから「レビュー」と「ランキング」のリンクを削除
  （`/search` と `/logs` のリンクは残す）
- `frontend/pages/home.vue` のレビュー投稿・レビュー一覧・ランキングへの導線を削除し、
  **記録機能への導線を主役に据え直す**。文言は既存のトーン（`logs/new.vue` の
  「フォトファースト飲酒ログ」「今日の一杯を記録」）に合わせること
- `frontend/pages/index.vue` の「この銘柄をレビュー」リンク（20行目付近）を削除。
  銘柄カードから記録画面へ誘導する形にするか、リンク自体を落とすかは
  ページの意図に沿って判断し、報告すること
- `frontend/composables/useWhiskeys.ts` からレビュー/ランキング関連の関数を削除。
  検索・一覧に使われている関数は残すこと（**呼び出し元を確認してから消すこと**）
- `frontend/types/whiskey.ts` のレビュー/ランキング関連の型定義を削除
- 上記に対応するテスト（`frontend/tests/`）を更新。削除した機能のテストは削除し、
  残る機能のテストは通ること

### 2. Lambda

- `lambda/reviews/` ディレクトリごと削除
- `lambda/ranking-aggregator/` ディレクトリごと削除
- `lambda/whiskeys-search/index.py` にレビュー/ランキング由来のコードがあれば削除する。
  ただし**検索機能そのものは残す**ので、慎重に切り分けること
- 対応するテストを削除: `tests/lambda/test_reviews.py`、`tests/lambda/test_ranking_aggregator.py`
- `tests/lambda/test_openapi_contract.py` からレビュー/ランキングのエンドポイント契約を削除
- `tests/lambda/test_whiskeys_search.py` は検索機能のテストなので**残す**。
  レビュー由来の記述があれば削除する

### 3. インフラ（`infra/lib/whiskey-infra-stack.ts`）

- `ReviewsFunction`（`reviews-{env}`）とその IAM ロール・ロググループを削除
- `RankingAggregatorFunction`（`ranking-aggregator-{env}`）とその IAM ロール・
  ロググループを削除
- ランキングのスケジュール実行一式を削除（744行目付近から）:
  `RankingScheduleDlq`、`RankingScheduleGroup`、`RankingScheduleTargetRole`、
  および EventBridge Scheduler のスケジュール本体
- `ReviewsTable`（`Reviews-{env}`）を削除。**バックアップは不要**（prd は 0 件、
  dev は検証用データのみ、と確認済み）
- API Gateway から `/api/reviews` 配下と `/api/whiskeys/ranking/` のリソース・
  メソッド・Lambda 統合を削除
- 各 Lambda の環境変数から `REVIEWS_TABLE` を削除。ただし他の用途で参照している
  箇所がないか確認すること
- `WhiskeyInfraStack` の public プロパティに影響がないか確認する
  （`errorAlarmFunctionNames` は `drink-log-analyze` と `drink-log-places` のみなので影響なし）
- 不要になった IAM 権限（Reviews テーブルへの読み書き）を他の Lambda のロールから削除

### 4. ドキュメント

- `CLAUDE.md` と `README.md` と `infra/README.md` から、レビュー機能・ランキング機能の
  記述を削除する。特に以下:
  - Lambda 一覧から `reviews-dev` と `ranking-aggregator-dev`
  - DynamoDB テーブル一覧から `Reviews-dev`
  - API エンドポイント一覧から `/api/reviews/` と `/api/whiskeys/ranking/`
  - 環境変数一覧から `REVIEWS_TABLE`
  - アプリケーション概要の説明を「記録機能に一本化された」実態へ整合させる
- `AppState` の説明から「ランキングキャッシュ」を外し、
  濫用/コスト防御カウンタのみである旨に更新する

## 制約

- **既存の飲酒ログ機能と検索機能の動作を変えないこと。** 削除の巻き添えで壊れていないか、
  テストで担保すること
- 依存パッケージの追加・更新は禁止
- AWS へのデプロイは行わない（コード変更のみ）
- `WhiskeySearch` テーブルの定義・GSI・データに一切触れないこと
- 秘密情報をコードに埋め込まない

## 受入条件（すべて実行して結果を報告すること）

```bash
# バックエンド
python -m pytest tests

# インフラ
cd infra && npx tsc --noEmit && npm test && npm run synth:dev && npm run synth:prd

# フロントエンド
cd frontend && npm run lint && npx vitest run
```

- すべて成功すること
- `cdk.out/WhiskeyApp-Prd.template.json` から次を確認して報告すること:
  - `AWS::DynamoDB::Table` に `Reviews-prd` が**存在しないこと**
  - `AWS::DynamoDB::Table` に `WhiskeySearch-prd` / `DrinkLogs-prd` / `AppState-prd` が
    **存在すること**
  - `AWS::Lambda::Function` に `reviews-prd` と `ranking-aggregator-prd` が
    **存在しないこと**
  - `AWS::Lambda::Function` に `whiskey-search-prd` / `whiskey-list-prd` /
    `drink-logs-prd` / `drink-log-analyze-prd` / `drink-log-places-prd` /
    `drink-log-reconciler-prd` が **存在すること**
  - EventBridge Scheduler のスケジュールが存在しないこと
- 残った API Gateway のパス一覧を抽出して報告すること

## 報告してほしいこと

- 削除したファイルと変更したファイルの一覧
- `frontend/pages/index.vue` と `home.vue` をどう作り替えたか、その判断理由
- `useWhiskeys.ts` から何を消し何を残したか、呼び出し元をどう確認したか
- 上記コマンドの実行結果
- 削除の巻き添えで壊れかけた箇所があれば、その内容と対処
