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

export interface WhiskeyInfraStackProps extends cdk.StackProps {
  environment: string;
  enableCustomDomain?: boolean;
  enableGoogleAuth?: boolean;
  hostedZone?: route53.IHostedZone;
  cloudFrontCertificateArn?: string;
}

const API_TIMEOUT = cdk.Duration.seconds(29);
const SCAN_COUNTER_PREFIX = 'scan-counter/*';
const RANKING_CACHE_PREFIX = 'ranking-cache/*';
const REVIEW_RATE_PREFIX = 'review-rate#*';
const REVIEW_CHANGE_COUNTER = 'review-change-counter';
const WHISKEY_CHANGE_COUNTER = 'whiskey-change-counter';
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
      cors: [{
        allowedMethods: [s3.HttpMethods.GET, s3.HttpMethods.PUT, s3.HttpMethods.POST],
        allowedOrigins,
        allowedHeaders: ['*'],
        exposedHeaders: ['ETag'],
      }],
    });

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

    const reviewsTable = new dynamodb.Table(this, 'ReviewsTable', {
      tableName: `Reviews-${environment}`,
      partitionKey: { name: 'id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy,
    });
    reviewsTable.addGlobalSecondaryIndex({
      indexName: 'UserDateIndex',
      partitionKey: { name: 'user_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'date', type: dynamodb.AttributeType.STRING },
    });
    reviewsTable.addGlobalSecondaryIndex({
      indexName: 'PublicDateIndex',
      partitionKey: { name: 'public_pk', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'date', type: dynamodb.AttributeType.STRING },
    });

    const whiskeySearchTable = new dynamodb.Table(this, 'WhiskeySearchTable', {
      tableName: `WhiskeySearch-${environment}`,
      partitionKey: { name: 'id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy,
    });
    whiskeySearchTable.addGlobalSecondaryIndex({
      indexName: 'NameIndex',
      partitionKey: { name: 'normalized_name', type: dynamodb.AttributeType.STRING },
    });
    const appStateTable = new dynamodb.Table(this, 'AppStateTable', {
      tableName: `AppState-${environment}`,
      partitionKey: { name: 'pk', type: dynamodb.AttributeType.STRING },
      timeToLiveAttribute: 'ttl',
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy,
    });

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
    const reviewsLogGroup = new logs.LogGroup(this, 'ReviewsLogGroup', {
      logGroupName: `/whiskey/${environment}/reviews`,
      retention: logRetention,
      removalPolicy: logRemovalPolicy,
    });
    const rankingAggregatorLogGroup = new logs.LogGroup(this, 'RankingAggregatorLogGroup', {
      logGroupName: `/whiskey/${environment}/ranking-aggregator`,
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
    const reviewsRole = createLambdaRole('ReviewsRole', `reviews-role-${environment}`, reviewsLogGroup);
    const rankingAggregatorRole = createLambdaRole(
      'RankingAggregatorRole',
      `ranking-aggregator-role-${environment}`,
      rankingAggregatorLogGroup,
    );

    whiskeySearchTable.grantReadData(listRole);
    whiskeySearchTable.grantReadData(searchRole);
    reviewsTable.grantReadWriteData(reviewsRole);
    whiskeySearchTable.grantReadData(reviewsRole);

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
    searchRole.addToPolicy(appStatePrefixStatement(['dynamodb:GetItem'], RANKING_CACHE_PREFIX));
    searchRole.addToPolicy(appStatePrefixStatement(['dynamodb:UpdateItem'], SCAN_COUNTER_PREFIX));
    reviewsRole.addToPolicy(appStatePrefixStatement(['dynamodb:UpdateItem'], SCAN_COUNTER_PREFIX));
    reviewsRole.addToPolicy(appStatePrefixStatement(
      ['dynamodb:UpdateItem'],
      [REVIEW_RATE_PREFIX, REVIEW_CHANGE_COUNTER],
    ));
    reviewsRole.addToPolicy(appStatePrefixStatement(['dynamodb:UpdateItem'], 'ranking-cache/meta'));
    rankingAggregatorRole.addToPolicy(new iam.PolicyStatement({
      actions: ['dynamodb:Scan'],
      resources: [reviewsTable.tableArn, whiskeySearchTable.tableArn],
    }));
    rankingAggregatorRole.addToPolicy(appStatePrefixStatement(
      ['dynamodb:GetItem', 'dynamodb:PutItem', 'dynamodb:UpdateItem', 'dynamodb:DeleteItem'],
      RANKING_CACHE_PREFIX,
    ));
    rankingAggregatorRole.addToPolicy(appStatePrefixStatement(
      ['dynamodb:GetItem'],
      [REVIEW_CHANGE_COUNTER, WHISKEY_CHANGE_COUNTER],
    ));

    const bundledPythonCode = (directory: string): lambda.AssetCode => {
      const sourceDirectory = path.join(__dirname, '..', '..', 'lambda', directory);
      return lambda.Code.fromAsset(sourceDirectory, {
        bundling: {
          image: lambda.Runtime.PYTHON_3_11.bundlingImage,
          platform: 'linux/amd64',
          command: ['bash', '-c', BUNDLING_COMMAND],
          ...(process.env.NODE_ENV === 'test' ? {
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

    const whiskeyListLambda = new lambda.Function(this, 'WhiskeyListFunction', {
      functionName: `whiskey-list-${environment}`,
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
      functionName: `whiskey-search-${environment}`,
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
        REVIEWS_TABLE: reviewsTable.tableName,
        WHISKEY_SEARCH_TABLE: whiskeySearchTable.tableName,
        APP_STATE_TABLE: appStateTable.tableName,
        PUBLIC_SCAN_MAX_PAGES: '1',
        PUBLIC_SCAN_DAILY_LIMIT: '10000',
        ALLOWED_ORIGINS: allowedOrigins.join(','),
        ENVIRONMENT: environment,
      },
    });

    const reviewsLambda = new lambda.Function(this, 'ReviewsFunction', {
      functionName: `reviews-${environment}`,
      runtime: lambda.Runtime.PYTHON_3_11,
      architecture: lambda.Architecture.X86_64,
      handler: 'index.lambda_handler',
      code: bundledPythonCode('reviews'),
      layers: [commonLayer],
      timeout: cdk.Duration.seconds(30),
      memorySize: 512,
      role: reviewsRole,
      logGroup: reviewsLogGroup,
      environment: {
        REVIEWS_TABLE: reviewsTable.tableName,
        WHISKEYS_TABLE: whiskeySearchTable.tableName,
        APP_STATE_TABLE: appStateTable.tableName,
        COGNITO_USER_POOL_ID: userPool.userPoolId,
        COGNITO_CLIENT_ID: userPoolClient.userPoolClientId,
        ALLOWED_ORIGINS: allowedOrigins.join(','),
        REVIEW_DAILY_USER_LIMIT: '100',
        REVIEW_DAILY_GLOBAL_LIMIT: '10000',
        ENVIRONMENT: environment,
      },
    });

    const rankingAggregatorLambda = new lambda.Function(this, 'RankingAggregatorFunction', {
      functionName: `ranking-aggregator-${environment}`,
      runtime: lambda.Runtime.PYTHON_3_11,
      architecture: lambda.Architecture.X86_64,
      handler: 'index.lambda_handler',
      code: bundledPythonCode('ranking-aggregator'),
      layers: [commonLayer],
      timeout: cdk.Duration.seconds(120),
      memorySize: 512,
      reservedConcurrentExecutions: 1,
      role: rankingAggregatorRole,
      logGroup: rankingAggregatorLogGroup,
      environment: {
        REVIEWS_TABLE: reviewsTable.tableName,
        WHISKEY_SEARCH_TABLE: whiskeySearchTable.tableName,
        APP_STATE_TABLE: appStateTable.tableName,
        ENVIRONMENT: environment,
      },
    });

    const rankingScheduleDlq = new sqs.Queue(this, 'RankingScheduleDlq', {
      queueName: `ranking-aggregator-dlq-${environment}`,
      encryption: sqs.QueueEncryption.SQS_MANAGED,
      retentionPeriod: cdk.Duration.days(14),
      removalPolicy,
    });
    const rankingScheduleGroup = new scheduler.CfnScheduleGroup(this, 'RankingScheduleGroup', {
      name: `ranking-aggregator-${environment}`,
    });
    const rankingScheduleRole = new iam.Role(this, 'RankingScheduleTargetRole', {
      roleName: `ranking-scheduler-target-role-${environment}`,
      assumedBy: new iam.ServicePrincipal('scheduler.amazonaws.com', {
        conditions: {
          ArnEquals: { 'aws:SourceArn': rankingScheduleGroup.attrArn },
          StringEquals: { 'aws:SourceAccount': this.account },
        },
      }),
    });
    rankingScheduleRole.addToPolicy(new iam.PolicyStatement({
      actions: ['lambda:InvokeFunction'],
      resources: [rankingAggregatorLambda.functionArn],
    }));
    rankingScheduleRole.addToPolicy(new iam.PolicyStatement({
      actions: ['sqs:SendMessage'],
      resources: [rankingScheduleDlq.queueArn],
    }));
    const rankingSchedule = new scheduler.CfnSchedule(this, 'RankingSchedule', {
      name: `ranking-aggregator-15min-${environment}`,
      groupName: rankingScheduleGroup.name,
      scheduleExpression: 'rate(15 minutes)',
      flexibleTimeWindow: { mode: 'OFF' },
      target: {
        arn: rankingAggregatorLambda.functionArn,
        roleArn: rankingScheduleRole.roleArn,
        input: '{}',
        deadLetterConfig: { arn: rankingScheduleDlq.queueArn },
        retryPolicy: {
          maximumEventAgeInSeconds: 3600,
          maximumRetryAttempts: 3,
        },
      },
    });
    rankingSchedule.addDependency(rankingScheduleGroup);

    let apiCertificate: acm.Certificate | undefined;
    if (enableCustomDomain) {
      apiCertificate = new acm.Certificate(this, 'ApiCertificate', {
        domainName: envConfig.apiDomain!,
        validation: acm.CertificateValidation.fromDns(props.hostedZone),
      });
    }

    const api = new apigateway.RestApi(this, 'WhiskeyApi', {
      restApiName: `whiskey-api-${environment}`,
      description: `Whiskey API for ${environment} environment`,
      endpointTypes: [apigateway.EndpointType.REGIONAL],
      cloudWatchRole: true,
      deployOptions: {
        stageName: environment,
        loggingLevel: apigateway.MethodLoggingLevel.INFO,
        dataTraceEnabled: false,
        metricsEnabled: true,
        methodOptions: {
          '/api/whiskeys/GET': { throttlingRateLimit: 5, throttlingBurstLimit: 10 },
          '/api/whiskeys/search/GET': { throttlingRateLimit: 5, throttlingBurstLimit: 10 },
          '/api/whiskeys/suggest/GET': { throttlingRateLimit: 5, throttlingBurstLimit: 10 },
          '/api/whiskeys/search/suggest/GET': { throttlingRateLimit: 5, throttlingBurstLimit: 10 },
          '/api/whiskeys/ranking/GET': { throttlingRateLimit: 5, throttlingBurstLimit: 10 },
          '/api/reviews/POST': { throttlingRateLimit: 1, throttlingBurstLimit: 5 },
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
    whiskeysResource.addResource('ranking').addMethod('GET', integration(whiskeySearchLambda), publicMethod);

    const reviewsResource = apiResource.addResource('reviews');
    reviewsResource.addMethod('GET', integration(reviewsLambda), authenticated);
    reviewsResource.addMethod('POST', integration(reviewsLambda), authenticated);
    reviewsResource.addResource('public').addMethod('GET', integration(reviewsLambda), publicMethod);
    const reviewByIdResource = reviewsResource.addResource('{id}');
    reviewByIdResource.addMethod('GET', integration(reviewsLambda), authenticated);
    reviewByIdResource.addMethod('PUT', integration(reviewsLambda), authenticated);
    reviewByIdResource.addMethod('DELETE', integration(reviewsLambda), authenticated);

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

    const placesSecret = secretsmanager.Secret.fromSecretNameV2(
      this,
      'PlacesSecret',
      `whiskey-places-${environment}`,
    );

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
    new cdk.CfnOutput(this, 'ReviewsTableName', { value: reviewsTable.tableName });
    new cdk.CfnOutput(this, 'AppStateTableName', { value: appStateTable.tableName });
    new cdk.CfnOutput(this, 'WhiskeyListRoleArn', { value: listRole.roleArn });
    new cdk.CfnOutput(this, 'WhiskeySearchRoleArn', { value: searchRole.roleArn });
    new cdk.CfnOutput(this, 'ReviewsRoleArn', { value: reviewsRole.roleArn });
    new cdk.CfnOutput(this, 'RankingAggregatorRoleArn', { value: rankingAggregatorRole.roleArn });
    new cdk.CfnOutput(this, 'PlacesSecretArn', { value: placesSecret.secretArn });
    new cdk.CfnOutput(this, 'WhiskeyListLambdaArn', { value: whiskeyListLambda.functionArn });
    new cdk.CfnOutput(this, 'WhiskeySearchLambdaArn', { value: whiskeySearchLambda.functionArn });
    new cdk.CfnOutput(this, 'ReviewsLambdaArn', { value: reviewsLambda.functionArn });
    new cdk.CfnOutput(this, 'RankingAggregatorLambdaArn', { value: rankingAggregatorLambda.functionArn });
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
