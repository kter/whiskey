# Task 01: CDK スタックのセキュリティ修正・スタック分割・最小権限化

## Goal

`infra/` の CDK コードに存在する重大なセキュリティ欠陥（removalPolicy の恒偽条件、API 全ルート認証なし、CORS 全開放ほか）を修正し、DNS/OIDC/通知の独立スタックを新設し、関数別最小権限ロールへ分割する。**このタスクは infra のみが対象。Lambda 本体・フロントエンドは変更しない**（対になる変更は後続タスク02/04が担当）。

## 背景（必読）

- 対象リポジトリはウイスキーレビューアプリ。AWS dev 環境は完全撤去済みで、これから再デプロイする。**既存 AWS リソースとの互換は考慮不要 — 全リソースが新規作成される**。
- 環境キーは `dev` / `prd`（`infra/bin/infra.ts:15` のエラーメッセージ参照）。**`'prod'` という環境名は存在しない**。
- prd の AWS アカウントは未確定。**今回の受入は dev × フラグ全組合せ + prd（フラグなし）の synth まで**。prd × カスタムドメインの組合せ・prd 用 OIDC は受入対象外。
- 実装判断に迷ったら、このファイルの指示を優先し、勝手にスコープを広げないこと。

## 変更対象

- `infra/lib/whiskey-infra-stack.ts`（主対象）
- `infra/lib/certificate-stack.ts`（fromLookup 廃止、DNS スタックからゾーンを受け取る）
- 新規 `infra/lib/dns-stack.ts` / `infra/lib/github-oidc-stack.ts` / `infra/lib/notifications-stack.ts`
- `infra/bin/infra.ts`（スタック構成・crossRegionReferences）
- `infra/config/environments.ts`（設定スキーマ拡張）
- `infra/scripts/deploy.sh` + `infra/package.json`（対象指定・ガード）
- `infra/test/infra.test.ts`（+ 必要なら分割）
- `infra/cdk.context.json`（古い削除済みゾーンのキャッシュを削除）

## 要求仕様

### 1. removalPolicy の恒偽条件修正（最重要バグ）
- `environment === 'prod'` の比較が **全7箇所**（stack.ts:66, 82, 155, 176, 184, 238 + ログ保持 :313）にあり、環境キーは 'prd' のため**永久に false** → 本番含む全ステートフルリソースが DESTROY になっている。
- すべて `envConfig.retainResources`（environments.ts に定義済み・現在未使用）ベースに置換。受入 grep: `=== 'prod'` の残存ゼロ。
- 非 retain 環境のバケットには `autoDeleteObjects: true` を追加（DESTROY でも非空バケットは削除失敗するため）。
- 全バケットに `enforceSSL: true`（presigned URL は bearer credential であり平文 HTTP を拒否する）。

### 2. 環境設定スキーマの拡張（environments.ts）
```ts
interface EnvironmentConfig {
  // 既存フィールドは維持
  account: string;              // dev: '031921999648'。prd は未確定のため空文字 + synth 時に custom domain 系を無効化
  enableCustomDomain: boolean;  // デフォルト false（Phase 3 で true にコミット）
  enableGoogleAuth: boolean;    // デフォルト false
  createOidcProvider: boolean;  // OIDC プロバイダを create するか import するか
  cognitoDomainPrefix: string;  // dev: 'whiskey-users-dev'（取得不能時に変更できるよう設定化）
  gatewayErrorOrigin: string;   // GatewayResponse 用静的オリジン。dev 初期値 'http://localhost:3000'
  retainResources: boolean;     // 既存
  allowedOrigins: string[];     // 既存
}
```
- **フラグは CLI context ではなく設定ファイルで永続化**（CLI `-c` は上書き手段としてのみ許可）。理由: deploy.sh は `-c env` しか渡さないため、揮発フラグだと通常デプロイでドメイン/IdP が剥がされる。

### 3. スタック分割（bin/infra.ts）
デプロイ順: `WhiskeyDns` → `WhiskeyGithubOidc` → 証明書 → `WhiskeyApp-{Dev,Prd}` → 通知。
- **`WhiskeyDns`（環境非依存シングルトン、ap-northeast-1）**: `whiskeybar.site` の PublicHostedZone（登録ドメインのゾーン。dev.whiskeybar.site ではない）。RemovalPolicy.RETAIN + `terminationProtection: true`。ゾーンID/NS 4件を CfnOutput。**アカウント 031921999648 固定 + スタック内で expected-account アサーション**。prd synth のテンプレートに `AWS::Route53::HostedZone` が含まれないことをテスト。
- **`WhiskeyGithubOidc`（シングルトン、terminationProtection: true）**: GitHub OIDC プロバイダ（`createOidcProvider` 設定で create/import 分岐）+ **CI ロールをこのスタックが所有**（旧アプリスタックからロール定義を移動）。trust は `repo:kter/whiskey:environment:dev` の StringEquals **のみ**（sub は environment 形式。prd は対象外）。ロール権限: 配信バケット S3 sync 相当（List/Get/Put/Delete — `grantReadWrite` が Delete を含むことを合成テンプレートで assert、重複 grant はしない）+ CloudFront invalidation + CloudFormation 読み取りのみ。**現行の `UpdateFunctionCode`/`UpdateFunctionConfiguration`（stack.ts:558-572）は削除**。
- **証明書スタック（certificate-stack.ts 改修）**: `fromLookup` 全廃。DNS スタックの `IHostedZone` を props で受け取る。us-east-1 は CloudFront 用のみ。**API Gateway 用証明書は ap-northeast-1 発行 + RestApi を `endpointTypes: [REGIONAL]` に明示**（デフォルト EDGE のままだと東京証明書でカスタムドメイン作成が失敗する）。RestApi/DomainName 両方を CDK テストで固定。
- **通知スタック2つ**: `WhiskeyNotifications`（us-east-1: SNS + `budgets.amazonaws.com` の sns:Publish を SourceAccount/SourceArn 条件で制限した TopicPolicy + AWS Budgets）と `WhiskeyNotifications-Tokyo`（ap-northeast-1: CloudWatch アラーム用トピック + alarm principal の TopicPolicy）。受信メールは SSM パラメータ `/whiskey/notifications/email` から（`valueForStringParameter` — `valueFromLookup` 禁止）。**アプリスタックからは参照しない**（SSM 未作成でもベースデプロイが通る独立性を維持）。
- 関与する全スタック（producer/consumer 双方）に `crossRegionReferences: true` を明示。

### 4. API Gateway の認証・CORS・防御
- `CognitoUserPoolsAuthorizer` を作成し、書き込み系（POST/PUT/DELETE reviews）+ 個人データ系 GET（collection GET /api/reviews）に装着。公開読み取り（whiskeys 系 + /api/reviews/public）は NONE のまま。
- **エスケープハッチで基底 `AWS::ApiGateway::Authorizer` の `identityValidationExpression` にクライアントIDの正確な正規表現を設定**（COGNITO_USER_POOLS 型では aud と照合される。CDK テストで assert）。
- ルート変更: `GET /api/reviews` の `?public=true` 分岐は廃止（公開一覧は `/api/reviews/public` に集約 — Lambda 側はタスク02）。**所有者用 `GET /api/reviews/{id}` と `DELETE /api/reviews/{id}` のルートを追加**（現行は PUT のみ）。
- preflight CORS: `Cors.ALL_ORIGINS` → `envConfig.allowedOrigins`。`-c extraAllowedOrigins` context を追加オリジンとして受け付ける。
- **GatewayResponse（UNAUTHORIZED / ACCESS_DENIED / DEFAULT_4XX / DEFAULT_5XX）に CORS ヘッダー**: `Access-Control-Allow-Origin` は **`envConfig.gatewayErrorOrigin` の静的1値のみ**（Origin ヘッダーの反射マッピングは禁止 — 任意オリジン反射になる）。
- `dataTraceEnabled: false`。
- メソッドスロットリング: 公開 scan 系（search/ranking/list/suggest）に保守的レート（rate 5 rps / burst 10 目安）、レビュー POST にも低レート（rate 1 rps / burst 5）。
- RestApi の統合タイムアウトはデフォルト 29 秒を明示維持（延長しない。CDK テストで固定）。

### 5. Cognito
- `USER_PASSWORD_AUTH` を無効化（SRP + OAuth code flow のみ）。
- `preventUserExistenceErrors: true`。
- prd のコールバック/ログアウト URL から `localhost:3000` を除去（`allowedOrigins` から導出）。
- Google IdP は `enableGoogleAuth` でゲート。**`supportedIdentityProviders` と IdP リソース・依存関係をセットでゲート**（IdP だけゲートしてクライアントに GOOGLE が残ると CloudFormation エラー）。
- Google クライアントID: SSM StringParameter `/whiskey/{env}/google-client-id` を `valueForStringParameter` で参照（`unsafeUnwrap` 廃止）。Secrets Manager にはクライアントシークレットのみ。
- Hosted UI ドメイン: `envConfig.cognitoDomainPrefix` から。CfnOutput: `CognitoHostedUiHostname`（**scheme なしの裸ホスト名** — テストで scheme 不在を assert）と `GoogleAuthorizedRedirectUri`（`https://<domain>/oauth2/idpresponse` の完全 URL）を**別出力**で。

### 6. IAM 最小権限（関数別ロール）
現行の単一共有ロール（stack.ts:321-352）を関数別に分割:
- whiskeys-list: WhiskeySearch 読み取り + AppState scan カウンタ prefix の `UpdateItem` のみ（`dynamodb:LeadingKeys` + `Null:false` 条件）
- whiskeys-search: WhiskeySearch + Reviews 読み取り + AppState ランキングキャッシュ prefix `GetItem` のみ + scan カウンタ prefix `UpdateItem` のみ
- reviews: Reviews RW + WhiskeySearch 読み取り + AppState カウンタ prefix `UpdateItem`
- **未使用の Cognito Admin 系権限（AdminDeleteUser 等）は、Lambda コードに使用箇所が無いことを grep 確認の上、削除**
- 負のテスト: search が ランキング prefix へ Put/Update できないこと、list が WhiskeySearch へ書けないこと

### 7. その他
- **`AppState-{env}` テーブル新設**: PK `pk`（文字列）、`timeToLiveAttribute: 'ttl'`、PAY_PER_REQUEST、removalPolicy は retainResources 準拠。
- **Users テーブルは作成しない**（廃止決定 — どの API も実体を読まないため。現行定義 stack.ts:171 は削除）。
- **Reviews テーブル**: GSI `UserDateIndex` は維持。**`WhiskeyIndex` は定義しない**（利用者なし）。**疎 GSI `PublicDateIndex`（PK `public_pk`、SK `date`）を追加**。
- **未使用 VPC を削除**（stack.ts:38, 617 — どのリソースからも参照されていない。関連出力ごと）。
- ロググループ: 各 Function に専用 logGroup（名前 `/whiskey/{env}/{function}` — 旧デプロイの残存デフォルトグループとの AlreadyExists 衝突回避）、保持は retainResources ベース。
- CloudFront: `www.` エイリアス（Route53 レコード + aliases）は廃止（正規オリジン1本化）。ResponseHeadersPolicy を追加: HSTS / X-Content-Type-Options / frame-ancestors 'none' / Referrer-Policy strict-origin-when-cross-origin（**CSP はここに入れない** — コンテンツ依存 CSP はフロントのビルド時 meta が担当）。
- Lambda パッケージングは現状の素の `Code.fromAsset` を**このタスクでは維持**（バンドリング変更はタスク02）。
- 既存出力 `ApiGatewayUrl` を正式契約として維持（重複出力を作らない）。
- Places 用シークレット `whiskey-places-{env}` の参照定義（`fromSecretNameV2` — 作成はユーザー作業）。
- `infra/cdk.context.json` から削除済みゾーンの lookup キャッシュを除去。

### 8. deploy.sh / npm scripts
- 対象指定必須化: `--dns` / `--oidc` / `--cert` / `--base` / `--notifications` / `--observability`（将来用に受け付けのみ）/ `--frontend`（スタブ: 後続タスクで実装、未実装なら明示エラー）。
- 環境ごとの期待アカウント検証: `sts get-caller-identity` の Account が `envConfig.account` と不一致なら中断。全 aws/cdk コマンドに明示 profile。
- **DNS / OIDC スタックの destroy はスクリプトで明示拒否**。
- CDK ブートストラップ検査: ap-northeast-1 / us-east-1 双方で SSM `/cdk-bootstrap/hnb659fds/version` の存在と版数を確認、不足時のみ `cdk bootstrap`。
- SSM 存在検査は `--notifications` 選択時のみ。

## 受入条件

1. `cd infra && npm ci && npx tsc --noEmit` 成功
2. `npx cdk synth -c env=dev`（フラグ全組合せ: enableCustomDomain/enableGoogleAuth の true/false 全4通り、config を一時変更してテストする形でよい）+ `npx cdk synth -c env=prd`（フラグなし）が **AWS 認証情報・lookup なしで**成功
3. `npx jest` 全緑。テストに含めること:
   - removalPolicy が retainResources に従う（dev: Delete, prd: Retain）
   - `=== 'prod'` の残存ゼロ（ソース grep）
   - autoDeleteObjects / enforceSSL / versioned:false
   - オーソライザーが対象メソッドに装着され、公開ルートは NONE
   - identityValidationExpression が設定されている
   - GatewayResponse の静的オリジン
   - 関数別ロールの正/負テスト（LeadingKeys 条件含む）
   - prd テンプレートに HostedZone なし / Users テーブルなし / WhiskeyIndex なし / VPC なし
   - logGroup 名が `/whiskey/{env}/...` 形式
   - Cognito: USER_PASSWORD_AUTH 無効・preventUserExistenceErrors・prd に localhost なし
   - CfnOutput: CognitoHostedUiHostname に scheme なし
   - RestApi REGIONAL + 統合タイムアウト既定
4. Lambda / frontend のファイルは一切変更していない（git diff で確認される）

## 検証コマンド

```bash
cd infra && npm ci && npx tsc --noEmit && npx jest && npx cdk synth -c env=dev > /dev/null && npx cdk synth -c env=prd > /dev/null
grep -rn "=== 'prod'" lib/ bin/ config/ || echo OK
```

## してはならないこと

- Lambda 本体（`lambda/`）、フロントエンド（`frontend/`）、CI（`.github/`）の変更
- 実 AWS へのデプロイ・アクセス（synth はローカル完結）
- 依存パッケージの追加（aws-cdk-lib 既存版で完結すること）
- `.gitignore` の変更、コミットの作成
