# Task 16: DNS ゾーン所有を環境ごとに分離し、prd のカスタムドメインを成立させる

## 背景

現状、`whiskeybar.site` の Route53 PublicHostedZone は **dev アカウント (031921999648)** が
`WhiskeyDns` スタックで単独所有している。`DnsStack` はアカウントを `DNS_ACCOUNT` に
ハード固定しており、`bin/infra.ts` も `environment === 'dev'` のときしか `DnsStack` を
生成しない。`CertificateStack` はその `dnsStack.hostedZone` に依存するため、

- prd では `DnsStack` が存在しない → `CertificateStack` も生成されない
- 結果として prd の `enableCustomDomain` は構造的に成立しない（`config/environments.ts` で
  `false` に固定されているのはこの制約の反映）

本番を `whiskeybar.site` で立ち上げるため、**apex ゾーンを prd アカウントが所有し、
dev は `dev.whiskeybar.site` の子ゾーンを所有して apex から NS 委任を受ける**構成へ移行する。

ドメインは Route53 Domains 登録ではなく **外部レジストラ（お名前.com）** 管理のため、
レジストラ側の NS 切替は人手で行う。コード側は「apex を prd が持ち、dev 子ゾーンへ委任する」
形を表現できればよい。

## スコープ

**このタスクはコード変更とテストのみ。AWS へのデプロイ・レジストラ操作・Secrets 作成は一切行わない。**

## 対象アカウント

- dev: `031921999648`
- prd: `401731371959`

## 実装要件

### 1. `infra/config/environments.ts`

- `prd.account` を `'401731371959'` に設定する（現在は空文字）。
- `prd.enableCustomDomain` を `true` にする。
- `EnvironmentConfig` に **`hostedZoneName: string`** を追加する。
  - dev: `'dev.whiskeybar.site'`
  - prd: `'whiskeybar.site'`
- `EnvironmentConfig` に **`parentZone?: { account: string; zoneName: string }`** を追加する。
  - dev: `{ account: '401731371959', zoneName: 'whiskeybar.site' }`
  - prd: 未設定（apex 自身なので親はいない）
- `prd.enableGoogleAuth` は **`false` のまま変更しない**（Google OAuth クライアント未整備のため、
  別タスクで扱う）。
- `prd.lambdaReservedConcurrency` は **付与しない**。prd アカウントの Lambda 同時実行上限は
  実測 **10**（dev と同じ絶対最低値）で、予約並列度を設定すると未予約枠が 10 を割って拒否される。
  既存のコメントを prd 用にも同趣旨で残すこと。

### 2. `infra/lib/dns-stack.ts`

- `DNS_ACCOUNT` の **エクスポートは残す**（`bin/infra.ts` の `GithubOidcStack` が
  dev アカウント固定の singleton として使い続けるため）。ただし `DnsStack` 内の
  「`this.account !== DNS_ACCOUNT` なら throw」というアカウント固定バリデーションは**削除**する。
- `ROOT_DOMAIN` は apex を指す定数として残してよいが、ゾーン名は props 由来にする。
- `DnsStackProps extends cdk.StackProps` を新設し、以下を受け取る:
  - `zoneName: string` — このスタックが所有するゾーン名
  - `delegationTargetAccounts?: string[]` — 指定時、このゾーンに対する
    cross-account 委任を許可する IAM ロールを作成する（apex = prd 用）
  - `parentZone?: { account: string; zoneName: string }` — 指定時、親ゾーンへ
    自ゾーンの NS 委任レコードを作成する（子ゾーン = dev 用）
- ゾーン作成は従来どおり `route53.PublicHostedZone` + `RemovalPolicy.RETAIN`。
- **委任ロール（親側 / prd）**: `delegationTargetAccounts` が空でないとき、
  `iam.Role` を **固定のロール名 `WhiskeyDnsDelegationRole`** で作成し、
  `assumedBy` は各アカウントの `iam.AccountPrincipal` を束ねた `iam.CompositePrincipal`。
  `hostedZone.grantDelegation(role)` を呼ぶ。ロール ARN を `CfnOutput`（論理ID `DelegationRoleArn`）で出力する。
  ロール名を固定するのは、子スタック側が lookup なしで ARN を組み立てられるようにするため。
- **委任レコード（子側 / dev）**: `parentZone` が指定されたとき、
  `route53.CrossAccountZoneDelegationRecord` を作成する。
  - `delegatedZone`: 自ゾーン
  - `parentHostedZoneName`: `parentZone.zoneName`
  - `delegationRole`: `iam.Role.fromRoleArn(this, 'ParentDelegationRole',
    \`arn:aws:iam::${parentZone.account}:role/WhiskeyDnsDelegationRole\`)`
  - この委任レコード生成は **context フラグ `enableZoneDelegation` で無効化できる**こと
    （既定 `true`）。親ゾーン側のロールがまだ存在しない初回デプロイで
    `-c enableZoneDelegation=false` を渡して回避できるようにする。
    フラグ解釈は `bin/infra.ts` の `contextBoolean` と同じ真偽値規約に合わせる。
- 既存の `HostedZoneId` / `NameServer1..4` の `CfnOutput` は維持する。

### 3. `infra/bin/infra.ts`

- `DnsStack` を **環境ごとに生成**する。`environment === 'dev'` ガードを外し、
  `env: { account, region: envConfig.region }`、`zoneName: envConfig.hostedZoneName`、
  `parentZone: envConfig.parentZone` を渡す。
  prd では `delegationTargetAccounts: [DNS_ACCOUNT]`（dev アカウント）を渡す。
  `terminationProtection: true` は維持。
- `GithubOidcStack` は **dev のみ・`DNS_ACCOUNT` 固定のまま**維持する
  （CI がフロントを配るのは dev だけのため）。`dnsStack` への依存関係もそのまま。
- `CertificateStack` の生成条件から `dnsStack` の dev 限定という前提を外し、
  `enableCustomDomain && envConfig.domain` が真なら生成する。`hostedZone` には
  その環境の `dnsStack.hostedZone` を渡す。
- `appStack` に渡す `hostedZone` も同様にその環境の `dnsStack.hostedZone` とする。
- スタック依存関係（cert → dns、app → cert）は現行の意図を保つこと。
- prd で `oidcStack` が `undefined` になることによる依存解決の分岐漏れがないこと。

### 4. `infra/scripts/deploy.sh`

- 78 行目付近の「prd では `--dns` と `--oidc` を拒否する」ガードを、
  **`--oidc` のみ prd 拒否**に変更する。`--dns` は prd でも許可する。
  エラーメッセージも実態に合わせて更新すること。
- 70 行目付近の `--destroy` と `--dns`/`--oidc` の併用禁止はそのまま維持する。
- `STACKS` の組み立て（148 行目付近）は現行のままでよいが、prd で `--dns` を選んだとき
  `WhiskeyDns` が正しく対象に入ることを確認すること。

### 5. `infra/test/infra.test.ts`

既存の `'DNS owns the root zone, retains it, and rejects the wrong account'` テストは
アカウント固定バリデーションの削除に伴い成立しなくなる。以下に置き換え・追加する。

- **prd apex ゾーン**: prd アカウント・`zoneName: 'whiskeybar.site'`・
  `delegationTargetAccounts: [DNS_ACCOUNT]` で合成すると、
  - `AWS::Route53::HostedZone` の `Name` が `whiskeybar.site.`、`DeletionPolicy` が `Retain`
  - `AWS::IAM::Role` が 1 つ作られ、`RoleName` が `WhiskeyDnsDelegationRole`、
    信頼ポリシーに dev アカウントが含まれる
  - Outputs に `HostedZoneId`, `NameServer1..4`, `DelegationRoleArn` が揃う
- **dev 子ゾーン**: dev アカウント・`zoneName: 'dev.whiskeybar.site'`・
  `parentZone: { account: <prd>, zoneName: 'whiskeybar.site' }` で合成すると、
  - HostedZone の `Name` が `dev.whiskeybar.site.`
  - `Custom::CrossAccountZoneDelegation` リソースが 1 つ存在し、
    `ParentZoneName` が `whiskeybar.site`、`DelegationRoleArn` に prd アカウントIDが含まれる
- **委任の無効化**: 同じ dev 構成に context `enableZoneDelegation=false` を与えると
  `Custom::CrossAccountZoneDelegation` が 0 件になる
- 既存の `'certificate consumes an injected hosted zone without lookup'` テストは維持する
  （必要なら zoneName を実態に合わせて調整）。
- 他の既存テストで `DNS_ACCOUNT` の throw 挙動や `prd.account === ''` を前提にしている箇所が
  あれば、新しい設定値に合わせて修正すること。`TEST_PRD_ACCOUNT` 定数の扱いに注意。

## 制約

- 依存パッケージの追加・更新は禁止。`aws-cdk-lib` 2.196.0 に
  `CrossAccountZoneDelegationRecord` / `PublicHostedZone.grantDelegation` は存在することを確認済み。
- 既存の Lambda コード・フロントエンドには手を入れない。
- `cdk.context.json` を生成するような `fromLookup` 系 API は使わない（lookup-free を維持）。
- 秘密情報をコードに埋め込まない。

## 受入条件（すべて実行して結果を報告すること）

```bash
cd infra
npm ci
npx tsc --noEmit
npm test
npm run synth:dev
npm run synth:prd
```

- `npx tsc --noEmit` がエラーなし
- `npm test`（jest）が全緑
- `npm run synth:dev` と **`npm run synth:prd` の両方**が成功すること。
  現状 `synth:prd` は `prd.account` が空のため env-agnostic 合成になっているが、
  本変更後はアカウント確定済みで合成が通る必要がある。
- 合成結果で以下を目視確認し、報告に含めること:
  - prd の `WhiskeyDns` に HostedZone `whiskeybar.site` と `WhiskeyDnsDelegationRole` がある
  - prd に `WhiskeyCertificate-Prd` が生成される
  - prd の `WhiskeyApp-Prd` に CloudFront の `Aliases: [whiskeybar.site]` と
    API のカスタムドメイン `api.whiskeybar.site` が現れる
  - dev の `WhiskeyDns` に HostedZone `dev.whiskeybar.site` と
    `Custom::CrossAccountZoneDelegation` がある

## 報告してほしいこと

- 変更したファイルと各変更の意図
- 上記コマンドの実行結果
- dev のゾーン名変更（`whiskeybar.site` → `dev.whiskeybar.site`）が
  CloudFormation 上で HostedZone の **置換**になるかどうかの見解
- 実装中に気づいた、デプロイ順序上の危険（特に dev の名前解決断）
