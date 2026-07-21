export interface EnvironmentConfig {
  region: string;
  account: string;
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
    aggregator?: number;
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
    // The production account is intentionally unset until it is finalized.
    account: '',
    domain: 'whiskeybar.site',
    apiDomain: 'api.whiskeybar.site',
    enableCustomDomain: false,
    enableGoogleAuth: false,
    createOidcProvider: false,
    cognitoDomainPrefix: 'whiskey-users-prd',
    gatewayErrorOrigin: 'https://whiskeybar.site',
    retainResources: true,
    allowedOrigins: ['https://whiskeybar.site'],
    // Recommended after the production account's Lambda concurrency quota is raised:
    // lambdaReservedConcurrency: { aggregator: 1, analyze: 2, places: 3 },
  },
};
