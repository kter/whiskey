# 磨き込みバックログ（Phase 5 で処理する Low 指摘の集約）

レビューで APPROVE されたが未対応の Low 項目。Phase 5 のタスク 13x で消化する。

## タスク05レビューより（ローカル環境）
- [ ] seed の `normalized_name` 形式を本番パイプライン（`insert_whiskeys_to_dynamodb.py` の `normalize_text(name)` 単独 + `normalized_distillery`）と揃える
- [ ] `make local-aggregate` が `locked|dirty|deferred` を有限リトライで許容するように
- [ ] `docs/LOCAL_DEV.md` に「テストの実行方法」（`pip install -r requirements-dev.txt` → pytest）を追記
- [ ] アダプタの `request_to_api_gateway_event` にヘッダー小文字化の注意コメント（実 API GW は原文ケース保持）
- [ ] TestClient ベースのアダプタ E2E テスト（MOCK_AUTH 有無のイベント構築 + isBase64Encoded 変換）

## タスク04レビューより（フロントエンド）
- [ ] useAuth のエラー collapse を緩和（InvalidPassword/CodeMismatch/LimitExceeded 等の非列挙系は文言を出し分け）
- [ ] `auth: 'optional'` モードが現状未使用（利用箇所ができるまで維持 or 削除判断）
- [ ] package.json の `overrides: vite-plugin-checker` に理由コメント
- [ ] useApi `required` モードのリダイレクト経路テスト

## タスク03レビューより（バックエンド）
- [ ] `_batch_get` の UnprocessedKeys 破棄時に warning ログ
- [ ] search Lambda 環境変数の死に設定 `REVIEWS_TABLE` を除去
- [ ] 公開レビュー削除時のランキング反映遅延（最大15分）を設計メモに記載
- [ ] ランキングの同率時 name 逆順ソート修正
- [ ] CLAUDE.md / WHISKEY_DATA_MANAGEMENT.md の旧 `ENVIRONMENT=prd python scripts/...` 手順を新 `--target` 契約に更新（Phase 5 ドキュメント整合で対応）

## タスク01レビューより（インフラ）
- [ ] CI ロールの CloudFront 権限をタグ条件で絞る（現状 distribution/*）
- [ ] IdentityValidationExpression テストの論理ID固定は対応済みか確認
