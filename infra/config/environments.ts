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
    analyze?: number;
    places?: number;
  };
}

export const environments: Record<string, EnvironmentConfig> = {
  dev: {
    region: 'ap-northeast-1',
    account: '031921999648',
    domain: 'dev.whiskeybar.site',
    apiDomain: 'api.dev.whiskeybar.site',
    enableCustomDomain: false,
    enableGoogleAuth: false,
    createOidcProvider: true,
    cognitoDomainPrefix: 'whiskey-users-dev',
    gatewayErrorOrigin: 'http://localhost:3000',
    retainResources: false,
    allowedOrigins: ['https://dev.whiskeybar.site', 'http://localhost:3000'],
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
