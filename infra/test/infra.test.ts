import * as fs from 'fs';
import * as path from 'path';
import * as cdk from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import * as route53 from 'aws-cdk-lib/aws-route53';
import { environments } from '../config/environments';
import { CertificateStack } from '../lib/certificate-stack';
import { DNS_ACCOUNT, DnsStack } from '../lib/dns-stack';
import { GithubOidcStack } from '../lib/github-oidc-stack';
import { NotificationsStack } from '../lib/notifications-stack';
import { WhiskeyInfraStack } from '../lib/whiskey-infra-stack';

type Resource = {
  Type: string;
  Properties?: Record<string, any>;
  DependsOn?: string | string[];
  DeletionPolicy?: string;
  UpdateReplacePolicy?: string;
};

type Synthesized = {
  Resources: Record<string, Resource>;
  Outputs?: Record<string, { Value: any }>;
};

const DEV_ACCOUNT = '031921999648';
const TEST_PRD_ACCOUNT = '111111111111';

function createAppStack(
  environment: 'dev' | 'prd',
  options: { customDomain?: boolean; googleAuth?: boolean; extraOrigins?: string } = {},
): { stack: WhiskeyInfraStack; template: Template; json: Synthesized; outdir: string } {
  const app = new cdk.App({
    context: options.extraOrigins ? { extraAllowedOrigins: options.extraOrigins } : undefined,
  });
  const account = environment === 'dev' ? DEV_ACCOUNT : TEST_PRD_ACCOUNT;
  let hostedZone: route53.IHostedZone | undefined;
  if (options.customDomain) {
    const producer = new cdk.Stack(app, `ZoneProducer-${environment}`, {
      env: { account, region: 'ap-northeast-1' },
    });
    hostedZone = route53.HostedZone.fromHostedZoneAttributes(producer, 'ImportedZone', {
      hostedZoneId: 'Z1234567890',
      zoneName: 'whiskeybar.site',
    });
  }
  const stack = new WhiskeyInfraStack(app, `App-${environment}-${options.customDomain}-${options.googleAuth}`, {
    env: { account, region: 'ap-northeast-1' },
    environment,
    enableCustomDomain: options.customDomain ?? false,
    enableGoogleAuth: options.googleAuth ?? false,
    hostedZone,
    cloudFrontCertificateArn: options.customDomain
      ? `arn:aws:acm:us-east-1:${account}:certificate/test-certificate`
      : undefined,
  });
  const template = Template.fromStack(stack);
  return { stack, template, json: template.toJSON() as Synthesized, outdir: app.outdir };
}

function resourcesOf(json: Synthesized, type: string): Array<[string, Resource]> {
  return Object.entries(json.Resources).filter(([, resource]) => resource.Type === type);
}

function apiMethods(json: Synthesized): Record<string, Resource['Properties']> {
  const apiResources = new Map<string, { parent?: string; part: string }>();
  for (const [logicalId, resource] of resourcesOf(json, 'AWS::ApiGateway::Resource')) {
    const parentId = resource.Properties?.ParentId?.Ref as string | undefined;
    apiResources.set(logicalId, { parent: parentId, part: resource.Properties?.PathPart as string });
  }

  const resourcePath = (logicalId: string): string => {
    const resource = apiResources.get(logicalId);
    if (!resource) {
      return '';
    }
    return `${resource.parent ? resourcePath(resource.parent) : ''}/${resource.part}`;
  };

  const methods: Record<string, Resource['Properties']> = {};
  for (const [, method] of resourcesOf(json, 'AWS::ApiGateway::Method')) {
    const properties = method.Properties;
    if (properties?.HttpMethod === 'OPTIONS' || !properties?.ResourceId?.Ref) {
      continue;
    }
    methods[`${properties.HttpMethod} ${resourcePath(properties.ResourceId.Ref)}`] = properties;
  }
  return methods;
}

function actions(statement: Record<string, any>): string[] {
  return Array.isArray(statement.Action) ? statement.Action : [statement.Action];
}

function rolePolicy(json: Synthesized, roleName: string): Record<string, any>[] {
  const roleEntry = resourcesOf(json, 'AWS::IAM::Role').find(([, role]) => role.Properties?.RoleName === roleName);
  expect(roleEntry).toBeDefined();
  const roleLogicalId = roleEntry![0];
  const policy = resourcesOf(json, 'AWS::IAM::Policy').find(([, candidate]) =>
    (candidate.Properties?.Roles ?? []).some((role: { Ref?: string }) => role.Ref === roleLogicalId));
  expect(policy).toBeDefined();
  return policy![1].Properties?.PolicyDocument.Statement as Record<string, any>[];
}

describe('stateful resource lifecycle and storage security', () => {
  test('dev deletes and prd retains stateful resources', () => {
    const dev = createAppStack('dev').json;
    const prd = createAppStack('prd').json;

    for (const type of ['AWS::S3::Bucket', 'AWS::DynamoDB::Table', 'AWS::Cognito::UserPool', 'AWS::Logs::LogGroup']) {
      for (const [, resource] of resourcesOf(dev, type)) {
        expect(resource.DeletionPolicy).toBe('Delete');
        expect(resource.UpdateReplacePolicy).toBe('Delete');
      }
      for (const [, resource] of resourcesOf(prd, type)) {
        expect(resource.DeletionPolicy).toBe('Retain');
        expect(resource.UpdateReplacePolicy).toBe('Retain');
      }
    }
  });

  test('all buckets are unversioned, SSL-only, and dev buckets auto-delete objects', () => {
    const { template, json } = createAppStack('dev');
    expect(resourcesOf(json, 'AWS::S3::Bucket')).toHaveLength(2);
    for (const [, bucket] of resourcesOf(json, 'AWS::S3::Bucket')) {
      expect(bucket.Properties?.VersioningConfiguration).toBeUndefined();
      expect(bucket.Properties?.Tags).toContainEqual({ Key: 'aws-cdk:auto-delete-objects', Value: 'true' });
    }
    template.resourceCountIs('Custom::S3AutoDeleteObjects', 2);
    template.hasResourceProperties('AWS::S3::BucketPolicy', {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Effect: 'Deny',
            Action: 's3:*',
            Condition: { Bool: { 'aws:SecureTransport': 'false' } },
          }),
        ]),
      },
    });
    const policies = resourcesOf(json, 'AWS::S3::BucketPolicy');
    expect(policies).toHaveLength(2);
    for (const [, policy] of policies) {
      const statements = policy.Properties?.PolicyDocument.Statement as Record<string, any>[];
      expect(statements.some((statement) => statement.Condition?.Bool?.['aws:SecureTransport'] === 'false')).toBe(true);
    }

    const prdPolicies = resourcesOf(createAppStack('prd').json, 'AWS::S3::BucketPolicy');
    expect(prdPolicies).toHaveLength(2);
    for (const [, policy] of prdPolicies) {
      const statements = policy.Properties?.PolicyDocument.Statement as Record<string, any>[];
      expect(statements.some((statement) => statement.Condition?.Bool?.['aws:SecureTransport'] === 'false')).toBe(true);
    }
  });

  test('source has no stale production comparison or lookup escape hatches', () => {
    const sourceDirs = ['lib', 'bin', 'config'].map((directory) => path.join(__dirname, '..', directory));
    const source = sourceDirs.flatMap((directory) =>
      fs.readdirSync(directory)
        .filter((file) => file.endsWith('.ts'))
        .map((file) => fs.readFileSync(path.join(directory, file), 'utf8'))).join('\n');
    expect(source).not.toContain("=== 'prod'");
    expect(source).not.toContain('fromLookup');
    expect(source).not.toContain('unsafeUnwrap');
    expect(source).not.toContain('Cors.ALL_ORIGINS');
  });
});

describe('API Gateway authentication, CORS, and defenses', () => {
  const authenticated = [
    'GET /api/reviews',
    'POST /api/reviews',
    'GET /api/reviews/{id}',
    'PUT /api/reviews/{id}',
    'DELETE /api/reviews/{id}',
  ];
  const publicRoutes = [
    'GET /api/whiskeys',
    'GET /api/whiskeys/search',
    'GET /api/whiskeys/suggest',
    'GET /api/whiskeys/search/suggest',
    'GET /api/whiskeys/ranking',
    'GET /api/reviews/public',
  ];

  test('private routes use Cognito and public routes remain unauthenticated', () => {
    const methods = apiMethods(createAppStack('dev').json);
    for (const route of authenticated) {
      expect(methods[route]?.AuthorizationType).toBe('COGNITO_USER_POOLS');
      expect(methods[route]?.AuthorizerId).toBeDefined();
    }
    for (const route of publicRoutes) {
      expect(methods[route]?.AuthorizationType).toBe('NONE');
      expect(methods[route]?.AuthorizerId).toBeUndefined();
    }
  });

  test('authorizer pins aud to the exact app client ID', () => {
    const { json } = createAppStack('dev');
    const userPoolClientLogicalId = resourcesOf(json, 'AWS::Cognito::UserPoolClient')[0][0];
    const authorizer = resourcesOf(json, 'AWS::ApiGateway::Authorizer')[0][1];
    expect(authorizer.Properties?.Type).toBe('COGNITO_USER_POOLS');
    expect(authorizer.Properties?.IdentityValidationExpression).toEqual({
      'Fn::Join': ['', ['^', { Ref: userPoolClientLogicalId }, '$']],
    });
  });

  test('gateway errors use one static origin and preflight accepts configured extras', () => {
    const { json } = createAppStack('dev', { extraOrigins: 'https://preview.example.com' });
    const responses = resourcesOf(json, 'AWS::ApiGateway::GatewayResponse');
    expect(responses).toHaveLength(4);
    for (const [, response] of responses) {
      expect(response.Properties?.ResponseParameters['gatewayresponse.header.Access-Control-Allow-Origin'])
        .toBe(`'${environments.dev.gatewayErrorOrigin}'`);
    }
    const serialized = JSON.stringify(json);
    expect(serialized).toContain('https://preview.example.com');
    expect(serialized).not.toContain('method.request.header.Origin');
  });

  test('API is regional, data tracing is disabled, throttles are fixed, and integrations stay at 29 seconds', () => {
    const { template, json } = createAppStack('dev');
    template.hasResourceProperties('AWS::ApiGateway::RestApi', {
      EndpointConfiguration: { Types: ['REGIONAL'] },
    });
    const stages = resourcesOf(json, 'AWS::ApiGateway::Stage');
    expect(stages).toHaveLength(1);
    const settings = stages[0][1].Properties?.MethodSettings as Record<string, any>[];
    expect(settings.every((setting) => setting.DataTraceEnabled === false)).toBe(true);
    expect(settings).toEqual(expect.arrayContaining([
      expect.objectContaining({ HttpMethod: 'GET', ThrottlingRateLimit: 5, ThrottlingBurstLimit: 10 }),
      expect.objectContaining({ HttpMethod: 'POST', ThrottlingRateLimit: 1, ThrottlingBurstLimit: 5 }),
    ]));
    const methods = Object.values(apiMethods(json));
    expect(methods).toHaveLength(authenticated.length + publicRoutes.length);
    expect(methods.every((method) => method?.Integration.TimeoutInMillis === 29000)).toBe(true);
  });

  test('custom-domain RestApi and DomainName are both regional', () => {
    const { template } = createAppStack('dev', { customDomain: true });
    template.hasResourceProperties('AWS::ApiGateway::RestApi', {
      EndpointConfiguration: { Types: ['REGIONAL'] },
    });
    template.hasResourceProperties('AWS::ApiGateway::DomainName', {
      EndpointConfiguration: { Types: ['REGIONAL'] },
      RegionalCertificateArn: Match.anyValue(),
    });
  });
});

describe('Cognito', () => {
  test('password auth is disabled, existence errors are hidden, and prd excludes localhost', () => {
    const { template, json } = createAppStack('prd');
    template.hasResourceProperties('AWS::Cognito::UserPoolClient', {
      ExplicitAuthFlows: Match.arrayWith(['ALLOW_USER_SRP_AUTH']),
      PreventUserExistenceErrors: 'ENABLED',
    });
    const client = resourcesOf(json, 'AWS::Cognito::UserPoolClient')[0][1];
    expect(client.Properties?.ExplicitAuthFlows).not.toContain('ALLOW_USER_PASSWORD_AUTH');
    expect(JSON.stringify(client.Properties?.CallbackURLs)).not.toContain('localhost');
    expect(JSON.stringify(client.Properties?.LogoutURLs)).not.toContain('localhost');
  });

  test('Google provider and client provider are gated together', () => {
    const disabled = createAppStack('dev', { googleAuth: false }).json;
    const enabled = createAppStack('dev', { googleAuth: true }).json;
    expect(resourcesOf(disabled, 'AWS::Cognito::UserPoolIdentityProvider')).toHaveLength(0);
    expect(resourcesOf(enabled, 'AWS::Cognito::UserPoolIdentityProvider')).toHaveLength(1);
    const disabledClient = resourcesOf(disabled, 'AWS::Cognito::UserPoolClient')[0][1];
    const enabledClient = resourcesOf(enabled, 'AWS::Cognito::UserPoolClient')[0][1];
    expect(disabledClient.Properties?.SupportedIdentityProviders).toEqual(['COGNITO']);
    expect(enabledClient.Properties?.SupportedIdentityProviders).toEqual(['COGNITO', 'Google']);
    expect(JSON.stringify(enabled)).toContain('AWS::SSM::Parameter::Value<String>');
    expect(JSON.stringify(enabled)).toContain('/whiskey/dev/google-client-id');
  });

  test('hosted UI hostname and Google redirect URI are separate outputs', () => {
    const { json } = createAppStack('dev');
    const hostname = json.Outputs?.CognitoHostedUiHostname.Value;
    expect(hostname).toBe('whiskey-users-dev.auth.ap-northeast-1.amazoncognito.com');
    expect(hostname).not.toMatch(/^https?:\/\//);
    expect(json.Outputs?.GoogleAuthorizedRedirectUri.Value)
      .toBe(`https://${hostname}/oauth2/idpresponse`);
  });
});

describe('least-privilege Lambda roles', () => {
  test('roles have only their positive DynamoDB grants and constrained AppState prefixes', () => {
    const json = createAppStack('dev').json;
    const list = rolePolicy(json, 'whiskey-list-role-dev');
    const search = rolePolicy(json, 'whiskey-search-role-dev');
    const reviews = rolePolicy(json, 'reviews-role-dev');
    const aggregator = rolePolicy(json, 'ranking-aggregator-role-dev');

    const listAppState = list.find((statement) => actions(statement).includes('dynamodb:UpdateItem'))!;
    const appStateTableLogicalId = resourcesOf(json, 'AWS::DynamoDB::Table')
      .find(([, table]) => table.Properties?.TableName === 'AppState-dev')![0];
    expect(listAppState.Resource).toEqual({ 'Fn::GetAtt': [appStateTableLogicalId, 'Arn'] });
    expect(listAppState.Condition).toEqual({
      'ForAllValues:StringLike': { 'dynamodb:LeadingKeys': ['scan-counter/*'] },
      Null: { 'dynamodb:LeadingKeys': 'false' },
    });
    expect(list.some((statement) => actions(statement).includes('dynamodb:Scan'))).toBe(true);
    expect(list.some((statement) => actions(statement).some((action) =>
      ['dynamodb:PutItem', 'dynamodb:DeleteItem'].includes(action)))).toBe(false);

    const rankingRead = search.find((statement) =>
      actions(statement).includes('dynamodb:GetItem')
      && statement.Condition?.['ForAllValues:StringLike']?.['dynamodb:LeadingKeys']?.includes('ranking-cache/*'));
    expect(rankingRead).toBeDefined();
    expect(search.some((statement) =>
      actions(statement).some((action) => ['dynamodb:PutItem', 'dynamodb:DeleteItem'].includes(action))
      || (actions(statement).includes('dynamodb:UpdateItem')
        && statement.Condition?.['ForAllValues:StringLike']?.['dynamodb:LeadingKeys']?.includes('ranking-cache/*'))))
      .toBe(false);

    expect(reviews.some((statement) => actions(statement).includes('dynamodb:PutItem'))).toBe(true);
    const reviewsAppStateUpdate = reviews.find((statement) =>
      actions(statement).includes('dynamodb:UpdateItem')
      && statement.Condition?.['ForAllValues:StringLike']?.['dynamodb:LeadingKeys']
        ?.includes('review-rate#*'));
    expect(reviewsAppStateUpdate?.Resource).toEqual({ 'Fn::GetAtt': [appStateTableLogicalId, 'Arn'] });
    expect(reviewsAppStateUpdate?.Condition).toEqual({
      'ForAllValues:StringLike': {
        'dynamodb:LeadingKeys': ['review-rate#*', 'review-change-counter'],
      },
      Null: { 'dynamodb:LeadingKeys': 'false' },
    });
    expect(JSON.stringify(resourcesOf(json, 'AWS::IAM::Policy'))).not.toContain('TransactWriteItems');
    expect(JSON.stringify([...list, ...search, ...reviews])).not.toContain('cognito-idp:Admin');

    const aggregatorScan = aggregator.find((statement) => actions(statement).includes('dynamodb:Scan'))!;
    expect(aggregatorScan.Resource).toHaveLength(2);
    const aggregatorCache = aggregator.find((statement) =>
      actions(statement).includes('dynamodb:PutItem'))!;
    expect(aggregatorCache.Condition['ForAllValues:StringLike']['dynamodb:LeadingKeys'])
      .toEqual(['ranking-cache/*']);
    const aggregatorCounters = aggregator.find((statement) =>
      actions(statement).includes('dynamodb:GetItem')
      && statement.Condition?.['ForAllValues:StringLike']?.['dynamodb:LeadingKeys']
        ?.includes('whiskey-change-counter'))!;
    expect(actions(aggregatorCounters)).toEqual(['dynamodb:GetItem']);
  });
});

describe('tables, logs, and removed infrastructure', () => {
  test('AppState and sparse public review index exist; retired resources do not', () => {
    const { template, json } = createAppStack('prd');
    template.hasResourceProperties('AWS::DynamoDB::Table', {
      TableName: 'AppState-prd',
      BillingMode: 'PAY_PER_REQUEST',
      KeySchema: [{ AttributeName: 'pk', KeyType: 'HASH' }],
      TimeToLiveSpecification: { AttributeName: 'ttl', Enabled: true },
    });
    const serialized = JSON.stringify(json);
    expect(serialized).toContain('PublicDateIndex');
    expect(serialized).toContain('UserDateIndex');
    expect(serialized).not.toContain('WhiskeyIndex');
    expect(serialized).not.toContain('DistilleryIndex');
    expect(serialized).not.toContain('Users-');
    template.resourceCountIs('AWS::EC2::VPC', 0);
    template.resourceCountIs('AWS::Route53::HostedZone', 0);
  });

  test('every function uses its dedicated /whiskey/{env}/ log group', () => {
    const { template } = createAppStack('dev');
    for (const name of ['whiskeys-list', 'whiskeys-search', 'reviews', 'ranking-aggregator']) {
      template.hasResourceProperties('AWS::Logs::LogGroup', {
        LogGroupName: `/whiskey/dev/${name}`,
      });
    }
  });
});

describe('Lambda bundling and shared layer', () => {
  test('all application functions are x86_64, use the shared layer, and receive shared settings', () => {
    const { json } = createAppStack('dev');
    const applicationFunctions = resourcesOf(json, 'AWS::Lambda::Function')
      .filter(([, resource]) => typeof resource.Properties?.FunctionName === 'string'
        && ['whiskey-list-dev', 'whiskey-search-dev', 'reviews-dev', 'ranking-aggregator-dev']
          .includes(resource.Properties.FunctionName));
    expect(applicationFunctions).toHaveLength(4);
    for (const [, fn] of applicationFunctions) {
      expect(fn.Properties?.Architectures).toEqual(['x86_64']);
      expect(fn.Properties?.Layers).toHaveLength(1);
      if (fn.Properties?.FunctionName !== 'ranking-aggregator-dev') {
        expect(fn.Properties?.Environment.Variables.ALLOWED_ORIGINS).toContain('https://dev.whiskeybar.site');
      }
    }
    const reviews = applicationFunctions.find(([, fn]) => fn.Properties?.FunctionName === 'reviews-dev')![1];
    expect(reviews.Properties?.Environment.Variables.COGNITO_CLIENT_ID).toEqual(expect.objectContaining({ Ref: expect.any(String) }));
    const list = applicationFunctions
      .find(([, fn]) => fn.Properties?.FunctionName === 'whiskey-list-dev')![1];
    expect(list.Properties?.Environment.Variables.PUBLIC_SCAN_MAX_PAGES).toBe('1');
    expect(list.Properties?.Environment.Variables.PUBLIC_SCAN_PAGE_SIZE).toBeUndefined();
    const search = applicationFunctions
      .find(([, fn]) => fn.Properties?.FunctionName === 'whiskey-search-dev')![1];
    expect(search.Properties?.Environment.Variables).toEqual(expect.objectContaining({
      PUBLIC_SCAN_MAX_PAGES: '5',
      PUBLIC_SCAN_PAGE_SIZE: '250',
    }));
    const aggregator = applicationFunctions
      .find(([, fn]) => fn.Properties?.FunctionName === 'ranking-aggregator-dev')![1];
    expect(aggregator.Properties).toEqual(expect.objectContaining({
      MemorySize: 512,
      Timeout: 120,
    }));
    expect(aggregator.Properties?.ReservedConcurrentExecutions).toBeUndefined();
    expect(resourcesOf(json, 'AWS::Lambda::LayerVersion')).toHaveLength(1);
  });

  test('aggregator reserved concurrency is added only when configured', () => {
    const previous = environments.dev.lambdaReservedConcurrency;
    environments.dev.lambdaReservedConcurrency = { aggregator: 2 };
    try {
      const aggregator = resourcesOf(createAppStack('dev').json, 'AWS::Lambda::Function')
        .find(([, fn]) => fn.Properties?.FunctionName === 'ranking-aggregator-dev')![1];
      expect(aggregator.Properties?.ReservedConcurrentExecutions).toBe(2);
    } finally {
      environments.dev.lambdaReservedConcurrency = previous;
    }
  });

  test('Docker bundling is pinned to amd64 and each bundled function asset contains index.py', () => {
    const source = fs.readFileSync(path.join(__dirname, '..', 'lib', 'whiskey-infra-stack.ts'), 'utf8');
    expect(source).toContain("platform: 'linux/amd64'");
    expect(source).toContain('pip install -r requirements.txt -t /asset-output');
    expect(source).toContain('cp -au . /asset-output');
    expect(source).toContain('find /asset-output -name __pycache__ -type d -exec rm -rf {} +');

    const { json, outdir } = createAppStack('dev');
    const applicationFunctions = resourcesOf(json, 'AWS::Lambda::Function')
      .filter(([, resource]) => typeof resource.Properties?.FunctionName === 'string'
        && ['whiskey-list-dev', 'whiskey-search-dev', 'reviews-dev', 'ranking-aggregator-dev']
          .includes(resource.Properties.FunctionName));
    for (const [, fn] of applicationFunctions) {
      const assetHash = JSON.stringify(fn.Properties?.Code).match(/[a-f0-9]{64}/)?.[0];
      expect(assetHash).toBeDefined();
      expect(fs.existsSync(path.join(outdir, `asset.${assetHash}`, 'index.py'))).toBe(true);
    }
  });
});

describe('scheduled ranking aggregation', () => {
  test('uses an explicit group, dedicated confused-deputy-safe role, retry, and DLQ', () => {
    const { json, template } = createAppStack('dev');
    template.hasResourceProperties('AWS::Scheduler::ScheduleGroup', {
      Name: 'ranking-aggregator-dev',
    });
    template.hasResourceProperties('AWS::Scheduler::Schedule', {
      GroupName: 'ranking-aggregator-dev',
      ScheduleExpression: 'rate(15 minutes)',
      FlexibleTimeWindow: { Mode: 'OFF' },
      Target: Match.objectLike({
        Input: '{}',
        DeadLetterConfig: { Arn: Match.anyValue() },
        RetryPolicy: {
          MaximumEventAgeInSeconds: 3600,
          MaximumRetryAttempts: 3,
        },
      }),
    });
    template.hasResourceProperties('AWS::SQS::Queue', {
      QueueName: 'ranking-aggregator-dlq-dev',
      MessageRetentionPeriod: 1209600,
      SqsManagedSseEnabled: true,
    });

    const groupLogicalId = resourcesOf(json, 'AWS::Scheduler::ScheduleGroup')[0][0];
    const targetRole = resourcesOf(json, 'AWS::IAM::Role')
      .find(([, role]) => role.Properties?.RoleName === 'ranking-scheduler-target-role-dev')![1];
    const trust = targetRole.Properties?.AssumeRolePolicyDocument.Statement[0];
    expect(trust.Principal).toEqual({ Service: 'scheduler.amazonaws.com' });
    expect(trust.Condition).toEqual({
      ArnEquals: { 'aws:SourceArn': { 'Fn::GetAtt': [groupLogicalId, 'Arn'] } },
      StringEquals: { 'aws:SourceAccount': DEV_ACCOUNT },
    });
    const targetPolicy = rolePolicy(json, 'ranking-scheduler-target-role-dev');
    expect(targetPolicy.map((statement) => actions(statement))).toEqual(
      expect.arrayContaining([['lambda:InvokeFunction'], ['sqs:SendMessage']]),
    );
  });
});

describe('split stacks', () => {
  test('DNS owns the root zone, retains it, and rejects the wrong account', () => {
    const app = new cdk.App();
    const dns = new DnsStack(app, 'Dns', {
      env: { account: DNS_ACCOUNT, region: 'ap-northeast-1' },
      terminationProtection: true,
    });
    const json = Template.fromStack(dns).toJSON() as Synthesized;
    const zone = resourcesOf(json, 'AWS::Route53::HostedZone')[0][1];
    expect(zone.Properties?.Name).toBe('whiskeybar.site.');
    expect(zone.DeletionPolicy).toBe('Retain');
    expect(Object.keys(json.Outputs ?? {})).toEqual(expect.arrayContaining([
      'HostedZoneId', 'NameServer1', 'NameServer2', 'NameServer3', 'NameServer4',
    ]));
    expect(() => new DnsStack(new cdk.App(), 'WrongDns', {
      env: { account: TEST_PRD_ACCOUNT, region: 'ap-northeast-1' },
    })).toThrow(DNS_ACCOUNT);
  });

  test('certificate consumes an injected hosted zone without lookup', () => {
    const app = new cdk.App();
    const producer = new cdk.Stack(app, 'Producer', {
      env: { account: DEV_ACCOUNT, region: 'us-east-1' },
    });
    const zone = route53.HostedZone.fromHostedZoneAttributes(producer, 'Zone', {
      hostedZoneId: 'Z1234567890',
      zoneName: 'whiskeybar.site',
    });
    const certificate = new CertificateStack(app, 'Certificate', {
      env: { account: DEV_ACCOUNT, region: 'us-east-1' },
      domain: 'dev.whiskeybar.site',
      hostedZone: zone,
    });
    Template.fromStack(certificate).resourceCountIs('AWS::CertificateManager::Certificate', 1);
  });

  test('OIDC trust is exact and S3 sync grants include delete without Lambda updates', () => {
    const app = new cdk.App();
    const oidc = new GithubOidcStack(app, 'Oidc', {
      env: { account: DEV_ACCOUNT, region: 'ap-northeast-1' },
      createOidcProvider: true,
      deploymentBucketName: `whiskey-webapp-dev-${DEV_ACCOUNT}`,
    });
    const { templateFile: _ignored, ...json } = Template.fromStack(oidc).toJSON() as Synthesized & { templateFile?: string };
    const role = resourcesOf(json, 'AWS::IAM::Role')
      .find(([, resource]) => resource.Properties?.RoleName === 'whiskey-github-actions-role-dev')![1];
    const trust = role.Properties?.AssumeRolePolicyDocument.Statement[0];
    expect(trust.Condition).toEqual({
      StringEquals: {
        'token.actions.githubusercontent.com:aud': 'sts.amazonaws.com',
        'token.actions.githubusercontent.com:sub': 'repo:kter/whiskey:environment:dev',
      },
    });
    const policyText = JSON.stringify(resourcesOf(json, 'AWS::IAM::Policy'));
    expect(policyText).toContain('s3:DeleteObject*');
    expect(policyText).toContain('cloudfront:CreateInvalidation');
    expect(policyText).toContain('cloudformation:DescribeStacks');
    expect(policyText).not.toContain('lambda:UpdateFunction');
  });

  test('OIDC provider can be imported without creating a provider resource', () => {
    const app = new cdk.App();
    const oidc = new GithubOidcStack(app, 'ImportedOidc', {
      env: { account: DEV_ACCOUNT, region: 'ap-northeast-1' },
      createOidcProvider: false,
      deploymentBucketName: `whiskey-webapp-dev-${DEV_ACCOUNT}`,
    });
    const json = Template.fromStack(oidc).toJSON() as Synthesized;
    expect(Object.values(json.Resources).some((resource) =>
      resource.Type.includes('OpenIdConnectProvider'))).toBe(false);
    expect(resourcesOf(json, 'AWS::IAM::Role')
      .some(([, role]) => role.Properties?.RoleName === 'whiskey-github-actions-role-dev')).toBe(true);
  });

  test('notification topic policies restrict service publishers and use SSM dynamic references', () => {
    const app = new cdk.App();
    const budget = new NotificationsStack(app, 'Budget', {
      env: { account: DEV_ACCOUNT, region: 'us-east-1' },
      kind: 'budget',
    });
    const alarms = new NotificationsStack(app, 'Alarms', {
      env: { account: DEV_ACCOUNT, region: 'ap-northeast-1' },
      kind: 'alarms',
    });
    const budgetJson = Template.fromStack(budget).toJSON() as Synthesized;
    const alarmJson = Template.fromStack(alarms).toJSON() as Synthesized;
    expect(JSON.stringify(budgetJson)).toContain('budgets.amazonaws.com');
    expect(JSON.stringify(budgetJson)).toContain('aws:SourceAccount');
    expect(JSON.stringify(budgetJson)).toContain('aws:SourceArn');
    expect(JSON.stringify(alarmJson)).toContain('cloudwatch.amazonaws.com');
    expect(JSON.stringify(alarmJson)).toContain('aws:SourceAccount');
    expect(JSON.stringify(alarmJson)).toContain('aws:SourceArn');
    expect(JSON.stringify(alarmJson)).toContain(`arn:aws:cloudwatch:*:${DEV_ACCOUNT}:alarm:*`);
    expect(JSON.stringify(budgetJson)).toContain('AWS::SSM::Parameter::Value<String>');
    expect(JSON.stringify(alarmJson)).toContain('AWS::SSM::Parameter::Value<String>');
    expect(JSON.stringify(budgetJson)).toContain('/whiskey/notifications/email');
    expect(JSON.stringify(alarmJson)).toContain('/whiskey/notifications/email');

    const topicPolicyLogicalId = resourcesOf(budgetJson, 'AWS::SNS::TopicPolicy')[0][0];
    const budgetResource = resourcesOf(budgetJson, 'AWS::Budgets::Budget')[0][1];
    const dependencies = Array.isArray(budgetResource.DependsOn)
      ? budgetResource.DependsOn
      : [budgetResource.DependsOn];
    expect(dependencies).toContain(topicPolicyLogicalId);
  });

  test.each([
    [false, false], [false, true], [true, false], [true, true],
  ])('dev feature combination custom=%s google=%s synthesizes', (customDomain, googleAuth) => {
    expect(() => createAppStack('dev', { customDomain, googleAuth })).not.toThrow();
  });
});
