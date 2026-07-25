# Task 17: DNS ゾーン移行の運用安全化（Task 16 のレビュー指摘対応）

## 背景

Task 16（コミット `7347f81`）で DNS ゾーン所有を環境ごとに分離した。実装自体は仕様どおりで
`tsc --noEmit` / jest 44件 / `synth:dev` / `synth:prd` はすべて通っている。
独立レビューの結果 **Critical はゼロ**だったが、Important な指摘が4件出た。
本タスクはその対応と、実移行を進めるうえで判明した `deploy.sh` の機能欠落を埋める。

**prd 側の apex ゾーンは既にデプロイ済み**（2026-07-26 実施）:
- HostedZone: `whiskeybar.site` / `Z06424363NJD2XHZPOF0J`（prd アカウント 401731371959）
- 委任ロール: `arn:aws:iam::401731371959:role/WhiskeyDnsDelegationRole`
- レジストラ（お名前.com）の NS は **まだ切り替えていない**。現在の権威は dev アカウントの旧 apex ゾーン `Z08969091QY06OFQT6YRF`。

## スコープ

**コード・テスト・ドキュメントのみ。AWS へのデプロイ、レジストラ操作、Secrets 作成は一切行わない。**

## 実装要件

### A. `infra/scripts/deploy.sh` に CDK context の受け渡しを追加（最優先）

現在 `CDK_CONTEXT` は `-c "env=$ENVIRONMENT" --profile "$PROFILE"` に固定されており、
`enableCustomDomain` や `enableZoneDelegation` といった **既に実装済みの context フラグを
deploy.sh 経由で渡す手段が存在しない**。移行手順がこれらのフラグに依存するため、これは実運用上のブロッカー。

- 新オプション **`-c KEY=VALUE` / `--context KEY=VALUE`** を追加し、複数回指定できるようにする。
  受け取った値は `CDK_CONTEXT` 配列に `-c KEY=VALUE` として追記する。
- `env=` を上書きする指定（`-c env=...`）は **エラーで拒否**すること。環境はサブコマンド第1引数が正典であり、
  ここが二重管理になるとアカウント検証ガードを迂回できてしまう。
- `KEY=VALUE` の形式でない引数（`=` を含まない）はエラーにする。
- `show_usage` に新オプションを追記する。
- 既存のオプション解析ループの構造・他のガード（`--destroy` と `--dns`/`--oidc` の併用禁止、
  prd での `--oidc` 拒否、アカウント検証）は**一切変更しない**。

### B. `bin/infra.ts` の配線に対する合成テストを追加（`infra/test/infra.test.ts`）

現在 `bin/infra.ts` の検証はソース文字列の `toContain` のみで、env 別の配線が壊れても 44 テストは緑のまま通る。
削除されたアカウント固定バリデーションの穴が埋まっていない。

実装方針は次のどちらでもよい。**どちらを選んだか報告すること。**
- (a) `npx cdk synth -c env=<env> --output <tmpdir>` を `execFileSync` で実行して生成物を検証する
- (b) `bin/infra.ts` のスタック組み立てを `infra/lib/app-builder.ts`（新規）の純関数へ切り出し、
  `bin/infra.ts` は薄いエントリポイントにする。テストからは `cdk.App` を渡して直接呼ぶ

(a) は合成コストが重いので、`describe` スコープで env ごとに1回だけ合成して使い回すこと。
CI 時間が過度に伸びる場合は (b) を選ぶこと。

検証内容:
- **`env=prd`**: `WhiskeyDns` に `RoleName: WhiskeyDnsDelegationRole` の `AWS::IAM::Role` が1件、
  信頼ポリシーに dev アカウント `031921999648` が含まれる。`Custom::CrossAccountZoneDelegation` は **0件**。
  HostedZone の `Name` が `whiskeybar.site.`。manifest に `WhiskeyCertificate-Prd` と `WhiskeyApp-Prd` が存在する。
- **`env=dev`**: `WhiskeyDns` に `Custom::CrossAccountZoneDelegation` が1件、`AssumeRoleArn` が
  prd アカウントの `WhiskeyDnsDelegationRole`。`RoleName: WhiskeyDnsDelegationRole` の IAM Role は **0件**。
  HostedZone の `Name` が `dev.whiskeybar.site.`。
- `delegationTargetAccounts` の設定を意図的に外すと prd のテストが落ちることを**手元で一度確認し、その結果を報告に含めること**。

### C. prd カスタムドメイン有効状態の app スタックテストを追加

既存の `'prd without feature flags synthesizes without lookups'` は `enableCustomDomain: true` に
なった新実態を検証していない。

- `createAppStack('prd', { customDomain: true })` 相当のテストを追加し、
  CloudFront の `Aliases` が `['whiskeybar.site']`、`AWS::ApiGateway::DomainName` の
  `DomainName` が `api.whiskeybar.site` であることを assert する。
- 既存テストは残してよいが、テスト名を実態に合わせて調整すること。
- `expect(environments.dev.parentZone?.account).toBe(environments.prd.account)` を追加する。
- `TEST_PRD_ACCOUNT` を `PRD_ACCOUNT` にリネームする（実アカウント ID を指すようになり名前が誤解を招くため）。

### D. `infra/README.md` のランブック更新

CLAUDE.md が `infra/README.md` を正典ランブックと定めている。現状は Task 16 の変更が未反映で、
知らずに操作すると DNS 断や CloudFormation ロールバックを起こす。

- targets 表の `--dns` 行を更新: 「環境ごとの HostedZone。prd = apex `whiskeybar.site`
  （+ dev への委任ロール `WhiskeyDnsDelegationRole`）、dev = 子ゾーン `dev.whiskeybar.site`（apex へ NS 委任）」
- 「prd はスコープ外」の記述を、DNS とアプリスタックについては prd がスコープ内になった旨へ更新する。
  `WhiskeyDns` を destroy しない禁則はそのまま維持。
- 新オプション `-c KEY=VALUE`（A で追加）を「段階投入フラグ」相当の節に追記する。
  `enableCustomDomain` / `enableZoneDelegation` / `enableGoogleAuth` / `createOidcProvider` が
  **`environments.ts` の既定値を CLI から上書きする context フラグ**であること、
  `enableZoneDelegation` の既定が `true` であることを明記する。
- **新セクション「DNS ゾーン所有の移行手順（apex を prd へ）」** を追加し、以下の順序を明記する。
  prd apex は既にデプロイ済みなので、その事実を前提に書くこと。

  1. prd `--dns` をデプロイし apex ゾーンと委任ロールを作る（**完了済み**: `Z06424363NJD2XHZPOF0J`）。
     この時点ではレジストラをまだ切り替えない。
  2. dev の `WhiskeyApp-Dev` が `WhiskeyDns` の HostedZone export を import しているため、
     ゾーン置換の前に **import を外す**。`deploy.sh dev --cert --base -c enableCustomDomain=false` を実行する。
     この間 `dev.whiskeybar.site` / `api.dev.whiskeybar.site` は**停止する**。
  3. `deploy.sh dev --dns` を実行し、旧 apex ゾーンを子ゾーン `dev.whiskeybar.site` に置換する。
     旧 apex ゾーンは `RemovalPolicy.RETAIN` により dev アカウントに孤児として残り、
     **レジストラがまだ指しているため権威であり続ける**。
  4. **旧 apex ゾーン（`Z08969091QY06OFQT6YRF`）に手動で `dev.whiskeybar.site` の NS レコードを追加**し、
     手順3で作られた子ゾーンの NS 4本を指す。これで旧 apex 権威のまま dev の解決先が子ゾーンへ移り、
     次手順の ACM 検証が公開 DNS から見えるようになる。**この手順を飛ばすと ACM 検証が
     永久に完了せず CloudFormation がタイムアウトする。**
  5. `deploy.sh dev --cert --base` を実行し（context フラグなし = カスタムドメイン再有効化）、
     証明書と A レコードを子ゾーンに作り直す。dev が復旧する。
  6. 旧 apex ゾーンに他にレコードがあれば prd apex へ移送し、
     **お名前.com の NS を prd apex の4本へ切り替える**。
  7. TTL 経過（最低48時間）を確認してから旧 apex ゾーンを手動削除する。

- 「既知の危険」節を設け、以下を明記する:
  - dev の HostedZone は名前変更＝**置換**であり、`WhiskeyDns:ExportsOutputRefHostedZoneDB99F866...`
    を `WhiskeyApp-Dev` が import しているため、import を外さずに `deploy.sh dev --dns` を打つと
    「使用中 export の値変更」で失敗する。
  - `WhiskeyCertificate-Dev` の `Certificate` と `WhiskeyApp-Dev` の `ApiCertificate` は
    `DomainValidationOptions` 変更で**置換**され、委任が公開 DNS に出るまで検証待ちでハングする。
  - 旧 apex ゾーンは RETAIN で残り課金される。削除タイミングを明記する。

### E. `infra/lib/dns-stack.ts` に受容リスクのコメントを追加

`grantDelegation` 呼び出しの直上に、次の趣旨のコメントを残す。

- 付与される権限は apex ゾーン**全体**に対する NS レコードの `UPSERT` / `DELETE` であり、
  Route53 の IAM にはレコード名を絞る条件キーが存在しない。
- `AccountPrincipal` は dev アカウント全体を信頼するため、dev で `sts:AssumeRole` を持つ
  任意のプリンシパルが `whiskeybar.site` 配下の任意の名前の NS レコードを書き換えられる。
- 将来的に custom resource Lambda の実ロール ARN（`ArnPrincipal`）へ絞る余地がある。
  初回デプロイ前に絞ると chicken-and-egg になるため、**このタスクでは `assumedBy` の実装は変更しない**。

### F. 軽微なクリーンアップ

- `EnvironmentConfig` に `delegationTargetAccounts?: string[]` を追加し、prd に `['031921999648']` を設定。
  `bin/infra.ts` の `environment === 'prd' ? [DNS_ACCOUNT] : undefined` を
  `envConfig.delegationTargetAccounts` に置き換える（`parentZone` が config 駆動なのと対称にする）。
  **合成結果が現在と一致すること**を確認すること。
- `contextBoolean` が `bin/infra.ts` と `lib/dns-stack.ts` に完全重複している。
  `infra/lib/context.ts`（新規）へ切り出して両方から import する。挙動は完全に同一に保つこと。
- `bin/infra.ts` の `Boolean(account) &&` は `account: string` が両 env で必ず非空になった今デッドコード。
  `envConfig` 読み込み直後に `if (!envConfig.account) throw new Error(...)` の明示チェックを入れ、
  `Boolean(account) &&` は削除する。
- 未使用になった `ROOT_DOMAIN` export を削除する。**`DNS_ACCOUNT` export は
  `GithubOidcStack` が使うため必ず残すこと。**

## 保持すべきもの（絶対に変更しない）

- `DNS_ACCOUNT` の export と `GithubOidcStack` の dev アカウント固定・`WhiskeyDns` への依存
- `deploy.sh` の `--destroy` + `--dns`/`--oidc` 併用禁止ガード
- `deploy.sh` のアカウント検証（`sts get-caller-identity` と `environments.ts` の突合）
- `RemovalPolicy.RETAIN` と `terminationProtection: true`
- `HostedZoneId` / `NameServer1..4` / `DelegationRoleArn` の CfnOutput 論理 ID
- `roleName: 'WhiskeyDnsDelegationRole'` の固定（dev 側が lookup なしで ARN を組み立てるため）
- `prd.enableGoogleAuth: false` と `prd.lambdaReservedConcurrency` 未設定
- lookup-free の維持（`fromLookup` 禁止、`cdk.context.json` を生成しない）
- 依存パッケージの追加・更新は禁止

## 受入条件（すべて実行して結果を報告すること）

```bash
cd infra
npx tsc --noEmit
npm test
npm run synth:dev
npm run synth:prd
npx cdk synth -c env=dev -c enableZoneDelegation=false WhiskeyDns
bash -n scripts/deploy.sh
```

- すべて成功すること
- 最後から2番目のコマンドで `Custom::CrossAccountZoneDelegation` が**出力されない**ことを目視確認して報告する
- `deploy.sh` の新 `-c` オプションについて、次を実際に確認して報告する:
  - `bash scripts/deploy.sh dev --base -c env=prd --diff-only` が **エラー終了**する（env 上書き拒否）
  - `bash scripts/deploy.sh dev --base -c badformat --diff-only` が **エラー終了**する（形式不正）
  - （AWS 認証が必要な箇所まで到達しない範囲での確認でよい。到達してしまう場合はその旨を報告する）
- B のテストが実際に配線を検証していること（`delegationTargetAccounts` を外すと落ちる）を確認した結果

## 報告してほしいこと

- 変更したファイルと各変更の意図
- B で (a) と (b) のどちらの方式を選んだか、およびその理由
- 上記コマンドの実行結果
- F の `delegationTargetAccounts` 移動で合成結果に差分が出ていないことの確認方法と結果
