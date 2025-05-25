export interface EnvironmentConfig {
  region: string;
  account?: string;
  domain?: string;
  certificateArn?: string;
  allowedOrigins: string[];
  natGateways: number;
  retainResources: boolean;
}

export const environments: Record<string, EnvironmentConfig> = {
  dev: {
    region: 'ap-northeast-1',
    domain: 'dev.whiskeybar.site',
    allowedOrigins: ['https://dev.whiskeybar.site', 'http://localhost:3000'], // 開発環境では本番ドメインとローカル
    natGateways: 1,
    retainResources: false,
  },
  prod: {
    region: 'ap-northeast-1',
    domain: 'whiskeybar.site',
    allowedOrigins: ['https://whiskeybar.site'], // 本番ドメインのみ許可
    natGateways: 2,
    retainResources: true,
    // certificateArn: 'arn:aws:acm:ap-northeast-1:123456789012:certificate/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx',
  },
}; 