#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { environments } from '../config/environments';
import { CertificateStack } from '../lib/certificate-stack';
import { DNS_ACCOUNT, DnsStack } from '../lib/dns-stack';
import { GithubOidcStack } from '../lib/github-oidc-stack';
import { NotificationsStack } from '../lib/notifications-stack';
import { ObservabilityStack } from '../lib/observability-stack';
import { WhiskeyInfraStack } from '../lib/whiskey-infra-stack';

function contextBoolean(app: cdk.App, key: string, fallback: boolean): boolean {
  const value = app.node.tryGetContext(key);
  if (value === undefined) {
    return fallback;
  }
  if (value === true || value === 'true') {
    return true;
  }
  if (value === false || value === 'false') {
    return false;
  }
  throw new Error(`Context ${key} must be true or false.`);
}

const app = new cdk.App();
const environment = app.node.tryGetContext('env') || process.env.ENV || 'dev';
const envConfig = environments[environment];
if (!envConfig) {
  throw new Error(`Invalid environment: ${environment}. Must be 'dev' or 'prd'.`);
}

const account = envConfig.account || undefined;
const environmentName = environment.charAt(0).toUpperCase() + environment.slice(1);
const enableCustomDomain = Boolean(account)
  && contextBoolean(app, 'enableCustomDomain', envConfig.enableCustomDomain);
const enableGoogleAuth = contextBoolean(app, 'enableGoogleAuth', envConfig.enableGoogleAuth);
const createOidcProvider = contextBoolean(app, 'createOidcProvider', envConfig.createOidcProvider);
const tags = { Project: 'WhiskeyApp', Environment: environment };

let dnsStack: DnsStack | undefined;
let oidcStack: GithubOidcStack | undefined;
if (environment === 'dev') {
  dnsStack = new DnsStack(app, 'WhiskeyDns', {
    env: { account: DNS_ACCOUNT, region: 'ap-northeast-1' },
    crossRegionReferences: true,
    terminationProtection: true,
    tags: { Project: 'WhiskeyApp', Environment: 'shared' },
  });

  oidcStack = new GithubOidcStack(app, 'WhiskeyGithubOidc', {
    env: { account: DNS_ACCOUNT, region: 'ap-northeast-1' },
    crossRegionReferences: true,
    terminationProtection: true,
    createOidcProvider,
    deploymentBucketName: `whiskey-webapp-dev-${DNS_ACCOUNT}`,
    tags: { Project: 'WhiskeyApp', Environment: 'shared' },
  });
  oidcStack.addDependency(dnsStack);
}

let certificateStack: CertificateStack | undefined;
if (enableCustomDomain && dnsStack && envConfig.domain) {
  certificateStack = new CertificateStack(app, `WhiskeyCertificate-${environmentName}`, {
    env: { account, region: 'us-east-1' },
    crossRegionReferences: true,
    domain: envConfig.domain,
    hostedZone: dnsStack.hostedZone,
    tags,
  });
  certificateStack.addDependency(oidcStack ?? dnsStack);
}

const appStack = new WhiskeyInfraStack(app, `WhiskeyApp-${environmentName}`, {
  env: { account, region: envConfig.region },
  crossRegionReferences: true,
  environment,
  enableCustomDomain,
  enableGoogleAuth,
  hostedZone: enableCustomDomain ? dnsStack?.hostedZone : undefined,
  cloudFrontCertificateArn: certificateStack?.certificate.certificateArn,
  tags,
});
if (certificateStack) {
  appStack.addDependency(certificateStack);
} else if (oidcStack) {
  appStack.addDependency(oidcStack);
}

const budgetNotifications = new NotificationsStack(app, 'WhiskeyNotifications', {
  env: { account, region: 'us-east-1' },
  crossRegionReferences: true,
  kind: 'budget',
  tags,
});

const tokyoNotifications = new NotificationsStack(app, 'WhiskeyNotifications-Tokyo', {
  env: { account, region: 'ap-northeast-1' },
  crossRegionReferences: true,
  kind: 'alarms',
  tags,
});
tokyoNotifications.addDependency(budgetNotifications);
appStack.addDependency(tokyoNotifications);

const observabilityStack = new ObservabilityStack(app, `WhiskeyObservability-${environmentName}`, {
  env: { account, region: 'ap-northeast-1' },
  crossRegionReferences: true,
  environment,
  notificationTopicArn: tokyoNotifications.topic.topicArn,
  imagesBucketName: appStack.imagesBucketName,
  reconcilerFunctionName: appStack.drinkLogReconcilerFunctionName,
  tags,
});
observabilityStack.addDependency(appStack);
observabilityStack.addDependency(tokyoNotifications);
