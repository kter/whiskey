# Task 18: 可用性アラームの追加（本番稼働に伴う監視の穴埋め）

## 背景

2026-07-26 に prd 本番（`https://whiskeybar.site`）が稼働開始した。
現在の `infra/lib/observability-stack.ts` が持つアラームは3件のみで、いずれも**費用防御寄り**だ。

- `whiskey-{env}-tmp-post-requests-high`（S3 画像アップロードの多発）
- `whiskey-{env}-logs-get-requests-high`（S3 画像取得の多発）
- `whiskey-{env}-drink-log-reconciler-errors`（リコンサイラの失敗）

**可用性の監視が存在しない。** API が 5xx を返し続けても、Lambda が失敗し続けても、
DynamoDB がスロットルしても、誰も気づけない。

さらに重要な事情として、**prd アカウントの Lambda 同時実行上限は 10**（絶対最低値）で、
8つの関数がこの枠を奪い合う。同時実行枯渇による `Throttles` は現実的に起こりうる
最有力の障害モードだが、これも監視されていない。

## スコープ

**コード・テストのみ。AWS へのデプロイは行わない。**

## 実装要件

### A. `ObservabilityStack` に監視対象を渡せるようにする

現在 `ObservabilityStackProps` は `imagesBucketName` と `reconcilerFunctionName` しか受け取らない。
以下を追加する。

- `restApiName: string` — API Gateway の REST API 名
- `lambdaFunctionNames: string[]` — 監視対象の全 Lambda 関数名
- `tableNames: string[]` — 監視対象の全 DynamoDB テーブル名

`infra/lib/whiskey-infra-stack.ts` は既に `imagesBucketName` /
`drinkLogReconcilerFunctionName` を public に公開している。同じ流儀で
上記3つを公開するプロパティを追加し、`infra/lib/app-builder.ts` から渡すこと。
既存の公開プロパティの名前・型は変更しない。

### B. 追加するアラーム

すべて `whiskey-{env}-<名前>` の命名規則に従い、既存3件と同じ SNS トピックへ通知する。
`treatMissingData` は原則 `NOT_BREACHING`（トラフィックのない環境で誤発報させない）。

1. **`api-5xx-high`** — API Gateway のサーバ側障害
   - namespace `AWS/ApiGateway`、metricName `5XXError`、dimension `ApiName: props.restApiName`
   - statistic `Sum`、period 5分、threshold `5`、evaluationPeriods `1`

2. **`lambda-errors-high`** — 関数の失敗
   - namespace `AWS/Lambda`、metricName `Errors`、statistic `Sum`、period 5分
   - **関数ごとに個別のアラームを作る**（どの関数が落ちたか通知で判別できるようにするため）
   - alarmName は `whiskey-{env}-lambda-errors-{関数の短縮名}` とする。
     関数名から `-{env}` サフィックスを除いた部分を短縮名に使うこと
   - threshold `3`、evaluationPeriods `1`

3. **`lambda-throttles`** — 同時実行枯渇（**prd の上限が 10 のため最重要**）
   - namespace `AWS/Lambda`、metricName `Throttles`、statistic `Sum`、period 5分
   - こちらは**全関数を合算した単一のアラーム**でよい（枠の奪い合いは全体現象のため）。
     `cloudwatch.MathExpression` で各関数の Throttles を合算するか、
     関数ディメンションなしのアカウント全体メトリクスを使うか、いずれか適切な方を選ぶこと。
     選んだ理由を報告に含めること
   - threshold `1`、evaluationPeriods `1`（1件でも出たら知らせる）

4. **`dynamodb-throttles`** — テーブルのスロットル
   - namespace `AWS/DynamoDB`、metricName `ThrottledRequests`、statistic `Sum`、period 5分
   - dimension `TableName` でテーブルごとに個別のアラーム
   - alarmName は `whiskey-{env}-dynamodb-throttles-{テーブルの短縮名}`
   - threshold `1`、evaluationPeriods `1`
   - **注意**: `ThrottledRequests` が対象テーブルで利用可能か確認すること。
     PAY_PER_REQUEST テーブルで意味のあるメトリクスを選ぶこと（必要なら
     `ReadThrottleEvents` / `WriteThrottleEvents` に変更してよい。変更した場合は理由を報告）

### C. アラーム数の上限に配慮する

CloudWatch アラームは1件あたり月額課金が発生する。関数8つ・テーブル4つで
個別アラームを作ると合計が増える。**現在の構成で何件になるか**を算出し、報告に含めること。
20件を超える場合は、Lambda Errors を関数ごとではなく合算に変更することを提案してよい
（実装は変えず、提案のみ報告する）。

### D. テスト（`infra/test/infra.test.ts`）

- `ObservabilityStack` を新 props で合成し、以下を assert する
  - `api-5xx-high` アラームが1件存在し、`ApiName` ディメンションが正しいこと
  - Lambda Errors アラームが渡した関数の数だけ存在すること
  - Lambda Throttles アラームが1件存在すること
  - DynamoDB スロットルアラームが渡したテーブルの数だけ存在すること
  - **全アラームに SNS アクションが付いていること**（1つでも通知先のないアラームがあってはならない）
- 既存3件のアラームが引き続き生成されることも確認する
- `app-builder.ts` 経由の配線テスト（Task 17 で追加済み）に、
  `WhiskeyObservability-Prd` へ関数名・テーブル名・API 名が渡っていることの検証を足す

## 保持すべきもの

- 既存3アラームの `alarmName` と閾値（変更しない）
- 「AppState の原子カウンタが費用の上限を担い、アラームは通知のみ」というコメントの趣旨
- lookup-free の維持（`fromLookup` 禁止）
- 依存パッケージの追加・更新は禁止

## 受入条件（すべて実行して結果を報告すること）

```bash
cd infra
npx tsc --noEmit
npm test
npm run synth:dev
npm run synth:prd
```

- すべて成功すること
- `cdk.out/WhiskeyObservability-Prd.template.json` から
  **生成されたアラーム名の一覧**を抽出して報告に含めること
- 各アラームに `AlarmActions` が設定されていることを合成結果で確認して報告すること

## 報告してほしいこと

- 変更したファイルと各変更の意図
- Lambda Throttles を合算する方式として何を選んだか、およびその理由
- DynamoDB のメトリクスに何を選んだか（`ThrottledRequests` のままか変更したか）とその理由
- 生成されるアラームの総件数と、20件を超える場合の削減提案
- 上記コマンドの実行結果
