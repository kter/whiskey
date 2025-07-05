#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { WhiskeyInfraStack } from '../lib/whiskey-infra-stack';
import { CertificateStack } from '../lib/certificate-stack';
import { environments } from '../config/environments';

const app = new cdk.App();

// 環境変数から環境を取得（デフォルトはdev）
const env = app.node.tryGetContext('env') || process.env.ENV || 'dev';

// 環境設定を取得
const envConfig = environments[env];
if (!envConfig) {
  throw new Error(`Invalid environment: ${env}. Must be 'dev' or 'prd'.`);
}

// 共通の環境設定
const account = process.env.CDK_DEFAULT_ACCOUNT;
const region = envConfig.region;
const envCapitalized = env.charAt(0).toUpperCase() + env.slice(1);

// 1. CloudFront用証明書スタック（us-east-1）を先に作成
let certificateStack: CertificateStack | undefined;
if (envConfig.domain) {
  certificateStack = new CertificateStack(app, `WhiskeyCertificate-${envCapitalized}`, {
    env: { account, region: 'us-east-1' },
    environment: env,
    domain: envConfig.domain,
    // Hosted Zone IDは後でlookupできるので、一旦ドメイン名のみで作成
    hostedZoneId: '', // 空文字の場合はlookupを使用
    hostedZoneName: envConfig.domain,
    tags: {
      Project: 'WhiskeyApp',
      Environment: env
    }
  });
}

// 2. メインスタック（証明書スタックの出力を参照）
const mainStack = new WhiskeyInfraStack(app, `WhiskeyApp-${envCapitalized}`, {
  env: { account, region },
  environment: env,
  cloudFrontCertificateArn: certificateStack?.certificate.certificateArn,
  crossRegionReferences: true, // クロスリージョン参照を有効化
  tags: {
    Project: 'WhiskeyApp',
    Environment: env
  }
});

// 依存関係を設定（証明書スタックが先に作成される）
if (certificateStack) {
  mainStack.addDependency(certificateStack);
}