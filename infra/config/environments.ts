export interface EnvironmentConfig {
  region: string;
  account: string;
  hostedZoneName: string;
  parentZone?: {
    account: string;
    zoneName: string;
  };
  delegationTargetAccounts?: string[];
  domain?: string;
  apiDomain?: string;
  certificateArn?: string;
  enableCustomDomain: boolean;
  enableGoogleAuth: boolean;
  createOidcProvider: boolean;
  cognitoDomainPrefix: string;
  gatewayErrorOrigin: string;
  retainResources: boolean;
  allowedOrigins: string[];
  lambdaReservedConcurrency?: {
    drinkLogs?: number;
    analyze?: number;
    places?: number;
    reconciler?: number;
  };
}

export const environments: Record<string, EnvironmentConfig> = {
  dev: {
    region: 'ap-northeast-1',
    account: '031921999648',
    hostedZoneName: 'dev.whiskeybar.site',
    parentZone: {
      account: '401731371959',
      zoneName: 'whiskeybar.site',
    },
    domain: 'dev.whiskeybar.site',
    apiDomain: 'api.dev.whiskeybar.site',
    enableCustomDomain: true,
    enableGoogleAuth: true,
    // 2026-07-20 実確認: token.actions.githubusercontent.com プロバイダはアカウントに残存 → import 分岐
    createOidcProvider: false,
    cognitoDomainPrefix: 'whiskey-users-dev',
    gatewayErrorOrigin: 'https://dev.whiskeybar.site',
    retainResources: false,
    allowedOrigins: ['https://dev.whiskeybar.site', 'http://localhost:3000'],
    // 2026-07-21: このアカウントの Lambda 同時実行上限は 10（絶対最低値）で、
    // 予約並列度を 1 でも設定すると未予約枠が 10 を割り拒否される。
    // よって D14 層② の予約並列度は無効化（費用の硬い上限は AppState 原子カウンタ
    // ＋ API GW メソッドスロットリングが担うため保証は不変）。
    // 同時実行クォータ引き上げ後に再付与推奨:
    // lambdaReservedConcurrency: { analyze: 2, places: 3, reconciler: 1 },
  },
  prd: {
    region: 'ap-northeast-1',
    account: '401731371959',
    hostedZoneName: 'whiskeybar.site',
    delegationTargetAccounts: ['031921999648'],
    domain: 'whiskeybar.site',
    apiDomain: 'api.whiskeybar.site',
    enableCustomDomain: true,
    // 2026-07-26 有効化。GCP プロジェクト whiskey-app-prd の OAuth クライアントを使う。
    // 前提: SSM /whiskey/prd/google-client-id と Secrets Manager whiskey-app-secrets-prd
    // （キーは GOOGLE_CLIENT_SECRET）。Google 側の承認済みリダイレクト URI は
    // https://whiskey-users-prd.auth.ap-northeast-1.amazoncognito.com/oauth2/idpresponse
    enableGoogleAuth: true,
    createOidcProvider: false,
    cognitoDomainPrefix: 'whiskey-users-prd',
    gatewayErrorOrigin: 'https://whiskeybar.site',
    retainResources: true,
    allowedOrigins: ['https://whiskeybar.site'],
    // 2026-07-26: このアカウントの Lambda 同時実行上限も 10（絶対最低値）で、
    // 予約並列度を設定すると未予約枠が 10 を割り拒否されるため付与しない。
    // 同時実行クォータ引き上げ後に再付与推奨:
    // lambdaReservedConcurrency: { analyze: 2, places: 3 },
  },
};
