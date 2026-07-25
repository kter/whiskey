# Task 01b: WhiskeyNotifications — Budget/TopicPolicy 依存関係の修正 + 小型ハードニング

対象: `infra/lib/notifications-stack.ts`、`infra/scripts/deploy.sh`（1点のみ）、`infra/test/infra.test.ts`。他ファイルは変更しない。

## 1.（必須・Medium）CfnBudget が TopicPolicy に依存していない

問題: `notifications-stack.ts:41` の `CfnBudget` は Topic の Ref にしか依存せず、`addToResourcePolicy`（:29-39）で作られる TopicPolicy への DependsOn がない（合成テンプレートで確認済み）。AWS Budgets は作成時にトピックの publish 権限を検証するため、初回デプロイが間欠的に失敗する。

修正: `this.topic.addToResourcePolicy(...)` の戻り値 `AddToResourcePolicyResult` を受け取り、`budget.node.addDependency(result.policyDependable!)` で TopicPolicy の後に CfnBudget が作成されることを保証する。

## 2.（推奨・Low）alarms トピックの confused-deputy 条件

`notifications-stack.ts:63-67` の `cloudwatch.amazonaws.com` への `sns:Publish` 許可に条件を追加:
`StringEquals: { 'aws:SourceAccount': this.account }` + `ArnLike: { 'aws:SourceArn': arn:aws:cloudwatch:*:{account}:alarm:* }`

## 3.（推奨・Low）`--observability` をエラーでなく no-op 受理に

`deploy.sh:75-78` は exit 2 している — 「後続タスクで実装予定。現時点では対象なし」の警告を出して正常終了（exit 0）に変更（`--frontend` の明示エラーは維持）。

## 4.（推奨・Low）テストの浅い箇所の補強

- `infra.test.ts:194` 付近: `IdentityValidationExpression` の Ref が **UserPoolClient の論理ID** を指すことまで assert
- list ロールの負テスト: `UpdateItem` ステートメントの `Resource` が AppState テーブル ARN であることも assert
- notifications テスト: **CfnBudget が TopicPolicy への DependsOn を持つ** assert を追加（項目1の回帰防止）
- enforceSSL の assert を prd テンプレートにも追加

## 受入条件

`cd infra && npx tsc --noEmit && npx jest && npx cdk synth -c env=dev > /dev/null && npx cdk synth -c env=prd > /dev/null` すべて成功。

## してはならないこと

上記以外のファイル変更・既存プロパティ（トピック/サブスクリプション/予算値・SSM 参照・budget 側の条件）の変更・コミット作成。
