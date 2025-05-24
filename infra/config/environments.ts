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
    allowedOrigins: ['*'], // 開発環境では全て許可
    natGateways: 1,
    retainResources: false,
  },
  prod: {
    region: 'ap-northeast-1',
    domain: 'your-domain.com', // 本番ドメインに変更
    allowedOrigins: ['https://your-domain.com'], // 本番ドメインのみ許可
    natGateways: 2,
    retainResources: true,
    // certificateArn: 'arn:aws:acm:ap-northeast-1:123456789012:certificate/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx',
  },
}; 