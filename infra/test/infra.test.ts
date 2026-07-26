import * as fs from 'fs';
import * as path from 'path';
import * as cdk from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import * as route53 from 'aws-cdk-lib/aws-route53';
import { environments } from '../config/environments';
import { buildApp } from '../lib/app-builder';
import { CertificateStack } from '../lib/certificate-stack';
import { DNS_ACCOUNT, DnsStack } from '../lib/dns-stack';
import { GithubOidcStack } from '../lib/github-oidc-stack';
import { NotificationsStack } from '../lib/notifications-stack';
import { ObservabilityStack } from '../lib/observability-stack';
import { WhiskeyInfraStack } from '../lib/whiskey-infra-stack';
import { bedrockInvokeStatements } from '../lib/bedrock-models';

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
const PRD_ACCOUNT = '401731371959';

function createAppStack(
  environment: 'dev' | 'prd',
  options: { customDomain?: boolean; googleAuth?: boolean; extraOrigins?: string } = {},
): { stack: WhiskeyInfraStack; template: Template; json: Synthesized; outdir: string } {
  const app = new cdk.App({
    context: options.extraOrigins ? { extraAllowedOrigins: options.extraOrigins } : undefined,
  });
  const account = environment === 'dev' ? DEV_ACCOUNT : PRD_ACCOUNT;
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

function lambdaByName(json: Synthesized, functionName: string): Resource {
  const entry = resourcesOf(json, 'AWS::Lambda::Function')
    .find(([, fn]) => fn.Properties?.FunctionName === functionName);
  expect(entry).toBeDefined();
  return entry![1];
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

  test('images bucket expires only tmp objects and enables the two filtered request metrics', () => {
    const { json } = createAppStack('dev');
    const images = resourcesOf(json, 'AWS::S3::Bucket')
      .find(([, bucket]) => bucket.Properties?.BucketName === `whiskey-images-dev-${DEV_ACCOUNT}`)![1];
    expect(images.Properties?.VersioningConfiguration).toBeUndefined();
    expect(images.Properties?.LifecycleConfiguration.Rules).toEqual([
      expect.objectContaining({ Prefix: 'tmp/', ExpirationInDays: 2, Status: 'Enabled' }),
    ]);
    expect(images.Properties?.MetricsConfigurations).toEqual([
      { Id: 'tmp', Prefix: 'tmp/' },
      { Id: 'logs', Prefix: 'logs/' },
    ]);
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
    'POST /api/drink-logs/upload-url',
    'POST /api/drink-logs/analyze',
    'POST /api/drink-logs/places',
    'POST /api/drink-logs/places/resolve',
    'POST /api/drink-logs',
    'GET /api/drink-logs',
    'GET /api/drink-logs/{id}',
    'PUT /api/drink-logs/{id}',
    'DELETE /api/drink-logs/{id}',
  ];
  const publicRoutes = [
    'GET /api/whiskeys',
    'GET /api/whiskeys/search',
    'GET /api/whiskeys/suggest',
    'GET /api/whiskeys/search/suggest',
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

  test('drink log routes are wired to the intended function assets', () => {
    const { json } = createAppStack('dev');
    const methods = apiMethods(json);
    const functionLogicalId = (name: string): string => resourcesOf(json, 'AWS::Lambda::Function')
      .find(([, fn]) => fn.Properties?.FunctionName === name)![0];
    const expectations: Record<string, string> = {
      'POST /api/drink-logs/upload-url': 'drink-logs-dev',
      'POST /api/drink-logs/analyze': 'drink-log-analyze-dev',
      'POST /api/drink-logs/places': 'drink-log-places-dev',
      'POST /api/drink-logs/places/resolve': 'drink-log-places-dev',
      'POST /api/drink-logs': 'drink-logs-dev',
      'GET /api/drink-logs': 'drink-logs-dev',
      'GET /api/drink-logs/{id}': 'drink-logs-dev',
      'PUT /api/drink-logs/{id}': 'drink-logs-dev',
      'DELETE /api/drink-logs/{id}': 'drink-logs-dev',
    };
    for (const [route, functionName] of Object.entries(expectations)) {
      expect(JSON.stringify(methods[route]?.Integration.Uri)).toContain(functionLogicalId(functionName));
    }
    expect(methods['GET /api/drink-logs/places']).toBeUndefined();
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
      expect.objectContaining({
        ResourcePath: '/~1api~1drink-logs',
        HttpMethod: 'POST',
        ThrottlingRateLimit: 2,
        ThrottlingBurstLimit: 5,
      }),
      expect.objectContaining({
        ResourcePath: '/~1api~1drink-logs~1analyze',
        HttpMethod: 'POST',
        ThrottlingRateLimit: 2,
        ThrottlingBurstLimit: 5,
      }),
      expect.objectContaining({
        ResourcePath: '/~1api~1drink-logs~1{id}',
        HttpMethod: 'GET',
        ThrottlingRateLimit: 5,
        ThrottlingBurstLimit: 10,
      }),
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
  test('list and search roles have only their positive DynamoDB grants and constrained AppState prefixes', () => {
    const json = createAppStack('dev').json;
    const list = rolePolicy(json, 'whiskey-list-role-dev');
    const search = rolePolicy(json, 'whiskey-search-role-dev');

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

    const searchAppState = search.find((statement) =>
      actions(statement).includes('dynamodb:UpdateItem')
      && statement.Condition?.['ForAllValues:StringLike']?.['dynamodb:LeadingKeys']);
    expect(searchAppState?.Condition).toEqual({
      'ForAllValues:StringLike': { 'dynamodb:LeadingKeys': ['scan-counter/*'] },
      Null: { 'dynamodb:LeadingKeys': 'false' },
    });
    expect(search.some((statement) =>
      actions(statement).some((action) => ['dynamodb:PutItem', 'dynamodb:DeleteItem'].includes(action))
      || (statement.Condition?.['ForAllValues:StringLike']?.['dynamodb:LeadingKeys'] || [])
        .some((key: string) => !key.startsWith('scan-counter/'))))
      .toBe(false);

    expect(JSON.stringify(resourcesOf(json, 'AWS::IAM::Policy'))).not.toContain('TransactWriteItems');
    expect(JSON.stringify([...list, ...search])).not.toContain('cognito-idp:Admin');
    expect(JSON.stringify(resourcesOf(json, 'AWS::IAM::Policy'))).not.toContain('Reviews-dev');
  });

  test('drink log roles isolate AppState keyspaces and share AI results only as designed', () => {
    const json = createAppStack('dev').json;
    const policies = {
      logs: rolePolicy(json, 'drink-logs-role-dev'),
      analyze: rolePolicy(json, 'drink-log-analyze-role-dev'),
      places: rolePolicy(json, 'drink-log-places-role-dev'),
      reconciler: rolePolicy(json, 'drink-log-reconciler-role-dev'),
    };
    const appStatePatterns = (policy: Record<string, any>[], action: string): string[] =>
      policy
        .filter((statement) => actions(statement).includes(action)
          && statement.Condition?.['ForAllValues:StringLike']?.['dynamodb:LeadingKeys'])
        .flatMap((statement) => statement.Condition['ForAllValues:StringLike']['dynamodb:LeadingKeys']);

    expect(appStatePatterns(policies.logs, 'dynamodb:UpdateItem')).toEqual(expect.arrayContaining([
      'drinklog-counter#*', 'drinklog-quota#*', 'ai-result:*',
    ]));
    expect(appStatePatterns(policies.logs, 'dynamodb:GetItem')).toEqual(['ai-result:*']);
    expect(appStatePatterns(policies.logs, 'dynamodb:DeleteItem')).toEqual(['ai-result:*']);
    expect(appStatePatterns(policies.analyze, 'dynamodb:UpdateItem')).toEqual(['drinklog-counter#*']);
    // analyze は解析結果キャッシュを put_item で保存するため ai-result:* は PutItem。
    expect(appStatePatterns(policies.analyze, 'dynamodb:PutItem')).toEqual(['ai-result:*']);
    expect(appStatePatterns(policies.analyze, 'dynamodb:GetItem')).toEqual(['drinklog-counter#*']);
    expect(appStatePatterns(policies.places, 'dynamodb:UpdateItem')).toEqual(['drinklog-counter#*']);
    expect(appStatePatterns(policies.reconciler, 'dynamodb:UpdateItem')).toEqual(['drinklog-quota#*']);

    for (const policy of Object.values(policies)) {
      for (const statement of policy.filter((candidate) => candidate.Condition?.['ForAllValues:StringLike'])) {
        expect(statement.Condition.Null).toEqual({ 'dynamodb:LeadingKeys': 'false' });
      }
    }
    expect(appStatePatterns(policies.analyze, 'dynamodb:UpdateItem')).not.toContain('drinklog-quota#*');
    expect(appStatePatterns(policies.places, 'dynamodb:UpdateItem')).not.toContain('ai-result:*');
    expect(appStatePatterns(policies.reconciler, 'dynamodb:UpdateItem')).not.toContain('drinklog-counter#*');
  });

  test('Places secret belongs only to Places and reconciler list access covers both image prefixes', () => {
    const json = createAppStack('dev').json;
    const analyze = rolePolicy(json, 'drink-log-analyze-role-dev');
    const places = rolePolicy(json, 'drink-log-places-role-dev');
    const reconciler = rolePolicy(json, 'drink-log-reconciler-role-dev');
    expect(places.some((statement) => actions(statement).includes('secretsmanager:GetSecretValue'))).toBe(true);
    expect(analyze.some((statement) => actions(statement).some((action) => action.startsWith('secretsmanager:'))))
      .toBe(false);
    expect(places.some((statement) => actions(statement).includes('dynamodb:BatchGetItem'))).toBe(true);
    const list = reconciler.find((statement) => actions(statement).includes('s3:ListBucket'))!;
    expect(list.Condition).toEqual({ StringLike: { 's3:prefix': ['logs/*', 'tmp/*'] } });
    expect(reconciler.some((statement) => actions(statement).includes('s3:PutObject'))).toBe(false);
  });

  test('Bedrock permissions match both approved profiles and destinations without discovery access', () => {
    const json = createAppStack('dev').json;
    const analyze = rolePolicy(json, 'drink-log-analyze-role-dev');
    const bedrock = analyze.filter((statement) => actions(statement).includes('bedrock:InvokeModel'));
    const profileArns = [
      `arn:aws:bedrock:ap-northeast-1:${DEV_ACCOUNT}:inference-profile/jp.amazon.nova-2-lite-v1:0`,
      `arn:aws:bedrock:ap-northeast-1:${DEV_ACCOUNT}:inference-profile/jp.anthropic.claude-haiku-4-5-20251001-v1:0`,
    ];
    const destinationArns = [
      'arn:aws:bedrock:ap-northeast-1::foundation-model/amazon.nova-2-lite-v1:0',
      'arn:aws:bedrock:ap-northeast-3::foundation-model/amazon.nova-2-lite-v1:0',
      'arn:aws:bedrock:ap-northeast-1::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0',
      'arn:aws:bedrock:ap-northeast-3::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0',
    ];
    expect(bedrock).toHaveLength(2);
    expect(bedrock[0].Resource).toEqual(profileArns);
    expect(bedrock[1].Resource).toEqual(destinationArns);
    expect(bedrock[1].Condition).toEqual({
      StringEquals: { 'bedrock:InferenceProfileArn': profileArns },
    });
    expect(JSON.stringify(analyze)).not.toContain('bedrock:GetInferenceProfile');
    expect(JSON.stringify(bedrock)).not.toContain('*');
    expect(JSON.stringify(bedrock)).not.toContain('foundation-model/unapproved');
  });

  test('Bedrock statement builder supports exact direct model grants', () => {
    const directArn = 'arn:aws:bedrock:ap-northeast-1::foundation-model/example.direct-v1:0';
    const statements = bedrockInvokeStatements([{ type: 'direct', modelArn: directArn }])
      .map((statement) => statement.toStatementJson());
    expect(statements).toEqual([{
      Effect: 'Allow',
      Action: 'bedrock:InvokeModel',
      Resource: directArn,
    }]);
    expect(JSON.stringify(statements)).not.toContain('inference-profile');
  });
});

describe('tables, logs, and removed infrastructure', () => {
  test('only WhiskeySearch, DrinkLogs, and AppState application tables remain', () => {
    const { template, json } = createAppStack('prd');
    template.hasResourceProperties('AWS::DynamoDB::Table', {
      TableName: 'AppState-prd',
      BillingMode: 'PAY_PER_REQUEST',
      KeySchema: [{ AttributeName: 'pk', KeyType: 'HASH' }],
      TimeToLiveSpecification: { AttributeName: 'ttl', Enabled: true },
    });
    const serialized = JSON.stringify(json);
    const tableNames = resourcesOf(json, 'AWS::DynamoDB::Table')
      .map(([, table]) => table.Properties?.TableName)
      .filter((name): name is string => typeof name === 'string');
    expect(tableNames).toEqual(expect.arrayContaining([
      'WhiskeySearch-prd',
      'DrinkLogs-prd',
      'AppState-prd',
    ]));
    expect(tableNames).not.toContain('Reviews-prd');
    expect(serialized).not.toContain('WhiskeyIndex');
    expect(serialized).not.toContain('DistilleryIndex');
    expect(serialized).not.toContain('Users-');
    expect(serialized).not.toContain('reviews-prd');
    expect(serialized).not.toContain('ranking-aggregator-prd');
    template.resourceCountIs('AWS::EC2::VPC', 0);
    template.resourceCountIs('AWS::Route53::HostedZone', 0);
  });

  test('DrinkLogs uses the user datetime GSI and intentionally has no TTL', () => {
    const { json } = createAppStack('dev');
    const table = resourcesOf(json, 'AWS::DynamoDB::Table')
      .find(([, resource]) => resource.Properties?.TableName === 'DrinkLogs-dev')![1];
    expect(table.Properties).toEqual(expect.objectContaining({
      BillingMode: 'PAY_PER_REQUEST',
      KeySchema: [{ AttributeName: 'id', KeyType: 'HASH' }],
      GlobalSecondaryIndexes: [expect.objectContaining({
        IndexName: 'UserDatetimeIndex',
        KeySchema: [
          { AttributeName: 'user_id', KeyType: 'HASH' },
          { AttributeName: 'datetime', KeyType: 'RANGE' },
        ],
      })],
    }));
    expect(table.Properties?.TimeToLiveSpecification).toBeUndefined();
  });

  test('every function uses its dedicated /whiskey/{env}/ log group', () => {
    const { template } = createAppStack('dev');
    for (const name of [
      'whiskeys-list', 'whiskeys-search',
      'drink-logs', 'drink-log-analyze', 'drink-log-places', 'drink-log-reconciler',
    ]) {
      template.hasResourceProperties('AWS::Logs::LogGroup', {
        LogGroupName: `/whiskey/dev/${name}`,
      });
    }
    const serialized = JSON.stringify(template.toJSON());
    expect(serialized).not.toContain('/whiskey/dev/reviews');
    expect(serialized).not.toContain('/whiskey/dev/ranking-aggregator');
  });
});

describe('Lambda bundling and shared layer', () => {
  test('all application functions are x86_64, use the shared layer, and receive shared settings', () => {
    const { json } = createAppStack('dev');
    const applicationFunctions = resourcesOf(json, 'AWS::Lambda::Function')
      .filter(([, resource]) => typeof resource.Properties?.FunctionName === 'string'
        && ['whiskey-list-dev', 'whiskey-search-dev']
          .includes(resource.Properties.FunctionName));
    expect(applicationFunctions).toHaveLength(2);
    for (const [, fn] of applicationFunctions) {
      expect(fn.Properties?.Architectures).toEqual(['x86_64']);
      expect(fn.Properties?.Layers).toHaveLength(1);
      expect(fn.Properties?.Environment.Variables.ALLOWED_ORIGINS).toContain('https://dev.whiskeybar.site');
    }
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
    expect(search.Properties?.Environment.Variables.REVIEWS_TABLE).toBeUndefined();
    expect(resourcesOf(json, 'AWS::Lambda::LayerVersion')).toHaveLength(1);
  });

  test('drink log functions pin handlers, sizing, concurrency, and cost-matrix environment', () => {
    const { json } = createAppStack('dev');
    // 2026-07-21: dev のアカウント同時実行上限が 10（絶対最低値）のため予約並列度は
    // 無効化。既定 dev 設定では全関数の ReservedConcurrentExecutions は undefined。
    // 設定時に値が反映されることは下の「added only when configured」テストで担保。
    const expected = [
      ['drink-logs-dev', 'index.lambda_handler', 1024, 25, undefined],
      ['drink-log-analyze-dev', 'index.lambda_handler', 1024, 28, undefined],
      ['drink-log-places-dev', 'places.lambda_handler', 256, 10, undefined],
      ['drink-log-reconciler-dev', 'reconciler.lambda_handler', 512, 300, undefined],
    ] as const;
    for (const [name, handler, memory, timeout, concurrency] of expected) {
      const fn = lambdaByName(json, name);
      expect(fn.Properties).toEqual(expect.objectContaining({
        Runtime: 'python3.11',
        Architectures: ['x86_64'],
        Handler: handler,
        MemorySize: memory,
        Timeout: timeout,
      }));
      expect(fn.Properties?.Layers).toHaveLength(1);
      expect(fn.Properties?.ReservedConcurrentExecutions).toBe(concurrency);
    }

    const logsEnv = lambdaByName(json, 'drink-logs-dev').Properties?.Environment.Variables;
    expect(logsEnv).toEqual(expect.objectContaining({
      ENVIRONMENT: 'dev',
      UPLOAD_USER_DAILY_LIMIT: '30',
      UPLOAD_GLOBAL_DAILY_LIMIT: '100',
      CREATE_USER_DAILY_LIMIT: '30',
      CREATE_GLOBAL_DAILY_LIMIT: '100',
      STORAGE_USER_LIMIT: '2000',
      STORAGE_GLOBAL_LIMIT: '20000',
      IMAGE_MAX_BYTES: '1572864',
      UPLOAD_MAX_BYTES: '3670016',
    }));
    const analyzeEnv = lambdaByName(json, 'drink-log-analyze-dev').Properties?.Environment.Variables;
    expect(analyzeEnv).toEqual(expect.objectContaining({
      BEDROCK_MODEL_ID: 'jp.amazon.nova-2-lite-v1:0',
      BEDROCK_MODEL_ALLOWLIST: 'jp.amazon.nova-2-lite-v1:0,jp.anthropic.claude-haiku-4-5-20251001-v1:0',
      ANALYZE_USER_DAILY_LIMIT: '20',
      ANALYZE_GLOBAL_DAILY_LIMIT: '50',
      ANALYZE_GLOBAL_MONTHLY_LIMIT: '1000',
    }));
    const placesEnv = lambdaByName(json, 'drink-log-places-dev').Properties?.Environment.Variables;
    expect(placesEnv).toEqual(expect.objectContaining({
      PLACES_USER_DAILY_LIMIT: '30',
      PLACES_GLOBAL_DAILY_LIMIT: '15',
      PLACES_GLOBAL_MONTHLY_LIMIT: '150',
      PLACES_SECRET_NAME: 'whiskey-places-dev',
    }));
    for (const env of [logsEnv, analyzeEnv, placesEnv]) {
      expect(env).toEqual(expect.objectContaining({
        APP_STATE_TABLE: expect.anything(),
        DRINKLOGS_TABLE: expect.anything(),
        IMAGES_BUCKET: expect.anything(),
        ALLOWED_ORIGINS: expect.stringContaining('https://dev.whiskeybar.site'),
        COGNITO_USER_POOL_ID: expect.anything(),
        COGNITO_CLIENT_ID: expect.anything(),
      }));
    }
    expect(lambdaByName(json, 'drink-log-reconciler-dev').Properties?.Environment.Variables)
      .toEqual(expect.objectContaining({ RECONCILE_AGE_HOURS: '48' }));
  });

  test('reserved concurrency is added only when configured', () => {
    const previous = environments.dev.lambdaReservedConcurrency;
    environments.dev.lambdaReservedConcurrency = {
      analyze: 2,
      places: 3,
      reconciler: 1,
    };
    try {
      const { json } = createAppStack('dev');
      const rcOf = (name: string) => lambdaByName(json, name).Properties?.ReservedConcurrentExecutions;
      expect(rcOf('drink-log-analyze-dev')).toBe(2);
      expect(rcOf('drink-log-places-dev')).toBe(3);
      expect(rcOf('drink-log-reconciler-dev')).toBe(1);
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
    expect(source).toContain("process.env.CDK_LOCAL_BUNDLING === '1'");

    const { json, outdir } = createAppStack('dev');
    const applicationFunctions = resourcesOf(json, 'AWS::Lambda::Function')
      .filter(([, resource]) => typeof resource.Properties?.FunctionName === 'string'
        && ['whiskey-list-dev', 'whiskey-search-dev']
          .includes(resource.Properties.FunctionName));
    for (const [, fn] of applicationFunctions) {
      const assetHash = JSON.stringify(fn.Properties?.Code).match(/[a-f0-9]{64}/)?.[0];
      expect(assetHash).toBeDefined();
      expect(fs.existsSync(path.join(outdir, `asset.${assetHash}`, 'index.py'))).toBe(true);
    }
  });

  test('local bundling contains every deployed drink log handler module', () => {
    const { json, outdir } = createAppStack('dev');
    const expected = [
      ['drink-logs-dev', 'index.py'],
      ['drink-log-analyze-dev', 'index.py'],
      ['drink-log-places-dev', 'places.py'],
      ['drink-log-reconciler-dev', 'reconciler.py'],
    ];
    for (const [functionName, handlerFile] of expected) {
      const fn = lambdaByName(json, functionName);
      const assetHash = JSON.stringify(fn.Properties?.Code).match(/[a-f0-9]{64}/)?.[0];
      expect(assetHash).toBeDefined();
      expect(fs.existsSync(path.join(outdir, `asset.${assetHash}`, handlerFile))).toBe(true);
    }
  });

  test('drink log dependencies are pinned only in the new functions, not the shared layer', () => {
    const lambdaRoot = path.join(__dirname, '..', '..', 'lambda');
    const common = fs.readFileSync(path.join(lambdaRoot, 'common', 'requirements.txt'), 'utf8');
    const logs = fs.readFileSync(path.join(lambdaRoot, 'drink-logs', 'requirements.txt'), 'utf8');
    const analyze = fs.readFileSync(path.join(lambdaRoot, 'drink-log-analyze', 'requirements.txt'), 'utf8');
    for (const requirement of ['boto3==1.43.4', 'botocore==1.43.4']) {
      // The new functions bundle their own SDK; the shared layer must NOT pin boto3
      // so the list/search functions keep runtime-provided boto3.
      expect(common).not.toContain(requirement);
      expect(logs).toContain(requirement);
      expect(analyze).toContain(requirement);
    }
    expect(logs).toContain('Pillow==11.0.0');
    expect(analyze).toContain('Pillow==11.0.0');
    expect(analyze).toContain('requests==2.32.5');
    // whiskey_common.jwt_utils imports `jwt` and `requests` at module load, so every
    // function bundling it (via the shared layer) must pin PyJWT[crypto] and requests
    // or the Lambda fails at import with "No module named 'jwt'". Regression guard.
    for (const requirement of ['PyJWT[crypto]==2.10.1', 'requests==2.32.5']) {
      expect(logs).toContain(requirement);
      expect(analyze).toContain(requirement);
    }
  });
});

describe('scheduled drink log reconciliation', () => {
  test('drink log reconciler runs daily with its own safe target role and DLQ', () => {
    const { json, template } = createAppStack('dev');
    expect(resourcesOf(json, 'AWS::Scheduler::Schedule')).toHaveLength(1);
    expect(JSON.stringify(json)).not.toContain('ranking-aggregator');
    template.hasResourceProperties('AWS::Scheduler::Schedule', {
      Name: 'drink-log-reconciler-daily-dev',
      GroupName: 'drink-log-reconciler-dev',
      ScheduleExpression: 'rate(1 day)',
      FlexibleTimeWindow: { Mode: 'OFF' },
      Target: Match.objectLike({
        DeadLetterConfig: { Arn: Match.anyValue() },
        RetryPolicy: { MaximumEventAgeInSeconds: 3600, MaximumRetryAttempts: 3 },
      }),
    });
    template.hasResourceProperties('AWS::SQS::Queue', {
      QueueName: 'drink-log-reconciler-dlq-dev',
      MessageRetentionPeriod: 1209600,
      SqsManagedSseEnabled: true,
    });
    const group = resourcesOf(json, 'AWS::Scheduler::ScheduleGroup')
      .find(([, resource]) => resource.Properties?.Name === 'drink-log-reconciler-dev')!;
    const role = resourcesOf(json, 'AWS::IAM::Role')
      .find(([, resource]) => resource.Properties?.RoleName === 'drink-log-reconciler-scheduler-target-role-dev')![1];
    expect(role.Properties?.AssumeRolePolicyDocument.Statement[0].Condition).toEqual({
      ArnEquals: { 'aws:SourceArn': { 'Fn::GetAtt': [group[0], 'Arn'] } },
      StringEquals: { 'aws:SourceAccount': DEV_ACCOUNT },
    });
    expect(rolePolicy(json, 'drink-log-reconciler-scheduler-target-role-dev')
      .map((statement) => actions(statement))).toEqual(expect.arrayContaining([
      ['lambda:InvokeFunction'], ['sqs:SendMessage'],
    ]));
  });
});

describe('split stacks', () => {
  test('environment DNS ownership and production feature flags are configured explicitly', () => {
    expect(environments.dev.hostedZoneName).toBe('dev.whiskeybar.site');
    expect(environments.dev.parentZone).toEqual({
      account: PRD_ACCOUNT,
      zoneName: 'whiskeybar.site',
    });
    expect(environments.dev.parentZone?.account).toBe(environments.prd.account);
    expect(environments.prd).toEqual(expect.objectContaining({
      account: PRD_ACCOUNT,
      hostedZoneName: 'whiskeybar.site',
      delegationTargetAccounts: [DEV_ACCOUNT],
      enableCustomDomain: true,
      enableGoogleAuth: true,
    }));
    expect(environments.prd.parentZone).toBeUndefined();
    expect(environments.prd.lambdaReservedConcurrency).toBeUndefined();
  });

  test('prd DNS owns and retains the apex zone with a dev delegation role', () => {
    const app = new cdk.App();
    const dns = new DnsStack(app, 'Dns', {
      env: { account: PRD_ACCOUNT, region: 'ap-northeast-1' },
      terminationProtection: true,
      zoneName: 'whiskeybar.site',
      delegationTargetAccounts: [DNS_ACCOUNT],
    });
    const json = Template.fromStack(dns).toJSON() as Synthesized;
    const zone = resourcesOf(json, 'AWS::Route53::HostedZone')[0][1];
    expect(zone.Properties?.Name).toBe('whiskeybar.site.');
    expect(zone.DeletionPolicy).toBe('Retain');
    const roles = resourcesOf(json, 'AWS::IAM::Role');
    expect(roles).toHaveLength(1);
    expect(roles[0][1].Properties?.RoleName).toBe('WhiskeyDnsDelegationRole');
    expect(JSON.stringify(roles[0][1].Properties?.AssumeRolePolicyDocument)).toContain(DNS_ACCOUNT);
    expect(Object.keys(json.Outputs ?? {})).toEqual(expect.arrayContaining([
      'HostedZoneId', 'NameServer1', 'NameServer2', 'NameServer3', 'NameServer4', 'DelegationRoleArn',
    ]));
  });

  test('dev DNS owns the child zone and delegates it through the prd role', () => {
    const app = new cdk.App();
    const dns = new DnsStack(app, 'Dns', {
      env: { account: DNS_ACCOUNT, region: 'ap-northeast-1' },
      zoneName: 'dev.whiskeybar.site',
      parentZone: {
        account: PRD_ACCOUNT,
        zoneName: 'whiskeybar.site',
      },
    });
    const json = Template.fromStack(dns).toJSON() as Synthesized;
    const zone = resourcesOf(json, 'AWS::Route53::HostedZone')[0][1];
    expect(zone.Properties?.Name).toBe('dev.whiskeybar.site.');
    const delegation = resourcesOf(json, 'Custom::CrossAccountZoneDelegation');
    expect(delegation).toHaveLength(1);
    expect(delegation[0][1].Properties?.ParentZoneName).toBe('whiskeybar.site');
    expect(JSON.stringify(delegation[0][1].Properties)).toContain(PRD_ACCOUNT);
  });

  test('dev DNS can disable parent-zone delegation through context', () => {
    const app = new cdk.App({
      context: { enableZoneDelegation: 'false' },
    });
    const dns = new DnsStack(app, 'Dns', {
      env: { account: DNS_ACCOUNT, region: 'ap-northeast-1' },
      zoneName: 'dev.whiskeybar.site',
      parentZone: {
        account: PRD_ACCOUNT,
        zoneName: 'whiskeybar.site',
      },
    });
    Template.fromStack(dns).resourceCountIs('Custom::CrossAccountZoneDelegation', 0);
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

  test('observability stack creates availability alarms and sends every alarm to Tokyo SNS', () => {
    const app = new cdk.App();
    const errorAlarmFunctionNames = [
      'drink-log-analyze-dev',
      'drink-log-places-dev',
    ];
    const stack = new ObservabilityStack(app, 'Observability', {
      env: { account: DEV_ACCOUNT, region: 'ap-northeast-1' },
      environment: 'dev',
      notificationTopicArn: `arn:aws:sns:ap-northeast-1:${DEV_ACCOUNT}:alerts`,
      imagesBucketName: `whiskey-images-dev-${DEV_ACCOUNT}`,
      reconcilerFunctionName: 'drink-log-reconciler-dev',
      restApiName: 'whiskey-api-dev',
      errorAlarmFunctionNames,
    });
    const synthesized = Template.fromStack(stack).toJSON() as Synthesized & { templateFile?: string };
    const { templateFile: _ignored, ...json } = synthesized;
    // 3 existing + API 5xx + per-function Errors + Throttles. Must stay at or under the
    // 10 alarm metrics that CloudWatch gives each account for free.
    expect(resourcesOf(json, 'AWS::CloudWatch::Alarm'))
      .toHaveLength(3 + 1 + errorAlarmFunctionNames.length + 1);
    expect(resourcesOf(json, 'AWS::CloudWatch::Alarm').length).toBeLessThanOrEqual(10);
    expect(resourcesOf(json, 'AWS::Route53::HostedZone')).toHaveLength(0);
    expect(resourcesOf(json, 'AWS::Lambda::Function')).toHaveLength(0);
    const alarms = resourcesOf(json, 'AWS::CloudWatch::Alarm').map(([, alarm]) => alarm.Properties!);
    expect(alarms).toEqual(expect.arrayContaining([
      expect.objectContaining({
        MetricName: 'PostRequests',
        Namespace: 'AWS/S3',
        TreatMissingData: 'notBreaching',
        Dimensions: expect.arrayContaining([
          { Name: 'BucketName', Value: `whiskey-images-dev-${DEV_ACCOUNT}` },
          { Name: 'FilterId', Value: 'tmp' },
        ]),
      }),
      expect.objectContaining({
        MetricName: 'GetRequests',
        Namespace: 'AWS/S3',
        TreatMissingData: 'notBreaching',
        Dimensions: expect.arrayContaining([
          { Name: 'FilterId', Value: 'logs' },
        ]),
      }),
      expect.objectContaining({
        MetricName: 'Errors',
        Namespace: 'AWS/Lambda',
        Threshold: 1,
        TreatMissingData: 'notBreaching',
        Dimensions: [{ Name: 'FunctionName', Value: 'drink-log-reconciler-dev' }],
      }),
    ]));
    expect(alarms).toEqual(expect.arrayContaining([
      expect.objectContaining({
        AlarmName: 'whiskey-dev-tmp-post-requests-high',
        Threshold: 300,
      }),
      expect.objectContaining({
        AlarmName: 'whiskey-dev-logs-get-requests-high',
        Threshold: 2000,
      }),
      expect.objectContaining({
        AlarmName: 'whiskey-dev-drink-log-reconciler-errors',
        Threshold: 1,
      }),
      expect.objectContaining({
        AlarmName: 'whiskey-dev-api-5xx-high',
        MetricName: '5XXError',
        Namespace: 'AWS/ApiGateway',
        Threshold: 5,
        Dimensions: [{ Name: 'ApiName', Value: 'whiskey-api-dev' }],
      }),
      expect.objectContaining({
        AlarmName: 'whiskey-dev-lambda-throttles',
        MetricName: 'Throttles',
        Namespace: 'AWS/Lambda',
        Threshold: 1,
      }),
    ]));

    const lambdaErrorsAlarms = alarms.filter((alarm) =>
      alarm.AlarmName.startsWith('whiskey-dev-lambda-errors-'));
    expect(lambdaErrorsAlarms).toHaveLength(errorAlarmFunctionNames.length);
    expect(lambdaErrorsAlarms.map((alarm) => alarm.Dimensions[0].Value).sort())
      .toEqual([...errorAlarmFunctionNames].sort());
    expect(lambdaErrorsAlarms.every((alarm) =>
      alarm.MetricName === 'Errors' && alarm.Threshold === 3)).toBe(true);

    const lambdaThrottlesAlarms = alarms.filter((alarm) =>
      alarm.AlarmName === 'whiskey-dev-lambda-throttles');
    expect(lambdaThrottlesAlarms).toHaveLength(1);
    expect(lambdaThrottlesAlarms[0].Dimensions).toBeUndefined();

    // Per-table DynamoDB alarms were dropped to stay inside the free tier.
    expect(alarms.filter((alarm) =>
      alarm.Namespace === 'AWS/DynamoDB')).toHaveLength(0);

    for (const alarm of alarms) {
      expect(alarm.AlarmActions).toEqual([
        `arn:aws:sns:ap-northeast-1:${DEV_ACCOUNT}:alerts`,
      ]);
    }
  });

  test('entrypoint and deployment guard preserve Notifications then App then Observability', () => {
    const binSource = fs.readFileSync(path.join(__dirname, '..', 'bin', 'infra.ts'), 'utf8');
    const builderSource = fs.readFileSync(path.join(__dirname, '..', 'lib', 'app-builder.ts'), 'utf8');
    const deploySource = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'deploy.sh'), 'utf8');
    const packageJson = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf8'));
    expect(binSource).toContain('buildApp(new cdk.App())');
    expect(builderSource).toContain('appStack.addDependency(tokyoNotifications)');
    expect(builderSource).toContain('observabilityStack.addDependency(appStack)');
    expect(builderSource).toContain('observabilityStack.addDependency(tokyoNotifications)');
    expect(builderSource).toContain('crossRegionReferences: true');
    expect(deploySource).toContain('[[ "$SELECT_OBSERVABILITY" == true ]] && STACKS+=("WhiskeyObservability-$ENV_NAME")');
    expect(deploySource).toContain('|| "$SELECT_OBSERVABILITY" == true');
    expect(deploySource).toContain('[[ "$SELECT_DNS" == true ]] && STACKS+=(WhiskeyDns)');
    expect(deploySource).toContain('if [[ "$ENVIRONMENT" == "prd" && "$SELECT_OIDC" == true ]]');
    expect(deploySource).not.toContain('"$ENVIRONMENT" == "prd" && ("$SELECT_DNS"');
    expect(packageJson.scripts['deploy:observability:dev']).toContain('--observability');
    expect(packageJson.scripts['diff:observability:dev']).toContain('--observability --diff-only');
  });

  test.each([
    [false, false], [false, true], [true, false], [true, true],
  ])('dev feature combination custom=%s google=%s synthesizes', (customDomain, googleAuth) => {
    expect(() => createAppStack('dev', { customDomain, googleAuth })).not.toThrow();
  });

  test('prd with custom domain disabled synthesizes without lookups', () => {
    expect(() => createAppStack('prd')).not.toThrow();
  });

  test('prd custom domain configures the CloudFront and API Gateway aliases', () => {
    const { template } = createAppStack('prd', { customDomain: true });
    template.hasResourceProperties('AWS::CloudFront::Distribution', {
      DistributionConfig: Match.objectLike({
        Aliases: ['whiskeybar.site'],
      }),
    });
    template.hasResourceProperties('AWS::ApiGateway::DomainName', {
      DomainName: 'api.whiskeybar.site',
    });
  });
});

function synthesizeApplication(environment: 'dev' | 'prd') {
  const app = new cdk.App({ context: { env: environment } });
  const stacks = buildApp(app);
  const assembly = app.synth();
  const dns = assembly.getStackArtifact(stacks.dnsStack.artifactId).template as Synthesized;
  const observability = assembly
    .getStackArtifact(stacks.observabilityStack.artifactId).template as Synthesized;
  return {
    assembly,
    dns,
    observability,
    observabilityStackName: stacks.observabilityStack.stackName,
  };
}

describe('application builder environment wiring', () => {
  const prd = synthesizeApplication('prd');
  const dev = synthesizeApplication('dev');

  test('prd wires the apex zone, dev trust, and production application stacks', () => {
    const delegationRoles = resourcesOf(prd.dns, 'AWS::IAM::Role')
      .filter(([, role]) => role.Properties?.RoleName === 'WhiskeyDnsDelegationRole');
    expect(delegationRoles).toHaveLength(1);
    expect(JSON.stringify(delegationRoles[0][1].Properties?.AssumeRolePolicyDocument))
      .toContain(DEV_ACCOUNT);
    expect(resourcesOf(prd.dns, 'Custom::CrossAccountZoneDelegation')).toHaveLength(0);
    expect(resourcesOf(prd.dns, 'AWS::Route53::HostedZone')[0][1].Properties?.Name)
      .toBe('whiskeybar.site.');

    const artifacts = Object.keys(prd.assembly.manifest.artifacts ?? {});
    expect(artifacts).toContain('WhiskeyCertificate-Prd');
    expect(artifacts).toContain('WhiskeyApp-Prd');
    expect(prd.observabilityStackName).toBe('WhiskeyObservability-Prd');

    const alarms = resourcesOf(prd.observability, 'AWS::CloudWatch::Alarm')
      .map(([, alarm]) => alarm.Properties!);
    const api5xxAlarm = alarms.filter((alarm) =>
      alarm.AlarmName === 'whiskey-prd-api-5xx-high');
    expect(api5xxAlarm).toHaveLength(1);
    expect(api5xxAlarm[0].Dimensions)
      .toEqual([{ Name: 'ApiName', Value: 'whiskey-api-prd' }]);

    // Only the functions that spend money per invocation get their own Errors alarm.
    const expectedFunctionNames = [
      'drink-log-analyze-prd',
      'drink-log-places-prd',
    ];
    const lambdaErrorsAlarms = alarms.filter((alarm) =>
      alarm.AlarmName.startsWith('whiskey-prd-lambda-errors-'));
    expect(lambdaErrorsAlarms).toHaveLength(expectedFunctionNames.length);
    expect(lambdaErrorsAlarms.map((alarm) => alarm.Dimensions[0].Value).sort())
      .toEqual(expectedFunctionNames.sort());

    // CloudWatch bills per metric referenced by an alarm and gives each account
    // 10 alarm metrics free. Production must stay inside that allowance.
    expect(alarms.length).toBeLessThanOrEqual(10);
    expect(alarms.filter((alarm) => alarm.Namespace === 'AWS/DynamoDB')).toHaveLength(0);
  });

  test('dev wires the child zone to the production delegation role only', () => {
    const delegation = resourcesOf(dev.dns, 'Custom::CrossAccountZoneDelegation');
    expect(delegation).toHaveLength(1);
    expect(delegation[0][1].Properties?.AssumeRoleArn)
      .toBe(`arn:aws:iam::${PRD_ACCOUNT}:role/WhiskeyDnsDelegationRole`);
    const delegationRoles = resourcesOf(dev.dns, 'AWS::IAM::Role')
      .filter(([, role]) => role.Properties?.RoleName === 'WhiskeyDnsDelegationRole');
    expect(delegationRoles).toHaveLength(0);
    expect(resourcesOf(dev.dns, 'AWS::Route53::HostedZone')[0][1].Properties?.Name)
      .toBe('dev.whiskeybar.site.');
  });
});
