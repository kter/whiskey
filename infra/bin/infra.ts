#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { WhiskeyInfraStack } from '../lib/whiskey-infra-stack';

const app = new cdk.App();

// 環境変数から環境を取得（デフォルトはdev）
const env = app.node.tryGetContext('env') || process.env.ENV || 'dev';

// 環境ごとのスタック設定
const stackConfig = {
  dev: {
    stackName: 'WhiskeyApp-Dev',
    env: { 
      account: process.env.CDK_DEFAULT_ACCOUNT, 
      region: process.env.CDK_DEFAULT_REGION || 'ap-northeast-1' 
    }
  },
  prod: {
    stackName: 'WhiskeyApp-Prod',
    env: { 
      account: process.env.CDK_DEFAULT_ACCOUNT, 
      region: process.env.CDK_DEFAULT_REGION || 'ap-northeast-1' 
    }
  }
};

const config = stackConfig[env as keyof typeof stackConfig];
if (!config) {
  throw new Error(`Invalid environment: ${env}. Must be 'dev' or 'prod'.`);
}

new WhiskeyInfraStack(app, config.stackName, {
  env: config.env,
  environment: env,
  tags: {
    Project: 'WhiskeyApp',
    Environment: env
  }
});