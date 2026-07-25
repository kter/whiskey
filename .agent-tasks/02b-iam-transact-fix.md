# Task 02b: reviews トランザクション用 IAM アクション名の修正 + 小型改善

## 必須（High）: 実在しない IAM アクション `dynamodb:TransactWriteItems` の修正

問題: `infra/lib/whiskey-infra-stack.ts:309-316` が `dynamodb:TransactWriteItems` を付与しているが、**このアクション名は IAM に存在しない**。DynamoDB トランザクションは項目単位アクション（UpdateItem/PutItem/DeleteItem/ConditionCheckItem）で認可される。IAM は未知アクション名を拒否しないためデプロイは成功し、実行時に reviews の POST/PUT/DELETE が AppState カウンタ更新の AccessDenied で全件失敗する。

修正:
1. `whiskey-infra-stack.ts:309-312` — AppState 向けステートメントのアクションを `['dynamodb:UpdateItem']` に変更（`dynamodb:LeadingKeys` 条件はそのまま維持）。
2. `whiskey-infra-stack.ts:313-316` — reviewsTable への無条件 `dynamodb:TransactWriteItems` ステートメントを削除（`grantReadWriteData` が既にカバー）。
3. `infra/test/infra.test.ts:316-323` — 期待値を修正: AppState 向け `dynamodb:UpdateItem` + LeadingKeys `['review-rate#*', 'review-change-counter']` 条件付きステートメントの存在をアサート + **`TransactWriteItems` という文字列がロールポリシーに一切現れないこと**をアサート。

## 任意（Low・やってよい）

- infra のバンドリングコマンドで `__pycache__` を除外（`cp` 後に `find /asset-output -name __pycache__ -type d -exec rm -rf {} +` 等 — アセットハッシュの無用な揺れ防止）
- `lambda/reviews/index.py` の `get_public_reviews` ページ充填ループに最大反復回数（例: 10）を追加
- `_attach_whiskey_details` の `ConsistentRead=True` を False に（強整合が必要なのは存在確認と公開再確認のみ）

## 変更対象

`infra/lib/whiskey-infra-stack.ts` / `infra/test/infra.test.ts` / （任意分のみ）`lambda/reviews/index.py`。それ以外は変更しない。

## 検証

`cd infra && npx tsc --noEmit && npx jest && npx cdk synth -c env=dev > /dev/null` + `python -m pytest tests/` 全緑。

## してはならないこと

Lambda の認証・契約ロジック変更 / 他ステートメント・レイヤー定義・環境変数の変更 / コミット作成。
