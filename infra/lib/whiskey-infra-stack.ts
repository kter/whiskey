import * as cdk from 'aws-cdk-lib';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as acm from 'aws-cdk-lib/aws-certificatemanager';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as route53 from 'aws-cdk-lib/aws-route53';
import * as targets from 'aws-cdk-lib/aws-route53-targets';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { Construct } from 'constructs';
import { environments } from '../config/environments';

interface WhiskeyInfraStackProps extends cdk.StackProps {
  environment: string;
  cloudFrontCertificateArn?: string;
}

export class WhiskeyInfraStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: WhiskeyInfraStackProps) {
    super(scope, id, props);

    const { environment, cloudFrontCertificateArn } = props;
    const envConfig = environments[environment];
    
    if (!envConfig) {
      throw new Error(`Environment configuration not found for: ${environment}`);
    }

    // ====================
    // VPC Configuration
    // ====================
    const vpc = new ec2.Vpc(this, 'WhiskeyVPC', {
      ipAddresses: ec2.IpAddresses.cidr('10.0.0.0/16'),
      maxAzs: 2,
      natGateways: envConfig.natGateways, // 環境に応じてNATゲートウェイを設定
      subnetConfiguration: [
        {
          cidrMask: 24,
          name: 'Public',
          subnetType: ec2.SubnetType.PUBLIC,
        },
        {
          cidrMask: 24,
          name: 'Private',
          subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
        },
      ],
    });

    // ====================
    // S3 Buckets
    // ====================
    
    // ウイスキー画像保存用S3バケット
    const imagesBucket = new s3.Bucket(this, 'WhiskeyImagesBucket', {
      bucketName: `whiskey-images-${environment}-${this.account}`,
      versioned: false,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: environment === 'prod' ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY,
      cors: [
        {
          allowedMethods: [s3.HttpMethods.GET, s3.HttpMethods.PUT, s3.HttpMethods.POST],
          allowedOrigins: envConfig.allowedOrigins,
          allowedHeaders: ['*'],
          exposedHeaders: ['ETag'],
        },
      ],
    });

    // Nuxt.js SPA用S3バケット
    const webAppBucket = new s3.Bucket(this, 'WhiskeyWebAppBucket', {
      bucketName: `whiskey-webapp-${environment}-${this.account}`,
      publicReadAccess: false, // パブリックアクセスを無効化
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL, // 全てのパブリックアクセスをブロック
      removalPolicy: environment === 'prod' ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY,
    });

    // ====================
    // Route53 & SSL Certificate (if domain is configured)
    // ====================
    
    let hostedZone;
    let webCertificate;
    let apiCertificate;
    
    if (envConfig.domain) {
      // Route53ホストゾーンを既存のものから取得
      hostedZone = route53.HostedZone.fromLookup(this, 'HostedZone', {
        domainName: envConfig.domain,
      });
      
      // CloudFront用SSL証明書（証明書スタックから参照）
      if (cloudFrontCertificateArn) {
        webCertificate = acm.Certificate.fromCertificateArn(this, 'WebCertificate', cloudFrontCertificateArn);
      }
      
      // API用SSL証明書（API Gateway用なので現在のリージョンで作成）
      if (envConfig.apiDomain) {
        apiCertificate = new acm.Certificate(this, 'ApiCertificate', {
          domainName: envConfig.apiDomain,
          validation: acm.CertificateValidation.fromDns(hostedZone),
        });
      }
    }

    // ====================
    // CloudFront Distribution
    // ====================
    
    const distribution = new cloudfront.Distribution(this, 'WhiskeyWebDistribution', {
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(webAppBucket),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        allowedMethods: cloudfront.AllowedMethods.ALLOW_GET_HEAD,
        cachedMethods: cloudfront.CachedMethods.CACHE_GET_HEAD,
        cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
      },
      defaultRootObject: 'index.html',
      errorResponses: [
        {
          httpStatus: 404,
          responseHttpStatus: 200,
          responsePagePath: '/index.html', // SPAの場合、404を index.html にリダイレクト
        },
        {
          httpStatus: 403,
          responseHttpStatus: 200,
          responsePagePath: '/index.html',
        },
      ],
      // カスタムドメインがある場合は設定
      ...(envConfig.domain && webCertificate ? {
        domainNames: [envConfig.domain, `www.${envConfig.domain}`],
        certificate: webCertificate,
      } : {}),
    });

    // ====================
    // DynamoDB Tables
    // ====================
    
    // Whiskeysテーブル
    const whiskeysTable = new dynamodb.Table(this, 'WhiskeysTable', {
      tableName: `Whiskeys-${environment}`,
      partitionKey: { name: 'id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: environment === 'prod' ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY,
    });

    // GSI for name search
    whiskeysTable.addGlobalSecondaryIndex({
      indexName: 'NameIndex',
      partitionKey: { name: 'name', type: dynamodb.AttributeType.STRING },
    });

    // Reviewsテーブル
    const reviewsTable = new dynamodb.Table(this, 'ReviewsTable', {
      tableName: `Reviews-${environment}`,
      partitionKey: { name: 'id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: environment === 'prod' ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY,
    });

    // GSI for user and date search
    reviewsTable.addGlobalSecondaryIndex({
      indexName: 'UserDateIndex',
      partitionKey: { name: 'user_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'date', type: dynamodb.AttributeType.STRING },
    });

    // UsersテーブルUser profile table
    const usersTable = new dynamodb.Table(this, 'UsersTable', {
      tableName: `Users-${environment}`,
      partitionKey: { name: 'user_id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: environment === 'prod' ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY,
    });

    // WhiskeySearchテーブル - 検索最適化用（日本語専用）
    const whiskeySearchTable = new dynamodb.Table(this, 'WhiskeySearchTable', {
      tableName: `WhiskeySearch-${environment}`,
      partitionKey: { name: 'id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: environment === 'prod' ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY,
    });

    // 検索用GSI（日本語専用） - 2つ目のGSIを追加
    whiskeySearchTable.addGlobalSecondaryIndex({
      indexName: 'NameIndex',
      partitionKey: { name: 'normalized_name', type: dynamodb.AttributeType.STRING },
    });

    whiskeySearchTable.addGlobalSecondaryIndex({
      indexName: 'DistilleryIndex',
      partitionKey: { name: 'normalized_distillery', type: dynamodb.AttributeType.STRING },
    });

    // ====================
    // Secrets Manager (moved before Cognito to support Google provider)
    // ====================
    const appSecrets = secretsmanager.Secret.fromSecretNameV2(this, 'WhiskeyAppSecrets', `whiskey-app-secrets-${environment}`);

    // ====================
    // Cognito User Pool
    // ====================
    const userPool = new cognito.UserPool(this, 'WhiskeyUserPool', {
      userPoolName: `whiskey-users-${environment}`,
      selfSignUpEnabled: true, // 一時的に有効化
      signInAliases: {
        email: true, // 一時的に有効化
        username: true, // 一時的に有効化
      },
      autoVerify: {
        email: true, // メール検証を有効化
      },
      standardAttributes: {
        email: {
          required: true,
          mutable: true,
        },
        givenName: {
          required: false,
          mutable: true,
        },
        familyName: {
          required: false,
          mutable: true,
        },
      },
      passwordPolicy: {
        minLength: 8,
        requireLowercase: true,
        requireUppercase: true,
        requireDigits: true,
        requireSymbols: false,
      },
      accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
      removalPolicy: environment === 'prod' ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY,
    });

    // User Pool Domain for hosted UI
    const userPoolDomain = new cognito.UserPoolDomain(this, 'WhiskeyUserPoolDomain', {
      userPool,
      cognitoDomain: {
        domainPrefix: `whiskey-users-${environment}`,
      },
    });

    // Google Identity Provider (temporarily disabled until credentials are configured)
    // TODO: Enable after setting up Google credentials in Secrets Manager
    
    const googleProvider = new cognito.UserPoolIdentityProviderGoogle(this, 'GoogleProvider', {
      userPool,
      clientId: appSecrets.secretValueFromJson('GOOGLE_CLIENT_ID').unsafeUnwrap(),
      clientSecretValue: appSecrets.secretValueFromJson('GOOGLE_CLIENT_SECRET'),
      scopes: ['email', 'profile', 'openid'],
      attributeMapping: {
        email: cognito.ProviderAttribute.GOOGLE_EMAIL,
        givenName: cognito.ProviderAttribute.GOOGLE_GIVEN_NAME,
        familyName: cognito.ProviderAttribute.GOOGLE_FAMILY_NAME,
        profilePicture: cognito.ProviderAttribute.GOOGLE_PICTURE,
      },
    });

    // User Pool Client
    const userPoolClient = new cognito.UserPoolClient(this, 'WhiskeyUserPoolClient', {
      userPool,
      userPoolClientName: `whiskey-app-client-${environment}`,
      generateSecret: false, // SPAの場合はfalse
      authFlows: {
        userSrp: true, // 一時的に有効化
        userPassword: true, // 一時的に有効化
      },
      supportedIdentityProviders: [
        cognito.UserPoolClientIdentityProvider.COGNITO, // 一時的にCognitoも有効化
        cognito.UserPoolClientIdentityProvider.GOOGLE,
      ],
      oAuth: {
        flows: {
          authorizationCodeGrant: true,
        },
        scopes: [
          cognito.OAuthScope.EMAIL,
          cognito.OAuthScope.PROFILE,
          cognito.OAuthScope.OPENID,
        ],
        callbackUrls: [
          `https://${envConfig.domain || 'dev.whiskeybar.site'}`,
          `https://${envConfig.domain || 'dev.whiskeybar.site'}/auth/callback`,
          'http://localhost:3000', // ローカル開発用
          'http://localhost:3000/auth/callback', // ローカル開発用
        ],
        logoutUrls: [
          `https://${envConfig.domain || 'dev.whiskeybar.site'}`,
          'http://localhost:3000', // ローカル開発用
        ],
      },
      refreshTokenValidity: cdk.Duration.days(30),
      accessTokenValidity: cdk.Duration.hours(1),
      idTokenValidity: cdk.Duration.hours(1),
    });

    // Google Providerの依存関係を明示的に設定 (temporarily disabled)
    userPoolClient.node.addDependency(googleProvider);

    // ====================
    // API Infrastructure (Lambda + API Gateway)
    // ====================
    
    // CloudWatch Logs Group for Lambda
    const lambdaLogGroup = new logs.LogGroup(this, 'WhiskeyApiLogGroup', {
      logGroupName: `/aws/lambda/whiskey-api-${environment}`,
      retention: environment === 'prod' ? logs.RetentionDays.ONE_MONTH : logs.RetentionDays.ONE_WEEK,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // ====================
    // IAM Roles
    // ====================
    
    // Lambda実行ロール
    const lambdaExecutionRole = new iam.Role(this, 'WhiskeyLambdaExecutionRole', {
      roleName: `whiskey-lambda-execution-role-${environment}`,
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
      ],
    });

    // DynamoDB アクセス権限
    whiskeysTable.grantReadWriteData(lambdaExecutionRole);
    reviewsTable.grantReadWriteData(lambdaExecutionRole);
    usersTable.grantReadWriteData(lambdaExecutionRole);
    whiskeySearchTable.grantReadWriteData(lambdaExecutionRole);

    // S3 アクセス権限
    imagesBucket.grantReadWrite(lambdaExecutionRole);
    
    // Cognito アクセス権限
    lambdaExecutionRole.addToPolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: [
        'cognito-idp:AdminGetUser',
        'cognito-idp:AdminCreateUser',
        'cognito-idp:AdminUpdateUserAttributes',
        'cognito-idp:AdminDeleteUser',
        'cognito-idp:AdminListGroupsForUser',
        'cognito-idp:AdminAddUserToGroup',
        'cognito-idp:AdminRemoveUserFromGroup',
        'cognito-idp:ListUsers',
      ],
      resources: [userPool.userPoolArn],
    }));

    // マイクロサービス Lambda関数群
    
    // ウイスキー一覧取得Lambda
    const whiskeyListLambda = new lambda.Function(this, 'WhiskeyListFunction', {
      functionName: `whiskey-list-${environment}`,
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'index.lambda_handler',
      code: lambda.Code.fromAsset('../lambda/whiskeys-list'),
      timeout: cdk.Duration.seconds(15),
      memorySize: 256,
      role: lambdaExecutionRole,
      environment: {
        WHISKEYS_TABLE: whiskeysTable.tableName,
      },
    });

    // ウイスキー検索Lambda
    const whiskeySearchLambda = new lambda.Function(this, 'WhiskeySearchFunction', {
      functionName: `whiskey-search-${environment}`,
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'index.lambda_handler',
      code: lambda.Code.fromAsset('../lambda/whiskeys-search'),
      timeout: cdk.Duration.seconds(15),
      memorySize: 256,
      role: lambdaExecutionRole,
      environment: {
        WHISKEYS_TABLE: whiskeysTable.tableName,
        REVIEWS_TABLE: reviewsTable.tableName, // ランキング機能のため追加
        WHISKEY_SEARCH_TABLE: whiskeySearchTable.tableName,
        ENVIRONMENT: environment,
      },
    });

    // レビュー統合Lambda
    const reviewsLambda = new lambda.Function(this, 'ReviewsFunction', {
      functionName: `reviews-${environment}`,
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'index.lambda_handler',
      code: lambda.Code.fromAsset('../lambda/reviews'),
      timeout: cdk.Duration.seconds(30),
      memorySize: 512,
      role: lambdaExecutionRole,
      environment: {
        REVIEWS_TABLE: reviewsTable.tableName,
        WHISKEYS_TABLE: whiskeysTable.tableName,
        COGNITO_USER_POOL_ID: userPool.userPoolId,
        AWS_REGION: this.region,
      },
    });

    // API Gateway
    const api = new apigateway.RestApi(this, 'WhiskeyApi', {
      restApiName: `whiskey-api-${environment}`,
      description: `Whiskey API for ${environment} environment`,
      cloudWatchRole: true,
      deployOptions: {
        stageName: environment,
        loggingLevel: apigateway.MethodLoggingLevel.INFO,
        dataTraceEnabled: true,
        metricsEnabled: true,
      },
      defaultCorsPreflightOptions: {
        allowOrigins: apigateway.Cors.ALL_ORIGINS,
        allowMethods: apigateway.Cors.ALL_METHODS,
        allowHeaders: [
          'Content-Type',
          'X-Amz-Date',
          'Authorization',
          'X-Api-Key',
          'X-Amz-Security-Token',
          'X-Requested-With',
        ],
        allowCredentials: false, // Lambdaでより柔軟なCORS処理を行うため無効化
      },
      ...(envConfig.apiDomain && apiCertificate ? {
        domainName: {
          domainName: envConfig.apiDomain,
          certificate: apiCertificate,
        },
      } : {}),
    });

    // API Gateway ルーティング設定
    // フロントエンドとの互換性のため /api プレフィックスを追加
    
    const apiResource = api.root.addResource('api');
    
    // ウイスキー関連エンドポイント
    const whiskeysResource = apiResource.addResource('whiskeys');
    
    // GET /api/whiskeys - ウイスキー一覧
    whiskeysResource.addMethod('GET', 
      new apigateway.LambdaIntegration(whiskeyListLambda),
      {
        authorizationType: apigateway.AuthorizationType.NONE,
      }
    );
    
    // GET /api/whiskeys/search - ウイスキー検索  
    const whiskeySearchResource = whiskeysResource.addResource('search');
    whiskeySearchResource.addMethod('GET', 
      new apigateway.LambdaIntegration(whiskeySearchLambda),
      {
        authorizationType: apigateway.AuthorizationType.NONE,
      }
    );
    
    // GET /api/whiskeys/suggest - ウイスキー サジェスト (直接アクセス用)
    const whiskeySuggestResource = whiskeysResource.addResource('suggest');
    whiskeySuggestResource.addMethod('GET', 
      new apigateway.LambdaIntegration(whiskeySearchLambda), // 検索Lambdaを共用
      {
        authorizationType: apigateway.AuthorizationType.NONE,
      }
    );
    
    // GET /api/whiskeys/search/suggest - ウイスキー サジェスト (フロントエンド互換用)
    const whiskeySearchSuggestResource = whiskeySearchResource.addResource('suggest');
    whiskeySearchSuggestResource.addMethod('GET', 
      new apigateway.LambdaIntegration(whiskeySearchLambda), // 検索Lambdaを共用
      {
        authorizationType: apigateway.AuthorizationType.NONE,
      }
    );
    
    // レビュー関連エンドポイント
    const reviewsResource = apiResource.addResource('reviews');
    
    // レビューCRUD (GET /api/reviews?public=true, POST /api/reviews, PUT /api/reviews/{id})
    reviewsResource.addMethod('GET', 
      new apigateway.LambdaIntegration(reviewsLambda),
      {
        authorizationType: apigateway.AuthorizationType.NONE, // Lambda内で認証処理
      }
    );
    reviewsResource.addMethod('POST', 
      new apigateway.LambdaIntegration(reviewsLambda),
      {
        authorizationType: apigateway.AuthorizationType.NONE, // Lambda内で認証処理
      }
    );
    
    // PUT /api/reviews/{id} - レビュー更新
    const reviewByIdResource = reviewsResource.addResource('{id}');
    reviewByIdResource.addMethod('PUT', 
      new apigateway.LambdaIntegration(reviewsLambda),
      {
        authorizationType: apigateway.AuthorizationType.NONE, // Lambda内で認証処理
      }
    );
    
    // GET /api/reviews/public/ - パブリックレビュー（後方互換性のため）
    const reviewsPublicResource = reviewsResource.addResource('public');
    reviewsPublicResource.addMethod('GET', 
      new apigateway.LambdaIntegration(reviewsLambda), // パブリックレビューも同じLambdaで処理
      {
        authorizationType: apigateway.AuthorizationType.NONE,
      }
    );
    
    // GET /api/whiskeys/ranking/ - ウイスキーランキング（後方互換性のため）
    const whiskeyRankingResource = whiskeysResource.addResource('ranking');
    whiskeyRankingResource.addMethod('GET', 
      new apigateway.LambdaIntegration(whiskeySearchLambda), // 検索Lambdaでランキングも処理
      {
        authorizationType: apigateway.AuthorizationType.NONE,
      }
    );

    // 単数形パスは削除し、複数形 /api/whiskeys/ に統一

    // GitHub Actions用OIDC プロバイダー
    const gitHubOidcProvider = new iam.OpenIdConnectProvider(this, 'GitHubOidcProvider', {
      url: 'https://token.actions.githubusercontent.com',
      clientIds: ['sts.amazonaws.com'],
      thumbprints: ['1c58a3a8518e8759bf075b76b750d4f2df264fcd', '6938fd4d98bab03faadb97b34396831e3780aea1'],
    });

    // GitHub Actions用ロール（S3デプロイ用）
    const githubActionsRole = new iam.Role(this, 'GitHubActionsRole', {
      roleName: `whiskey-github-actions-role-${environment}`,
      assumedBy: new iam.WebIdentityPrincipal(
        gitHubOidcProvider.openIdConnectProviderArn,
        {
          StringEquals: {
            'token.actions.githubusercontent.com:aud': 'sts.amazonaws.com',
          },
          StringLike: {
            'token.actions.githubusercontent.com:sub': 'repo:kter/whiskey:*', // 実際のリポジトリ名に変更
          },
        }
      ),
    });

    // GitHub Actions に S3 デプロイ権限を付与
    webAppBucket.grantReadWrite(githubActionsRole);
    githubActionsRole.addToPolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: [
        'cloudfront:CreateInvalidation',
      ],
      resources: [distribution.distributionArn],
    }));

    // Lambda関数更新権限（マイクロサービス対応）
    githubActionsRole.addToPolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: [
        'lambda:UpdateFunctionCode',
        'lambda:UpdateFunctionConfiguration',
        'lambda:GetFunction',
        'lambda:PublishVersion',
      ],
      resources: [
        whiskeyListLambda.functionArn,
        whiskeySearchLambda.functionArn,
        reviewsLambda.functionArn,
      ],
    }));


    // CloudFormationスタック情報読み取り権限
    githubActionsRole.addToPolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: [
        'cloudformation:DescribeStacks',
        'cloudformation:ListStacks',
      ],
      resources: [`arn:aws:cloudformation:${this.region}:${this.account}:stack/WhiskeyApp-*/*`],
    }));


    // ====================
    // Route53 DNS Records (if domain is configured)
    // ====================
    if (envConfig.domain && hostedZone) {
      // メインドメインのAレコード
      new route53.ARecord(this, 'DomainARecord', {
        zone: hostedZone,
        recordName: envConfig.domain,
        target: route53.RecordTarget.fromAlias(new targets.CloudFrontTarget(distribution)),
      });

      // www サブドメインのAレコード
      new route53.ARecord(this, 'WwwDomainARecord', {
        zone: hostedZone,
        recordName: `www.${envConfig.domain}`,
        target: route53.RecordTarget.fromAlias(new targets.CloudFrontTarget(distribution)),
      });

      // APIドメインのAレコード
      if (envConfig.apiDomain) {
        new route53.ARecord(this, 'ApiDomainARecord', {
          zone: hostedZone,
          recordName: envConfig.apiDomain,
          target: route53.RecordTarget.fromAlias(new targets.ApiGateway(api)),
        });
      }
    }

    // ====================
    // Outputs
    // ====================
    new cdk.CfnOutput(this, 'VpcId', {
      value: vpc.vpcId,
      exportName: `whiskey-vpc-id-${environment}`,
    });

    new cdk.CfnOutput(this, 'UserPoolId', {
      value: userPool.userPoolId,
      exportName: `whiskey-user-pool-id-${environment}`,
    });

    new cdk.CfnOutput(this, 'UserPoolClientId', {
      value: userPoolClient.userPoolClientId,
      exportName: `whiskey-user-pool-client-id-${environment}`,
    });

    new cdk.CfnOutput(this, 'ImagesBucketName', {
      value: imagesBucket.bucketName,
      exportName: `whiskey-images-bucket-${environment}`,
    });

    new cdk.CfnOutput(this, 'WebAppBucketName', {
      value: webAppBucket.bucketName,
      exportName: `whiskey-webapp-bucket-${environment}`,
    });

    new cdk.CfnOutput(this, 'CloudFrontDistributionId', {
      value: distribution.distributionId,
      exportName: `whiskey-cloudfront-distribution-id-${environment}`,
    });

    new cdk.CfnOutput(this, 'CloudFrontDomainName', {
      value: distribution.distributionDomainName,
      exportName: `whiskey-cloudfront-domain-${environment}`,
    });

    // カスタムドメインの出力
    if (envConfig.domain) {
      new cdk.CfnOutput(this, 'CustomDomainName', {
        value: envConfig.domain,
        exportName: `whiskey-custom-domain-${environment}`,
      });

      new cdk.CfnOutput(this, 'WebsiteUrl', {
        value: `https://${envConfig.domain}`,
        exportName: `whiskey-website-url-${environment}`,
      });
    }

    new cdk.CfnOutput(this, 'WhiskeysTableName', {
      value: whiskeysTable.tableName,
      exportName: `whiskey-whiskeys-table-${environment}`,
    });

    new cdk.CfnOutput(this, 'ReviewsTableName', {
      value: reviewsTable.tableName,
      exportName: `whiskey-reviews-table-${environment}`,
    });

    new cdk.CfnOutput(this, 'LambdaExecutionRoleArn', {
      value: lambdaExecutionRole.roleArn,
      exportName: `whiskey-lambda-execution-role-arn-${environment}`,
    });

    new cdk.CfnOutput(this, 'GitHubActionsRoleArn', {
      value: githubActionsRole.roleArn,
      exportName: `whiskey-github-actions-role-arn-${environment}`,
    });

    new cdk.CfnOutput(this, 'SecretsManagerArn', {
      value: appSecrets.secretArn,
      exportName: `whiskey-secrets-arn-${environment}`,
    });

    // Lambda関数の出力（マイクロサービス対応）
    new cdk.CfnOutput(this, 'WhiskeyListLambdaArn', {
      value: whiskeyListLambda.functionArn,
      exportName: `whiskey-list-lambda-arn-${environment}`,
    });
    
    new cdk.CfnOutput(this, 'WhiskeySearchLambdaArn', {
      value: whiskeySearchLambda.functionArn,
      exportName: `whiskey-search-lambda-arn-${environment}`,
    });
    
    new cdk.CfnOutput(this, 'ReviewsLambdaArn', {
      value: reviewsLambda.functionArn,
      exportName: `reviews-lambda-arn-${environment}`,
    });

    new cdk.CfnOutput(this, 'ApiGatewayRestApiId', {
      value: api.restApiId,
      exportName: `whiskey-api-gateway-id-${environment}`,
    });

    new cdk.CfnOutput(this, 'ApiGatewayUrl', {
      value: api.url,
      exportName: `whiskey-api-gateway-url-${environment}`,
    });

    // APIドメインの出力
    if (envConfig.apiDomain) {
      new cdk.CfnOutput(this, 'ApiDomainName', {
        value: envConfig.apiDomain,
        exportName: `whiskey-api-domain-${environment}`,
      });

      new cdk.CfnOutput(this, 'ApiUrl', {
        value: `https://${envConfig.apiDomain}`,
        exportName: `whiskey-api-url-${environment}`,
      });
    }
  }
} 