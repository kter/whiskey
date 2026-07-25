# Task 03d: 検索の「空ページ + next_token」修正（サーバー側ページ充填）

## 問題（dev 実機の Chrome スモークで検出）

`GET /api/whiskeys/search?q=響&limit=20` が `{"whiskeys": [], "count": 0, "next_token": "..."}` を返す。
原因は2つの合成:

1. `whiskey_search_service.search_whiskeys` が scan に `Limit: limit` を渡している。scan の `Limit` は**走査件数**であってフィルタ一致件数ではないため、「20件走査して一致0 + LastEvaluatedKey」の空ページが正常系として発生する。`PUBLIC_SCAN_MAX_PAGES=1` なので内部継続もしない。
2. `frontend/pages/search.vue` は `advancedResults.length === 0` で「該当するウイスキーが見つかりませんでした」を表示し、`next_token` があっても「さらに読み込む」ボタン（`v-else` の結果ブロック内にある）へ到達しない。

計画は同種の問題（FilterExpression + limit Query）についてタイムライン GET で「サーバー側で内部ページを反復し（上限付きループ）指定件数を満たすか走査終了まで進め、途中状態を next_token にエンコード」という方式を確立済み。検索もこれに揃える。

## 修正

### バックエンド（`lambda/whiskeys-search/python/whiskey_search_service.py` + 必要なら `lambda/common/python/whiskey_common/scan_utils.py`）

- `search_whiskeys` を**ページ充填ループ**に変更: フィルタ一致アイテムが `limit` 件に達するか、走査が末尾に到達するか、内部ページ数が `PUBLIC_SCAN_MAX_PAGES` に達するまで scan ページを反復する。
  - scan の per-page `Limit` は `limit` をそのまま渡さない（走査量制御としては `PUBLIC_SCAN_PAGE_SIZE`（新設 env、デフォルト 250）等の内部ページサイズを使うか、Limit なし = 1MB ページでもよい。どちらを選ぶかは実装で決めてよいが、**1リクエストの走査上界 = ページサイズ × max_pages が有限で明示されている**こと）
  - 一致件数が `limit` を超えた分は切り捨て、`next_token` は**最後に返却したアイテムの主キー**（`{"id": ...}`）をエンコードして返す（scan の `ExclusiveStartKey` は実在アイテムの主キーで再開可能）。切り捨てが無い場合は最終ページの `LastEvaluatedKey`（なければ None）。
  - `max_pages` 到達時に一致 0 件でも `next_token` を返すのは契約どおり許容（無言の切り捨て禁止）。ただし通常のデータ規模ではこのケースが起きないよう max_pages を引き上げる（下記）。
  - scan 日次カウンタ（`before_page`）の消費単位は現行どおり**内部ページごと**を維持。
- 実装を `scan_utils` に一般化して置く場合（例: `scan_filtered_page(table, target_items, ...)`）は、既存 `scan_all_pages` の他の利用箇所（reviews 公開一覧等）の挙動を変えないこと。

### インフラ（`infra/lib/whiskey-infra-stack.ts`）

- search 関数の `PUBLIC_SCAN_MAX_PAGES` を `'1'` → `'5'` に引き上げ（list は Limit=limit の非フィルタ scan でページが常に充填されるため据え置きでよい。変更する場合は理由をコメント）。
- 新設 env（`PUBLIC_SCAN_PAGE_SIZE` を採用した場合）を search 関数に追加。
- jest のスナップショット/assertion を追随。

### フロントエンド（`frontend/pages/search.vue`）

- 「見つかりませんでした」表示の条件を `advancedResults.length === 0 && !isAdvancedSearching && !advancedNextToken` に変更。
- 0件でも `advancedNextToken` がある場合は結果ブロック側を描画し、「さらに読み込む」ボタン（+「続きを検索できます」等の案内文言）を表示する（バックエンド修正後も max_pages 到達時の防御として必要）。

### ローカルアダプタ

- `local_api` で search に渡る env（`PUBLIC_SCAN_MAX_PAGES` 等）があれば同じ値に追随（なければデフォルトで動くことを確認するだけでよい）。

## テスト

- pytest（`tests/lambda/`）:
  1. 「1ページ目に一致なし・2ページ目に一致あり」のデータ配置で、1リクエストが充填済み結果を返す（moto または stub で LastEvaluatedKey を再現）
  2. 一致件数 > limit のとき limit 件 + 最後の返却アイテム主キー由来の next_token、そのトークンで続きが正しく取れる（重複・欠落なし）
  3. max_pages 到達時: 部分結果（0件含む）+ next_token
  4. 走査末尾到達時: next_token = None
- vitest: 0件 + next_token → 「見つかりません」を出さず「さらに読み込む」を表示 / 0件 + token なし → 「見つかりません」表示
- `cd infra && npx tsc --noEmit && npx jest && npx cdk synth -c env=dev > /dev/null`
- `cd frontend && npm run lint && npm run typecheck && npx vitest run`

## してはならないこと

reviews / ranking / list のロジック変更（scan_utils を触る場合も既存挙動維持）、上記以外のファイル変更、コミット作成、実 AWS アクセス。
