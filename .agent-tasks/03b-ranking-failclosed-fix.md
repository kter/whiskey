# Task 03b: ランキング fail-closed の締め直し（外科的修正）

## 1.（必須・Medium）世代有効化が即時無効化マーカーを消し得るレース

`lambda/ranking-aggregator/index.py` の `_activate_generation`（:322-334）は ConditionExpression が `generation_id` しか見ず、UpdateExpression が `REMOVE dirty_since, invalidated_at` を行う。最終カウンタ再確認の後・有効化の前に reviews 側の非公開化トランザクション（`invalidated_at` 付与）が commit すると、有効化がマーカーを消して非公開レビュー込みの世代を公開してしまう。

修正: ConditionExpression の**両分岐**（`attribute_not_exists(#generation)` / `#generation = :old_generation`）に `AND attribute_not_exists(invalidated_at)` を追加。例外処理は変更しない — `ConditionalCheckFailedException` 時は既存どおり staged 世代を expire して `{"status": "superseded"}` を返し、meta の `invalidated_at` は残す（search が fail-closed を維持）。

## 2.（必須・Medium）`dirty_since` の起点が書き込み側で刻まれていない

仕様は「カウンタ変更時に dirty_since を記録」。現状は集計側の `_mark_dirty` が最初に気付いた時点で刻むため、集計失敗継続時の最悪陳腐化が45分でなく約60分になる。また `increment_whiskey_revision` は誰も読まない `whiskey-change-counter` item に dirty_since を書いている（死に属性）。

修正（推奨案a）: 書き込み側が meta に刻む —
- `lambda/reviews/index.py`: dirty カウンタ更新のトランザクション経路に `ranking-cache/meta` への `dirty_since = if_not_exists(dirty_since, :updated_at)` 更新を追加（reviews ロールは既に meta への UpdateItem 権限を保有）
- `scripts/insert_whiskeys_to_dynamodb.py` の `increment_whiskey_revision`: dirty_since の書き込み先をカウンタ item から `ranking-cache/meta` に変更
- `_mark_dirty` の `if_not_exists` 意味論は維持（最古のタイムスタンプが勝つ）。有効化時の REMOVE も現状どおり

## 3. テスト追加

- (i) 最終カウンタ確認と有効化の間にマーカーが書かれた場合 → 有効化条件失敗・status `superseded`・meta に `invalidated_at` 残存・staged ページに TTL 付与
- (ii) deadline 超過 → `{"status": "deferred"}` + lease 解放
- (iii) レガシー契約: パラメータなしの ranking が素の配列を返す
- (iv) staging ページが有効化**前**に TTL を持つ

## 保持するもの

既存の全ステータス（skipped/locked/dirty/superseded/published/deferred）、IAM ステートメント、Scheduler 配線、scan_utils/cost_guard の挙動、search Lambda の読み取り専用性。

## 検証

`python -m pytest tests/` 全緑 / `cd infra && npx jest && npx cdk synth -c env=dev > /dev/null` / `lambda/whiskeys-search/` 配下に DynamoDB 書き込みゼロ（grep）。

## してはならないこと

上記以外のファイル変更・コミット作成・フロントエンド変更。
