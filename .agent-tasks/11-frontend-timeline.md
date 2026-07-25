# Task 11: タイムライン（一覧 + 詳細/編集/削除）

新規: `frontend/pages/logs/index.vue`（タイムライン一覧）, `frontend/pages/logs/[id].vue`（詳細+編集+削除）。変更: 必要なら `frontend/composables/useDrinkLogs.ts`（タスク10の共有ストア/メソッドを利用・拡張）。テスト: `frontend/tests/pages/` に vitest。**バックエンド・インフラは変更しない**（06〜09確定）。

パターン: タスク10の `useDrinkLogs`（`listLogs`/`getLog`/`updateLog`/`deleteLog`/`resolvePlaces` + useState 共有ストア）、`useApi`、`useAuth`（`waitForAuthReady`/`currentUserId`）。既存詳細ページ雛形 `pages/reviews/[id]/index.vue`、Tailwind stone/amber。ナビ「記録」リンクは task 10 で `/logs` 追加済み。

## API 契約（実装済み・厳守）

- `GET /api/drink-logs?limit&next_token&brand&store&place_id` → `{results:[record…], count, next_token}`。
- `GET /api/drink-logs/{id}` → 単一 record（`image_url` 付き）。他人のは 404。
- `PUT /api/drink-logs/{id}` body `{brand_text?, store?:{name,place_id?}, notes?, rating?, serving_style?}`（**不変フィールド id/user_id/s3_image_key/created_at/datetime は送らない**）→ 更新後 record。
- `DELETE /api/drink-logs/{id}` → 204。
- `POST /api/drink-logs/places/resolve` body `{items:[{log_id, place_id}]}`（最大10）→ `{results:[{log_id, display_name, name_source:"google", attributions:[…]}]}`（**永続化しない・表示のみ**）。
- record 形状（内部フィールドは strip 済み）: `{id, user_id, status, datetime(RFC3339 UTC), image_url, brand_text, brand_source(ai|manual|matched), serving_style, store:{name, place_id?}, notes?, rating?, ai?, created_at, updated_at}`。
- 全て `auth:'required'`。

## `pages/logs/index.vue`（タイムライン）

- **日付グルーピング**: `datetime`（UTC保存）を**ローカルTZで和書式表示**（例「2026年7月21日」）してグループ化。保存は UTC のまま扱う。
- 各エントリ: 写真サムネイル（`image_url`）、「いつ・どこで・何を・どう飲んだか」= 日時 + 店名 + 銘柄 + 飲み方。`rating` があれば ★ 表示。
- **next_token 無限スクロール**（IntersectionObserver で末尾到達時に `listLogs({next_token})` 追加取得。`count`/`next_token` 契約に従う）。
- **銘柄/店フィルタチップ**: `brand`/`store` クエリパラメータでサーバーフィルタ（入力 → `listLogs({brand})` 等で再取得、`next_token` リセット）。
- 各エントリから詳細 `/logs/{id}` へ。
- **空状態**: 「まだ記録がありません。最初の一杯を記録しましょう」+ `/logs/new` への導線。

## `pages/logs/[id].vue`（詳細 + 編集 + 削除）

- フル画像（`image_url`）+ 全項目表示。所有者のみ（API が 404 を返すのでハンドリング）。
- **編集**: `brand_text`/`store.name`/`serving_style`/`rating`/`notes` を PUT（不変フィールドは送らない）。**銘柄編集時は brand_source が manual になる**旨は API 側の挙動（フロントは brand_text を送るだけ）。store 候補の再選択（`searchPlaces` 経由で place_id 差し替え）も可能にする（任意）。
- **削除**: 確認の上 `deleteLog(id)` → 共有ストアから除去 → `/logs` へ。**ブラウザ標準の `confirm()` ダイアログは使わず**、ページ内モーダル/インライン確認で行う（ダイアログはブラウザ自動化を止めるため）。

## Google 帰属表示（Places ポリシー）

- **store.name が空 + place_id がある record は、表示時に `resolvePlaces` で都度解決**（`{items:[{log_id, place_id}]}`、`name_source:"google"` の `display_name` + `attributions` を取得）。**可視領域のみ IntersectionObserver で遅延解決 + log_id 重複排除の上10件ずつチャンク（同時実行最大2）**。結果は**表示中コンポーネントの状態のみ**に保持（画面遷移/アンマウントで破棄、再表示時に再解決 — セッション横断キャッシュも永続化も禁止）。解決失敗/NOT_FOUND は「場所登録済み」プレースホルダ。
- **`name_source=google` の店名が表示される全箇所（タイムライン・詳細の両方）に帰属表示**（`attributions` を隣接描画。記録フォームだけでは不足）。共通の表示モデル/コンポーネントで帰属が必ず付くようにする。

## 保存直後の整合性

- GSI は結果整合のため、保存レスポンス（`image_url` 込み）を**ID で upsert**（単純先頭挿入だと GSI 反映後に重複表示）。**useState ベースの共有ストア**（タスク10で導入）で、記録ページの保存 → タイムライン遷移でも同一インスタンスに届くようにし、**ID重複排除 + 日時再ソート**まで契約化。保存→遷移直後「消えた」ように見える事象を防ぐ。E2E（vitest）で upsert/重複排除/再ソートを検証。

## presigned URL 失効対策

- 画像 `<img @error>` で該当 record を `getLog(id)` 再取得し新しい `image_url` へ差し替え。**再署名は画像ごと1回まで**、なお失敗ならプレースホルダに確定（恒久404での無限リトライ防止）。

## 検証

`cd frontend && npm run lint && npm run typecheck && npx vitest run`（全緑）。`npm run generate`（成功、`/logs`・`/logs/[id]` プリレンダ）。**vitest**: 日付グルーピング（ローカルTZ）、無限スクロール（next_token追加取得）、フィルタチップ、共有ストア upsert/重複排除/再ソート、presigned URL onerror 再署名1回→プレースホルダ、place_id 遅延解決 + 帰属表示（タイムライン・詳細両方）、編集 PUT（不変フィールド非送信）、削除（インライン確認・標準dialog不使用）、他人レコード404。

## してはならないこと

- バックエンド/インフラ/ローカルアダプタの変更。不変フィールド（datetime 含む）の PUT 送信。Google 表示名や GPS 座標のローカルストレージ/永続ストアへの保存。`confirm()`/`alert()` 等ブラウザ標準ダイアログの使用。実 API キーのハードコード。コミット作成。
