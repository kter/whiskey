import * as cdk from 'aws-cdk-lib';
import { environments } from '../config/environments';
import { CertificateStack } from './certificate-stack';
import { contextBoolean } from './context';
import { DNS_ACCOUNT, DnsStack } from './dns-stack';
import { GithubOidcStack } from './github-oidc-stack';
import { NotificationsStack } from './notifications-stack';
import { ObservabilityStack } from './observability-stack';
import { WhiskeyInfraStack } from './whiskey-infra-stack';

export interface AppStacks {
  dnsStack: DnsStack;
  oidcStack?: GithubOidcStack;
  certificateStack?: CertificateStack;
  appStack: WhiskeyInfraStack;
  budgetNotifications: NotificationsStack;
  tokyoNotifications: NotificationsStack;
  observabilityStack: ObservabilityStack;
}

export function buildApp(app: cdk.App): AppStacks {
  const environment = app.node.tryGetContext('env') || process.env.ENV || 'dev';
  const envConfig = environments[environment];
  if (!envConfig) {
    throw new Error(`Invalid environment: ${environment}. Must be 'dev' or 'prd'.`);
  }
  if (!envConfig.account) {
    throw new Error(`Account for environment ${environment} must be configured.`);
  }

  const account = envConfig.account;
  const environmentName = environment.charAt(0).toUpperCase() + environment.slice(1);
  const enableCustomDomain = contextBoolean(
    app,
    'enableCustomDomain',
    envConfig.enableCustomDomain,
  );
  const enableGoogleAuth = contextBoolean(app, 'enableGoogleAuth', envConfig.enableGoogleAuth);
  const createOidcProvider = contextBoolean(app, 'createOidcProvider', envConfig.createOidcProvider);
  const tags = { Project: 'WhiskeyApp', Environment: environment };

  const dnsStack = new DnsStack(app, 'WhiskeyDns', {
    env: { account, region: envConfig.region },
    crossRegionReferences: true,
    terminationProtection: true,
    zoneName: envConfig.hostedZoneName,
    delegationTargetAccounts: envConfig.delegationTargetAccounts,
    parentZone: envConfig.parentZone,
    tags,
  });

  let oidcStack: GithubOidcStack | undefined;
  if (environment === 'dev') {
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
  if (enableCustomDomain && envConfig.domain) {
    certificateStack = new CertificateStack(app, `WhiskeyCertificate-${environmentName}`, {
      env: { account, region: 'us-east-1' },
      crossRegionReferences: true,
      domain: envConfig.domain,
      hostedZone: dnsStack.hostedZone,
      tags,
    });
    certificateStack.addDependency(dnsStack);
  }

  const appStack = new WhiskeyInfraStack(app, `WhiskeyApp-${environmentName}`, {
    env: { account, region: envConfig.region },
    crossRegionReferences: true,
    environment,
    enableCustomDomain,
    enableGoogleAuth,
    hostedZone: enableCustomDomain ? dnsStack.hostedZone : undefined,
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

  const observabilityStack = new ObservabilityStack(
    app,
    `WhiskeyObservability-${environmentName}`,
    {
      env: { account, region: 'ap-northeast-1' },
      crossRegionReferences: true,
      environment,
      notificationTopicArn: tokyoNotifications.topic.topicArn,
      imagesBucketName: appStack.imagesBucketName,
      reconcilerFunctionName: appStack.drinkLogReconcilerFunctionName,
      restApiName: appStack.restApiName,
      lambdaFunctionNames: appStack.lambdaFunctionNames,
      tableNames: appStack.tableNames,
      tags,
    },
  );
  observabilityStack.addDependency(appStack);
  observabilityStack.addDependency(tokyoNotifications);

  return {
    dnsStack,
    oidcStack,
    certificateStack,
    appStack,
    budgetNotifications,
    tokyoNotifications,
    observabilityStack,
  };
}
