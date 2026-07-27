import * as cdk from 'aws-cdk-lib';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as acm from 'aws-cdk-lib/aws-certificatemanager';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as route53 from 'aws-cdk-lib/aws-route53';
import * as targets from 'aws-cdk-lib/aws-route53-targets';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as scheduler from 'aws-cdk-lib/aws-scheduler';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import { Construct } from 'constructs';
import * as fs from 'fs';
import * as path from 'path';
import { environments } from '../config/environments';
import { BedrockModel, bedrockInvokeStatements, bedrockModelAllowlist } from './bedrock-models';

export interface WhiskeyInfraStackProps extends cdk.StackProps {
  environment: string;
  enableCustomDomain?: boolean;
  enableGoogleAuth?: boolean;
  hostedZone?: route53.IHostedZone;
  cloudFrontCertificateArn?: string;
}

const API_TIMEOUT = cdk.Duration.seconds(29);
const SCAN_COUNTER_PREFIX = 'scan-counter/*';
const DRINKLOG_COUNTER_PREFIX = 'drinklog-counter#*';
const DRINKLOG_QUOTA_PREFIX = 'drinklog-quota#*';
const AI_RESULT_PREFIX = 'ai-result:*';
const BUNDLING_COMMAND = "if [ -f requirements.txt ]; then pip install -r requirements.txt -t /asset-output; fi && cp -au . /asset-output && find /asset-output -name __pycache__ -type d -exec rm -rf {} +";

function parseExtraOrigins(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.filter((origin): origin is string => typeof origin === 'string' && origin.length > 0);
  }
  if (typeof value === 'string') {
    return value.split(',').map((origin) => origin.trim()).filter(Boolean);
  }
  return [];
}

export class WhiskeyInfraStack extends cdk.Stack {
  public readonly imagesBucketName: string;
  public readonly drinkLogReconcilerFunctionName: string;
  public readonly restApiName: string;
  /** Functions billed per invocation by an external service; each gets its own Errors alarm. */
  public readonly errorAlarmFunctionNames: string[];

  constructor(scope: Construct, id: string, props: WhiskeyInfraStackProps) {
    super(scope, id, props);

    const { environment } = props;
    const envConfig = environments[environment];
    if (!envConfig) {
      throw new Error(`Environment configuration not found for: ${environment}`);
    }

    const retainResources = envConfig.retainResources;
    const removalPolicy = retainResources ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY;
    const enableCustomDomain = props.enableCustomDomain ?? envConfig.enableCustomDomain;
    const enableGoogleAuth = props.enableGoogleAuth ?? envConfig.enableGoogleAuth;
    const allowedOrigins = Array.from(new Set([
      ...envConfig.allowedOrigins,
      ...parseExtraOrigins(this.node.tryGetContext('extraAllowedOrigins')),
    ]));
    const tableNames = {
      whiskeySearch: `WhiskeySearch-${environment}`,
      appState: `AppState-${environment}`,
      drinkLogs: `DrinkLogs-${environment}`,
    };
    const lambdaFunctionNames = {
      whiskeyList: `whiskey-list-${environment}`,
      whiskeySearch: `whiskey-search-${environment}`,
      drinkLogs: `drink-logs-${environment}`,
      drinkLogAnalyze: `drink-log-analyze-${environment}`,
      drinkLogPlaces: `drink-log-places-${environment}`,
      drinkLogReconciler: `drink-log-reconciler-${environment}`,
    };
    this.errorAlarmFunctionNames = [
      lambdaFunctionNames.drinkLogAnalyze,
      lambdaFunctionNames.drinkLogPlaces,
    ];
    this.restApiName = `whiskey-api-${environment}`;

    if (enableCustomDomain && (!envConfig.domain || !envConfig.apiDomain || !props.hostedZone || !props.cloudFrontCertificateArn)) {
      throw new Error('Custom domains require domain configuration, a hosted zone, and a CloudFront certificate.');
    }

    const bucketDefaults = {
      versioned: false,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      removalPolicy,
      autoDeleteObjects: !retainResources,
    };

    const imagesBucket = new s3.Bucket(this, 'WhiskeyImagesBucket', {
      ...bucketDefaults,
      bucketName: `whiskey-images-${environment}-${this.account}`,
      lifecycleRules: [{ prefix: 'tmp/', expiration: cdk.Duration.days(2) }],
      // Paid, best-effort request metrics expose PostRequests/BytesUploaded for tmp and
      // GetRequests/BytesDownloaded for logs; AppState counters enforce the cost ceilings.
      metrics: [
        { id: 'tmp', prefix: 'tmp/' },
        { id: 'logs', prefix: 'logs/' },
      ],
      cors: [{
        allowedMethods: [s3.HttpMethods.GET, s3.HttpMethods.PUT, s3.HttpMethods.POST],
        allowedOrigins,
        allowedHeaders: ['*'],
        exposedHeaders: ['ETag'],
      }],
    });
    this.imagesBucketName = imagesBucket.bucketName;

    const webAppBucket = new s3.Bucket(this, 'WhiskeyWebAppBucket', {
      ...bucketDefaults,
      bucketName: `whiskey-webapp-${environment}-${this.account}`,
    });

    const responseHeadersPolicy = new cloudfront.ResponseHeadersPolicy(this, 'SecurityHeadersPolicy', {
      responseHeadersPolicyName: `whiskey-security-headers-${environment}`,
      securityHeadersBehavior: {
        strictTransportSecurity: {
          accessControlMaxAge: cdk.Duration.days(730),
          includeSubdomains: true,
          preload: true,
          override: true,
        },
        contentTypeOptions: { override: true },
        // X-Frame-Options DENY is the non-CSP equivalent of frame-ancestors 'none'.
        // The content-dependent CSP remains owned by the frontend build.
        frameOptions: { frameOption: cloudfront.HeadersFrameOption.DENY, override: true },
        referrerPolicy: {
          referrerPolicy: cloudfront.HeadersReferrerPolicy.STRICT_ORIGIN_WHEN_CROSS_ORIGIN,
          override: true,
        },
      },
    });

    const webCertificate = enableCustomDomain
      ? acm.Certificate.fromCertificateArn(this, 'WebCertificate', props.cloudFrontCertificateArn!)
      : undefined;

    const distribution = new cloudfront.Distribution(this, 'WhiskeyWebDistribution', {
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(webAppBucket),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        allowedMethods: cloudfront.AllowedMethods.ALLOW_GET_HEAD,
        cachedMethods: cloudfront.CachedMethods.CACHE_GET_HEAD,
        cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
        responseHeadersPolicy,
      },
      defaultRootObject: 'index.html',
      errorResponses: [
        { httpStatus: 404, responseHttpStatus: 200, responsePagePath: '/index.html' },
        { httpStatus: 403, responseHttpStatus: 200, responsePagePath: '/index.html' },
      ],
      ...(enableCustomDomain ? {
        domainNames: [envConfig.domain!],
        certificate: webCertificate,
      } : {}),
    });

    const whiskeySearchTable = new dynamodb.Table(this, 'WhiskeySearchTable', {
      tableName: tableNames.whiskeySearch,
      partitionKey: { name: 'id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy,
    });
    whiskeySearchTable.addGlobalSecondaryIndex({
      indexName: 'NameIndex',
      partitionKey: { name: 'normalized_name', type: dynamodb.AttributeType.STRING },
    });
    const appStateTable = new dynamodb.Table(this, 'AppStateTable', {
      tableName: tableNames.appState,
      partitionKey: { name: 'pk', type: dynamodb.AttributeType.STRING },
      timeToLiveAttribute: 'ttl',
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy,
    });
    const drinkLogsTable = new dynamodb.Table(this, 'DrinkLogsTable', {
      tableName: tableNames.drinkLogs,
      partitionKey: { name: 'id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy,
    });
    drinkLogsTable.addGlobalSecondaryIndex({
      indexName: 'UserDatetimeIndex',
      partitionKey: { name: 'user_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'datetime', type: dynamodb.AttributeType.STRING },
    });

    const placesSecret = secretsmanager.Secret.fromSecretNameV2(
      this,
      'PlacesSecret',
      `whiskey-places-${environment}`,
    );

    const userPool = new cognito.UserPool(this, 'WhiskeyUserPool', {
      userPoolName: `whiskey-users-${environment}`,
      selfSignUpEnabled: true,
      signInAliases: { email: true, username: true },
      autoVerify: { email: true },
      standardAttributes: {
        email: { required: true, mutable: true },
        givenName: { required: false, mutable: true },
        familyName: { required: false, mutable: true },
      },
      passwordPolicy: {
        minLength: 8,
        requireLowercase: true,
        requireUppercase: true,
        requireDigits: true,
        requireSymbols: false,
      },
      accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
      removalPolicy,
    });

    new cognito.UserPoolDomain(this, 'WhiskeyUserPoolDomain', {
      userPool,
      cognitoDomain: { domainPrefix: envConfig.cognitoDomainPrefix },
    });

    let googleProvider: cognito.UserPoolIdentityProviderGoogle | undefined;
    if (enableGoogleAuth) {
      const googleClientId = ssm.StringParameter.valueForStringParameter(
        this,
        `/whiskey/${environment}/google-client-id`,
      );
      const googleSecret = secretsmanager.Secret.fromSecretNameV2(
        this,
        'GoogleClientSecret',
        `whiskey-app-secrets-${environment}`,
      );
      googleProvider = new cognito.UserPoolIdentityProviderGoogle(this, 'GoogleProvider', {
        userPool,
        clientId: googleClientId,
        clientSecretValue: googleSecret.secretValueFromJson('GOOGLE_CLIENT_SECRET'),
        scopes: ['email', 'profile', 'openid'],
        attributeMapping: {
          email: cognito.ProviderAttribute.GOOGLE_EMAIL,
          givenName: cognito.ProviderAttribute.GOOGLE_GIVEN_NAME,
          familyName: cognito.ProviderAttribute.GOOGLE_FAMILY_NAME,
          profilePicture: cognito.ProviderAttribute.GOOGLE_PICTURE,
        },
      });
    }

    const callbackUrls = allowedOrigins.flatMap((origin) => [origin, `${origin}/auth/callback`]);
    const userPoolClient = new cognito.UserPoolClient(this, 'WhiskeyUserPoolClient', {
      userPool,
      userPoolClientName: `whiskey-app-client-${environment}`,
      generateSecret: false,
      authFlows: { userSrp: true, userPassword: false },
      preventUserExistenceErrors: true,
      supportedIdentityProviders: [
        cognito.UserPoolClientIdentityProvider.COGNITO,
        ...(enableGoogleAuth ? [cognito.UserPoolClientIdentityProvider.GOOGLE] : []),
      ],
      oAuth: {
        flows: { authorizationCodeGrant: true },
        scopes: [cognito.OAuthScope.EMAIL, cognito.OAuthScope.PROFILE, cognito.OAuthScope.OPENID],
        callbackUrls,
        logoutUrls: allowedOrigins,
      },
      refreshTokenValidity: cdk.Duration.days(30),
      accessTokenValidity: cdk.Duration.hours(1),
      idTokenValidity: cdk.Duration.hours(1),
    });
    if (googleProvider) {
      userPoolClient.node.addDependency(googleProvider);
    }

    const logRemovalPolicy = retainResources ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY;
    const logRetention = retainResources ? logs.RetentionDays.ONE_MONTH : logs.RetentionDays.ONE_WEEK;
    const listLogGroup = new logs.LogGroup(this, 'WhiskeyListLogGroup', {
      logGroupName: `/whiskey/${environment}/whiskeys-list`,
      retention: logRetention,
      removalPolicy: logRemovalPolicy,
    });
    const searchLogGroup = new logs.LogGroup(this, 'WhiskeySearchLogGroup', {
      logGroupName: `/whiskey/${environment}/whiskeys-search`,
      retention: logRetention,
      removalPolicy: logRemovalPolicy,
    });
    const drinkLogsLogGroup = new logs.LogGroup(this, 'DrinkLogsLogGroup', {
      logGroupName: `/whiskey/${environment}/drink-logs`,
      retention: logRetention,
      removalPolicy: logRemovalPolicy,
    });
    const drinkLogAnalyzeLogGroup = new logs.LogGroup(this, 'DrinkLogAnalyzeLogGroup', {
      logGroupName: `/whiskey/${environment}/drink-log-analyze`,
      retention: logRetention,
      removalPolicy: logRemovalPolicy,
    });
    const drinkLogPlacesLogGroup = new logs.LogGroup(this, 'DrinkLogPlacesLogGroup', {
      logGroupName: `/whiskey/${environment}/drink-log-places`,
      retention: logRetention,
      removalPolicy: logRemovalPolicy,
    });
    const drinkLogReconcilerLogGroup = new logs.LogGroup(this, 'DrinkLogReconcilerLogGroup', {
      logGroupName: `/whiskey/${environment}/drink-log-reconciler`,
      retention: logRetention,
      removalPolicy: logRemovalPolicy,
    });

    const createLambdaRole = (id: string, roleName: string, logGroup: logs.ILogGroup): iam.Role => {
      const role = new iam.Role(this, id, {
        roleName,
        assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      });
      logGroup.grantWrite(role);
      return role;
    };

    const listRole = createLambdaRole('WhiskeyListRole', `whiskey-list-role-${environment}`, listLogGroup);
    const searchRole = createLambdaRole('WhiskeySearchRole', `whiskey-search-role-${environment}`, searchLogGroup);
    const drinkLogsRole = createLambdaRole(
      'DrinkLogsRole',
      `drink-logs-role-${environment}`,
      drinkLogsLogGroup,
    );
    const drinkLogAnalyzeRole = createLambdaRole(
      'DrinkLogAnalyzeRole',
      `drink-log-analyze-role-${environment}`,
      drinkLogAnalyzeLogGroup,
    );
    const drinkLogPlacesRole = createLambdaRole(
      'DrinkLogPlacesRole',
      `drink-log-places-role-${environment}`,
      drinkLogPlacesLogGroup,
    );
    const drinkLogReconcilerRole = createLambdaRole(
      'DrinkLogReconcilerRole',
      `drink-log-reconciler-role-${environment}`,
      drinkLogReconcilerLogGroup,
    );

    whiskeySearchTable.grantReadData(listRole);
    whiskeySearchTable.grantReadData(searchRole);

    const appStatePrefixStatement = (
      actions: string[],
      prefixes: string | string[],
    ): iam.PolicyStatement => new iam.PolicyStatement({
      actions,
      resources: [appStateTable.tableArn],
      conditions: {
        'ForAllValues:StringLike': {
          'dynamodb:LeadingKeys': Array.isArray(prefixes) ? prefixes : [prefixes],
        },
        Null: { 'dynamodb:LeadingKeys': 'false' },
      },
    });

    listRole.addToPolicy(appStatePrefixStatement(['dynamodb:UpdateItem'], SCAN_COUNTER_PREFIX));
    searchRole.addToPolicy(appStatePrefixStatement(['dynamodb:UpdateItem'], SCAN_COUNTER_PREFIX));

    drinkLogsTable.grantReadWriteData(drinkLogsRole);
    whiskeySearchTable.grantReadData(drinkLogsRole);
    drinkLogsRole.addToPolicy(new iam.PolicyStatement({
      actions: ['s3:GetObject', 's3:PutObject', 's3:DeleteObject'],
      resources: [imagesBucket.arnForObjects('tmp/*'), imagesBucket.arnForObjects('logs/*')],
    }));
    // create の削除確認（_object_absent）が head_object で 404 を得るには ListBucket が
    // 必要。無いと存在しないオブジェクトへの HeadObject が 403（存在秘匿）になり、
    // 404 前提の不在判定が誤って例外→500 になる。プレフィックスで tmp/logs に限定。
    drinkLogsRole.addToPolicy(new iam.PolicyStatement({
      actions: ['s3:ListBucket'],
      resources: [imagesBucket.bucketArn],
      conditions: { StringLike: { 's3:prefix': ['logs/*', 'tmp/*'] } },
    }));
    drinkLogsRole.addToPolicy(appStatePrefixStatement(
      ['dynamodb:UpdateItem'],
      [DRINKLOG_COUNTER_PREFIX, DRINKLOG_QUOTA_PREFIX],
    ));
    drinkLogsRole.addToPolicy(appStatePrefixStatement(
      ['dynamodb:GetItem', 'dynamodb:UpdateItem', 'dynamodb:DeleteItem'],
      AI_RESULT_PREFIX,
    ));

    whiskeySearchTable.grantReadData(drinkLogAnalyzeRole);
    drinkLogAnalyzeRole.addToPolicy(new iam.PolicyStatement({
      actions: ['s3:GetObject'],
      resources: [imagesBucket.arnForObjects('tmp/*')],
    }));
    drinkLogAnalyzeRole.addToPolicy(appStatePrefixStatement(
      ['dynamodb:GetItem', 'dynamodb:UpdateItem'],
      DRINKLOG_COUNTER_PREFIX,
    ));
    // analyze は解析結果キャッシュを put_item（全項目の新規書き込み）で保存するため
    // PutItem が必要。UpdateItem では AccessDenied になる（実コード lambda/drink-log-analyze
    // /index.py の put_item と一致させる）。
    drinkLogAnalyzeRole.addToPolicy(appStatePrefixStatement(
      ['dynamodb:PutItem'],
      AI_RESULT_PREFIX,
    ));

    drinkLogPlacesRole.addToPolicy(new iam.PolicyStatement({
      actions: ['dynamodb:BatchGetItem'],
      resources: [drinkLogsTable.tableArn],
    }));
    drinkLogPlacesRole.addToPolicy(appStatePrefixStatement(
      ['dynamodb:GetItem', 'dynamodb:UpdateItem'],
      DRINKLOG_COUNTER_PREFIX,
    ));
    placesSecret.grantRead(drinkLogPlacesRole);

    drinkLogsTable.grantReadWriteData(drinkLogReconcilerRole);
    drinkLogReconcilerRole.addToPolicy(new iam.PolicyStatement({
      actions: ['s3:ListBucket'],
      resources: [imagesBucket.bucketArn],
      conditions: { StringLike: { 's3:prefix': ['logs/*', 'tmp/*'] } },
    }));
    drinkLogReconcilerRole.addToPolicy(new iam.PolicyStatement({
      actions: ['s3:GetObject', 's3:DeleteObject'],
      resources: [imagesBucket.arnForObjects('logs/*'), imagesBucket.arnForObjects('tmp/*')],
    }));
    drinkLogReconcilerRole.addToPolicy(appStatePrefixStatement(
      ['dynamodb:UpdateItem'],
      DRINKLOG_QUOTA_PREFIX,
    ));

    const bedrockModels: readonly BedrockModel[] = [
      {
        type: 'profile',
        profileArn: `arn:aws:bedrock:${this.region}:${this.account}:inference-profile/jp.amazon.nova-2-lite-v1:0`,
        destinationArns: [
          'arn:aws:bedrock:ap-northeast-1::foundation-model/amazon.nova-2-lite-v1:0',
          'arn:aws:bedrock:ap-northeast-3::foundation-model/amazon.nova-2-lite-v1:0',
        ],
      },
      {
        type: 'profile',
        profileArn: `arn:aws:bedrock:${this.region}:${this.account}:inference-profile/jp.anthropic.claude-haiku-4-5-20251001-v1:0`,
        destinationArns: [
          'arn:aws:bedrock:ap-northeast-1::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0',
          'arn:aws:bedrock:ap-northeast-3::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0',
        ],
      },
      {
        type: 'profile',
        profileArn: `arn:aws:bedrock:${this.region}:${this.account}:inference-profile/jp.anthropic.claude-sonnet-4-6`,
        destinationArns: [
          'arn:aws:bedrock:ap-northeast-1::foundation-model/anthropic.claude-sonnet-4-6',
          'arn:aws:bedrock:ap-northeast-3::foundation-model/anthropic.claude-sonnet-4-6',
        ],
      },
    ];
    for (const statement of bedrockInvokeStatements(bedrockModels)) {
      drinkLogAnalyzeRole.addToPolicy(statement);
    }

    const bundledPythonCode = (directory: string): lambda.AssetCode => {
      const sourceDirectory = path.join(__dirname, '..', '..', 'lambda', directory);
      return lambda.Code.fromAsset(sourceDirectory, {
        bundling: {
          image: lambda.Runtime.PYTHON_3_11.bundlingImage,
          platform: 'linux/amd64',
          command: ['bash', '-c', BUNDLING_COMMAND],
          // Jest and template-only npm synth commands copy sources locally so they
          // remain usable where the Docker daemon is intentionally unavailable.
          // deploy.sh does not set CDK_LOCAL_BUNDLING and keeps the Python 3.11
          // Docker bundling path for deployable assets.
          ...(process.env.NODE_ENV === 'test' || process.env.CDK_LOCAL_BUNDLING === '1' ? {
            local: {
              tryBundle(outputDirectory: string): boolean {
                for (const entry of fs.readdirSync(sourceDirectory)) {
                  fs.cpSync(
                    path.join(sourceDirectory, entry),
                    path.join(outputDirectory, entry),
                    { recursive: true },
                  );
                }
                return true;
              },
            },
          } : {}),
        },
      });
    };

    const commonLayer = new lambda.LayerVersion(this, 'WhiskeyCommonLayer', {
      layerVersionName: `whiskey-common-${environment}`,
      description: 'Shared logging, responses, JWT, normalization, and AWS clients',
      compatibleArchitectures: [lambda.Architecture.X86_64],
      compatibleRuntimes: [lambda.Runtime.PYTHON_3_11],
      code: bundledPythonCode('common'),
    });

    const authenticatedDrinkLogEnvironment = {
      ENVIRONMENT: environment,
      APP_STATE_TABLE: appStateTable.tableName,
      DRINKLOGS_TABLE: drinkLogsTable.tableName,
      IMAGES_BUCKET: imagesBucket.bucketName,
      ALLOWED_ORIGINS: allowedOrigins.join(','),
      COGNITO_USER_POOL_ID: userPool.userPoolId,
      COGNITO_CLIENT_ID: userPoolClient.userPoolClientId,
    };

    const whiskeyListLambda = new lambda.Function(this, 'WhiskeyListFunction', {
      functionName: lambdaFunctionNames.whiskeyList,
      runtime: lambda.Runtime.PYTHON_3_11,
      architecture: lambda.Architecture.X86_64,
      handler: 'index.lambda_handler',
      code: bundledPythonCode('whiskeys-list'),
      layers: [commonLayer],
      timeout: cdk.Duration.seconds(15),
      memorySize: 256,
      role: listRole,
      logGroup: listLogGroup,
      environment: {
        WHISKEYS_TABLE: whiskeySearchTable.tableName,
        APP_STATE_TABLE: appStateTable.tableName,
        PUBLIC_SCAN_MAX_PAGES: '1',
        PUBLIC_SCAN_DAILY_LIMIT: '10000',
        ALLOWED_ORIGINS: allowedOrigins.join(','),
        ENVIRONMENT: environment,
      },
    });

    const whiskeySearchLambda = new lambda.Function(this, 'WhiskeySearchFunction', {
      functionName: lambdaFunctionNames.whiskeySearch,
      runtime: lambda.Runtime.PYTHON_3_11,
      architecture: lambda.Architecture.X86_64,
      handler: 'index.lambda_handler',
      code: bundledPythonCode('whiskeys-search'),
      layers: [commonLayer],
      timeout: cdk.Duration.seconds(15),
      memorySize: 256,
      role: searchRole,
      logGroup: searchLogGroup,
      environment: {
        WHISKEYS_TABLE: whiskeySearchTable.tableName,
        WHISKEY_SEARCH_TABLE: whiskeySearchTable.tableName,
        APP_STATE_TABLE: appStateTable.tableName,
        PUBLIC_SCAN_MAX_PAGES: '5',
        PUBLIC_SCAN_PAGE_SIZE: '250',
        PUBLIC_SCAN_DAILY_LIMIT: '10000',
        ALLOWED_ORIGINS: allowedOrigins.join(','),
        ENVIRONMENT: environment,
      },
    });

    const drinkLogsLambda = new lambda.Function(this, 'DrinkLogsFunction', {
      functionName: lambdaFunctionNames.drinkLogs,
      runtime: lambda.Runtime.PYTHON_3_11,
      architecture: lambda.Architecture.X86_64,
      handler: 'index.lambda_handler',
      code: bundledPythonCode('drink-logs'),
      layers: [commonLayer],
      timeout: cdk.Duration.seconds(25),
      memorySize: 1024,
      reservedConcurrentExecutions: envConfig.lambdaReservedConcurrency?.drinkLogs,
      role: drinkLogsRole,
      logGroup: drinkLogsLogGroup,
      environment: {
        ...authenticatedDrinkLogEnvironment,
        WHISKEY_SEARCH_TABLE: whiskeySearchTable.tableName,
        UPLOAD_USER_DAILY_LIMIT: '30',
        UPLOAD_GLOBAL_DAILY_LIMIT: '100',
        CREATE_USER_DAILY_LIMIT: '30',
        CREATE_GLOBAL_DAILY_LIMIT: '100',
        STORAGE_USER_LIMIT: '2000',
        STORAGE_GLOBAL_LIMIT: '20000',
        IMAGE_MAX_BYTES: '1572864',
        UPLOAD_MAX_BYTES: '3670016',
      },
    });

    const drinkLogAnalyzeLambda = new lambda.Function(this, 'DrinkLogAnalyzeFunction', {
      functionName: lambdaFunctionNames.drinkLogAnalyze,
      runtime: lambda.Runtime.PYTHON_3_11,
      architecture: lambda.Architecture.X86_64,
      handler: 'index.lambda_handler',
      code: bundledPythonCode('drink-log-analyze'),
      layers: [commonLayer],
      timeout: cdk.Duration.seconds(28),
      memorySize: 1024,
      reservedConcurrentExecutions: envConfig.lambdaReservedConcurrency?.analyze,
      role: drinkLogAnalyzeRole,
      logGroup: drinkLogAnalyzeLogGroup,
      environment: {
        ...authenticatedDrinkLogEnvironment,
        WHISKEY_SEARCH_TABLE: whiskeySearchTable.tableName,
        BEDROCK_MODEL_ID: 'jp.anthropic.claude-sonnet-4-6',
        BEDROCK_MODEL_ALLOWLIST: bedrockModelAllowlist(bedrockModels).join(','),
        ANALYZE_USER_DAILY_LIMIT: '20',
        ANALYZE_GLOBAL_DAILY_LIMIT: '50',
        ANALYZE_GLOBAL_MONTHLY_LIMIT: '1000',
        IMAGE_MAX_BYTES: '1572864',
        UPLOAD_MAX_BYTES: '3670016',
      },
    });

    const drinkLogPlacesLambda = new lambda.Function(this, 'DrinkLogPlacesFunction', {
      functionName: lambdaFunctionNames.drinkLogPlaces,
      runtime: lambda.Runtime.PYTHON_3_11,
      architecture: lambda.Architecture.X86_64,
      handler: 'places.lambda_handler',
      code: bundledPythonCode('drink-log-analyze'),
      layers: [commonLayer],
      timeout: cdk.Duration.seconds(10),
      memorySize: 256,
      reservedConcurrentExecutions: envConfig.lambdaReservedConcurrency?.places,
      role: drinkLogPlacesRole,
      logGroup: drinkLogPlacesLogGroup,
      environment: {
        ...authenticatedDrinkLogEnvironment,
        PLACES_USER_DAILY_LIMIT: '30',
        PLACES_GLOBAL_DAILY_LIMIT: '15',
        PLACES_GLOBAL_MONTHLY_LIMIT: '150',
        PLACES_SECRET_NAME: `whiskey-places-${environment}`,
      },
    });

    const drinkLogReconcilerLambda = new lambda.Function(this, 'DrinkLogReconcilerFunction', {
      functionName: lambdaFunctionNames.drinkLogReconciler,
      runtime: lambda.Runtime.PYTHON_3_11,
      architecture: lambda.Architecture.X86_64,
      handler: 'reconciler.lambda_handler',
      code: bundledPythonCode('drink-logs'),
      layers: [commonLayer],
      timeout: cdk.Duration.seconds(300),
      memorySize: 512,
      reservedConcurrentExecutions: envConfig.lambdaReservedConcurrency?.reconciler,
      role: drinkLogReconcilerRole,
      logGroup: drinkLogReconcilerLogGroup,
      environment: {
        ENVIRONMENT: environment,
        DRINKLOGS_TABLE: drinkLogsTable.tableName,
        IMAGES_BUCKET: imagesBucket.bucketName,
        APP_STATE_TABLE: appStateTable.tableName,
        RECONCILE_AGE_HOURS: '48',
      },
    });
    this.drinkLogReconcilerFunctionName = drinkLogReconcilerLambda.functionName;

    const drinkLogReconcilerScheduleDlq = new sqs.Queue(this, 'DrinkLogReconcilerScheduleDlq', {
      queueName: `drink-log-reconciler-dlq-${environment}`,
      encryption: sqs.QueueEncryption.SQS_MANAGED,
      retentionPeriod: cdk.Duration.days(14),
      removalPolicy,
    });
    const drinkLogReconcilerScheduleGroup = new scheduler.CfnScheduleGroup(
      this,
      'DrinkLogReconcilerScheduleGroup',
      { name: `drink-log-reconciler-${environment}` },
    );
    const drinkLogReconcilerScheduleRole = new iam.Role(this, 'DrinkLogReconcilerScheduleTargetRole', {
      roleName: `drink-log-reconciler-scheduler-target-role-${environment}`,
      assumedBy: new iam.ServicePrincipal('scheduler.amazonaws.com', {
        conditions: {
          ArnEquals: { 'aws:SourceArn': drinkLogReconcilerScheduleGroup.attrArn },
          StringEquals: { 'aws:SourceAccount': this.account },
        },
      }),
    });
    drinkLogReconcilerScheduleRole.addToPolicy(new iam.PolicyStatement({
      actions: ['lambda:InvokeFunction'],
      resources: [drinkLogReconcilerLambda.functionArn],
    }));
    drinkLogReconcilerScheduleRole.addToPolicy(new iam.PolicyStatement({
      actions: ['sqs:SendMessage'],
      resources: [drinkLogReconcilerScheduleDlq.queueArn],
    }));
    const drinkLogReconcilerSchedule = new scheduler.CfnSchedule(this, 'DrinkLogReconcilerSchedule', {
      name: `drink-log-reconciler-daily-${environment}`,
      groupName: drinkLogReconcilerScheduleGroup.name,
      scheduleExpression: 'rate(1 day)',
      flexibleTimeWindow: { mode: 'OFF' },
      target: {
        arn: drinkLogReconcilerLambda.functionArn,
        roleArn: drinkLogReconcilerScheduleRole.roleArn,
        input: '{}',
        deadLetterConfig: { arn: drinkLogReconcilerScheduleDlq.queueArn },
        retryPolicy: {
          maximumEventAgeInSeconds: 3600,
          maximumRetryAttempts: 3,
        },
      },
    });
    drinkLogReconcilerSchedule.addDependency(drinkLogReconcilerScheduleGroup);

    let apiCertificate: acm.Certificate | undefined;
    if (enableCustomDomain) {
      apiCertificate = new acm.Certificate(this, 'ApiCertificate', {
        domainName: envConfig.apiDomain!,
        validation: acm.CertificateValidation.fromDns(props.hostedZone),
      });
    }

    const api = new apigateway.RestApi(this, 'WhiskeyApi', {
      restApiName: this.restApiName,
      description: `Whiskey API for ${environment} environment`,
      endpointTypes: [apigateway.EndpointType.REGIONAL],
      cloudWatchRole: true,
      deployOptions: {
        stageName: environment,
        loggingLevel: apigateway.MethodLoggingLevel.INFO,
        dataTraceEnabled: false,
        metricsEnabled: true,
        // API Gateway throttles are best-effort protections, not guaranteed ceilings; AppState counters enforce limits.
        methodOptions: {
          '/api/whiskeys/GET': { throttlingRateLimit: 5, throttlingBurstLimit: 10 },
          '/api/whiskeys/search/GET': { throttlingRateLimit: 5, throttlingBurstLimit: 10 },
          '/api/whiskeys/suggest/GET': { throttlingRateLimit: 5, throttlingBurstLimit: 10 },
          '/api/whiskeys/search/suggest/GET': { throttlingRateLimit: 5, throttlingBurstLimit: 10 },
          '/api/drink-logs/upload-url/POST': { throttlingRateLimit: 2, throttlingBurstLimit: 5 },
          '/api/drink-logs/analyze/POST': { throttlingRateLimit: 2, throttlingBurstLimit: 5 },
          '/api/drink-logs/places/POST': { throttlingRateLimit: 2, throttlingBurstLimit: 5 },
          '/api/drink-logs/places/resolve/POST': { throttlingRateLimit: 2, throttlingBurstLimit: 5 },
          '/api/drink-logs/POST': { throttlingRateLimit: 2, throttlingBurstLimit: 5 },
          '/api/drink-logs/GET': { throttlingRateLimit: 5, throttlingBurstLimit: 10 },
          '/api/drink-logs/{id}/GET': { throttlingRateLimit: 5, throttlingBurstLimit: 10 },
          '/api/drink-logs/{id}/PUT': { throttlingRateLimit: 2, throttlingBurstLimit: 5 },
          '/api/drink-logs/{id}/DELETE': { throttlingRateLimit: 2, throttlingBurstLimit: 5 },
        },
      },
      defaultCorsPreflightOptions: {
        allowOrigins: allowedOrigins,
        allowMethods: apigateway.Cors.ALL_METHODS,
        allowHeaders: [
          'Content-Type',
          'X-Amz-Date',
          'Authorization',
          'X-Api-Key',
          'X-Amz-Security-Token',
          'X-Requested-With',
        ],
        allowCredentials: false,
      },
      ...(enableCustomDomain ? {
        domainName: {
          domainName: envConfig.apiDomain!,
          certificate: apiCertificate!,
          endpointType: apigateway.EndpointType.REGIONAL,
          securityPolicy: apigateway.SecurityPolicy.TLS_1_2,
        },
      } : {}),
    });

    const authorizer = new apigateway.CognitoUserPoolsAuthorizer(this, 'CognitoAuthorizer', {
      cognitoUserPools: [userPool],
      identitySource: apigateway.IdentitySource.header('Authorization'),
    });
    const cfnAuthorizer = authorizer.node.defaultChild as apigateway.CfnAuthorizer;
    cfnAuthorizer.identityValidationExpression = `^${userPoolClient.userPoolClientId}$`;

    const gatewayResponseHeaders = {
      'Access-Control-Allow-Origin': `'${envConfig.gatewayErrorOrigin}'`,
      'Access-Control-Allow-Headers': "'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token,X-Requested-With'",
      'Access-Control-Allow-Methods': "'GET,POST,PUT,DELETE,OPTIONS'",
    };
    [
      apigateway.ResponseType.UNAUTHORIZED,
      apigateway.ResponseType.ACCESS_DENIED,
      apigateway.ResponseType.DEFAULT_4XX,
      apigateway.ResponseType.DEFAULT_5XX,
    ].forEach((type, index) => {
      api.addGatewayResponse(`CorsGatewayResponse${index}`, {
        type,
        responseHeaders: gatewayResponseHeaders,
      });
    });

    const integration = (handler: lambda.IFunction): apigateway.LambdaIntegration =>
      new apigateway.LambdaIntegration(handler, { timeout: API_TIMEOUT });
    const authenticated = {
      authorizationType: apigateway.AuthorizationType.COGNITO,
      authorizer,
    };
    const publicMethod = { authorizationType: apigateway.AuthorizationType.NONE };

    const apiResource = api.root.addResource('api');
    const whiskeysResource = apiResource.addResource('whiskeys');
    whiskeysResource.addMethod('GET', integration(whiskeyListLambda), publicMethod);
    const whiskeySearchResource = whiskeysResource.addResource('search');
    whiskeySearchResource.addMethod('GET', integration(whiskeySearchLambda), publicMethod);
    whiskeysResource.addResource('suggest').addMethod('GET', integration(whiskeySearchLambda), publicMethod);
    whiskeySearchResource.addResource('suggest').addMethod('GET', integration(whiskeySearchLambda), publicMethod);

    const drinkLogsResource = apiResource.addResource('drink-logs');
    drinkLogsResource.addMethod('POST', integration(drinkLogsLambda), authenticated);
    drinkLogsResource.addMethod('GET', integration(drinkLogsLambda), authenticated);
    drinkLogsResource.addResource('upload-url').addMethod(
      'POST',
      integration(drinkLogsLambda),
      authenticated,
    );
    drinkLogsResource.addResource('analyze').addMethod(
      'POST',
      integration(drinkLogAnalyzeLambda),
      authenticated,
    );
    const drinkLogPlacesResource = drinkLogsResource.addResource('places');
    drinkLogPlacesResource.addMethod('POST', integration(drinkLogPlacesLambda), authenticated);
    drinkLogPlacesResource.addResource('resolve').addMethod(
      'POST',
      integration(drinkLogPlacesLambda),
      authenticated,
    );
    const drinkLogByIdResource = drinkLogsResource.addResource('{id}');
    drinkLogByIdResource.addMethod('GET', integration(drinkLogsLambda), authenticated);
    drinkLogByIdResource.addMethod('PUT', integration(drinkLogsLambda), authenticated);
    drinkLogByIdResource.addMethod('DELETE', integration(drinkLogsLambda), authenticated);

    if (enableCustomDomain) {
      new route53.ARecord(this, 'DomainARecord', {
        zone: props.hostedZone!,
        recordName: envConfig.domain!,
        target: route53.RecordTarget.fromAlias(new targets.CloudFrontTarget(distribution)),
      });
      new route53.ARecord(this, 'ApiDomainARecord', {
        zone: props.hostedZone!,
        recordName: envConfig.apiDomain!,
        target: route53.RecordTarget.fromAlias(new targets.ApiGateway(api)),
      });
    }

    const hostedUiHostname = `${envConfig.cognitoDomainPrefix}.auth.${this.region}.amazoncognito.com`;
    new cdk.CfnOutput(this, 'UserPoolId', { value: userPool.userPoolId });
    new cdk.CfnOutput(this, 'UserPoolClientId', { value: userPoolClient.userPoolClientId });
    new cdk.CfnOutput(this, 'CognitoHostedUiHostname', { value: hostedUiHostname });
    new cdk.CfnOutput(this, 'GoogleAuthorizedRedirectUri', {
      value: `https://${hostedUiHostname}/oauth2/idpresponse`,
    });
    new cdk.CfnOutput(this, 'ImagesBucketName', { value: imagesBucket.bucketName });
    new cdk.CfnOutput(this, 'WebAppBucketName', { value: webAppBucket.bucketName });
    new cdk.CfnOutput(this, 'CloudFrontDistributionId', { value: distribution.distributionId });
    new cdk.CfnOutput(this, 'CloudFrontDomainName', { value: distribution.distributionDomainName });
    new cdk.CfnOutput(this, 'WhiskeysTableName', { value: whiskeySearchTable.tableName });
    new cdk.CfnOutput(this, 'AppStateTableName', { value: appStateTable.tableName });
    new cdk.CfnOutput(this, 'DrinkLogsTableName', { value: drinkLogsTable.tableName });
    new cdk.CfnOutput(this, 'WhiskeyListRoleArn', { value: listRole.roleArn });
    new cdk.CfnOutput(this, 'WhiskeySearchRoleArn', { value: searchRole.roleArn });
    new cdk.CfnOutput(this, 'DrinkLogsRoleArn', { value: drinkLogsRole.roleArn });
    new cdk.CfnOutput(this, 'DrinkLogAnalyzeRoleArn', { value: drinkLogAnalyzeRole.roleArn });
    new cdk.CfnOutput(this, 'DrinkLogPlacesRoleArn', { value: drinkLogPlacesRole.roleArn });
    new cdk.CfnOutput(this, 'DrinkLogReconcilerRoleArn', { value: drinkLogReconcilerRole.roleArn });
    new cdk.CfnOutput(this, 'PlacesSecretArn', { value: placesSecret.secretArn });
    new cdk.CfnOutput(this, 'WhiskeyListLambdaArn', { value: whiskeyListLambda.functionArn });
    new cdk.CfnOutput(this, 'WhiskeySearchLambdaArn', { value: whiskeySearchLambda.functionArn });
    new cdk.CfnOutput(this, 'DrinkLogsLambdaArn', { value: drinkLogsLambda.functionArn });
    new cdk.CfnOutput(this, 'DrinkLogAnalyzeLambdaArn', { value: drinkLogAnalyzeLambda.functionArn });
    new cdk.CfnOutput(this, 'DrinkLogPlacesLambdaArn', { value: drinkLogPlacesLambda.functionArn });
    new cdk.CfnOutput(this, 'DrinkLogReconcilerLambdaArn', { value: drinkLogReconcilerLambda.functionArn });
    new cdk.CfnOutput(this, 'ApiGatewayRestApiId', { value: api.restApiId });
    new cdk.CfnOutput(this, 'ApiGatewayUrl', { value: api.url });

    if (enableCustomDomain) {
      new cdk.CfnOutput(this, 'CustomDomainName', { value: envConfig.domain! });
      new cdk.CfnOutput(this, 'WebsiteUrl', { value: `https://${envConfig.domain}` });
      new cdk.CfnOutput(this, 'ApiDomainName', { value: envConfig.apiDomain! });
      new cdk.CfnOutput(this, 'ApiUrl', { value: `https://${envConfig.apiDomain}` });
    }
  }
}
