import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import * as route53 from 'aws-cdk-lib/aws-route53';
import * as acm from 'aws-cdk-lib/aws-certificatemanager';
import * as targets from 'aws-cdk-lib/aws-route53-targets';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as elbv2 from 'aws-cdk-lib/aws-elasticloadbalancingv2';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Construct } from 'constructs';
import { environments } from '../config/environments';

interface WhiskeyInfraStackProps extends cdk.StackProps {
  environment: string;
}

export class WhiskeyInfraStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: WhiskeyInfraStackProps) {
    super(scope, id, props);

    const { environment } = props;
    const envConfig = environments[environment];
    
    if (!envConfig) {
      throw new Error(`Environment configuration not found for: ${environment}`);
    }

    // ====================
    // VPC Configuration
    // ====================
    const vpc = new ec2.Vpc(this, 'WhiskeyVPC', {
      cidr: '10.0.0.0/16',
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
          subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS, // ECS Fargate用
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
      
      // フロントエンド用SSL証明書（CloudFront用なのでus-east-1で作成）
      webCertificate = new acm.DnsValidatedCertificate(this, 'WebCertificate', {
        domainName: envConfig.domain,
        subjectAlternativeNames: [`www.${envConfig.domain}`],
        hostedZone: hostedZone,
        region: 'us-east-1', // CloudFrontではus-east-1のみ
      });
      
      // API用SSL証明書（ALB用なので現在のリージョンで作成）
      if (envConfig.apiDomain) {
        apiCertificate = new acm.DnsValidatedCertificate(this, 'ApiCertificate', {
          domainName: envConfig.apiDomain,
          hostedZone: hostedZone,
          region: envConfig.region, // ALB用は現在のリージョン
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

    // ====================
    // Cognito User Pool
    // ====================
    const userPool = new cognito.UserPool(this, 'WhiskeyUserPool', {
      userPoolName: `whiskey-users-${environment}`,
      selfSignUpEnabled: true,
      signInAliases: {
        email: true,
        username: true,
      },
      autoVerify: {
        email: true,
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

    // User Pool Client
    const userPoolClient = new cognito.UserPoolClient(this, 'WhiskeyUserPoolClient', {
      userPool,
      userPoolClientName: `whiskey-app-client-${environment}`,
      generateSecret: false, // SPAの場合はfalse
      authFlows: {
        userSrp: true,
        userPassword: true,
      },
      supportedIdentityProviders: [cognito.UserPoolClientIdentityProvider.COGNITO],
      refreshTokenValidity: cdk.Duration.days(30),
      accessTokenValidity: cdk.Duration.hours(1),
      idTokenValidity: cdk.Duration.hours(1),
    });

    // ====================
    // API Infrastructure (ECS Fargate + ALB)
    // ====================
    
    // ECR Repository for API Docker images
    const apiRepository = new ecr.Repository(this, 'WhiskeyApiRepository', {
      repositoryName: `whiskey-api-${environment}`,
      imageScanOnPush: true,
      removalPolicy: environment === 'prod' ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY,
    });

    // ECS Cluster
    const cluster = new ecs.Cluster(this, 'WhiskeyApiCluster', {
      clusterName: `whiskey-api-cluster-${environment}`,
      vpc: vpc,
      containerInsights: environment === 'prod', // 本番環境のみ有効
    });

    // CloudWatch Logs Group
    const logGroup = new logs.LogGroup(this, 'WhiskeyApiLogGroup', {
      logGroupName: `/ecs/whiskey-api-${environment}`,
      retention: environment === 'prod' ? logs.RetentionDays.ONE_MONTH : logs.RetentionDays.ONE_WEEK,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // ALB Security Group
    const albSecurityGroup = new ec2.SecurityGroup(this, 'ALBSecurityGroup', {
      vpc: vpc,
      description: 'Security group for API ALB',
      allowAllOutbound: true,
    });

    // ALB Security Group Rules
    albSecurityGroup.addIngressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.tcp(80),
      'Allow HTTP traffic'
    );
    albSecurityGroup.addIngressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.tcp(443),
      'Allow HTTPS traffic'
    );

    // Application Load Balancer
    const alb = new elbv2.ApplicationLoadBalancer(this, 'WhiskeyApiALB', {
      loadBalancerName: `whiskey-api-alb-${environment}`,
      vpc: vpc,
      internetFacing: true,
      securityGroup: albSecurityGroup,
    });

    // Target Group
    const targetGroup = new elbv2.ApplicationTargetGroup(this, 'WhiskeyApiTargetGroup', {
      targetGroupName: `whiskey-api-tg-${environment}`,
      port: 8000, // Django port
      protocol: elbv2.ApplicationProtocol.HTTP,
      vpc: vpc,
      targetType: elbv2.TargetType.IP,
      healthCheck: {
        enabled: true,
        path: '/health/', // Django health check endpoint
        protocol: elbv2.Protocol.HTTP,
        port: '8000',
        healthyThresholdCount: 2,
        unhealthyThresholdCount: 5,
        timeout: cdk.Duration.seconds(10),
        interval: cdk.Duration.seconds(30),
      },
    });

    // HTTPS Listener (if API domain and certificate exist)
    if (envConfig.apiDomain && apiCertificate) {
      const httpsListener = alb.addListener('HttpsListener', {
        port: 443,
        protocol: elbv2.ApplicationProtocol.HTTPS,
        certificates: [apiCertificate],
        defaultTargetGroups: [targetGroup],
      });
    }

    // HTTP Listener (redirect to HTTPS)
    const httpListener = alb.addListener('HttpListener', {
      port: 80,
      protocol: elbv2.ApplicationProtocol.HTTP,
      defaultAction: elbv2.ListenerAction.redirect({
        protocol: 'HTTPS',
        port: '443',
        permanent: true,
      }),
    });

    // ====================
    // IAM Roles
    // ====================
    
    // Lambda/ECS実行ロール
    const appExecutionRole = new iam.Role(this, 'WhiskeyAppExecutionRole', {
      roleName: `whiskey-app-execution-role-${environment}`,
      assumedBy: new iam.CompositePrincipal(
        new iam.ServicePrincipal('lambda.amazonaws.com'),
        new iam.ServicePrincipal('ecs-tasks.amazonaws.com')
      ),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaVPCAccessExecutionRole'),
      ],
    });

    // DynamoDB アクセス権限
    whiskeysTable.grantReadWriteData(appExecutionRole);
    reviewsTable.grantReadWriteData(appExecutionRole);

    // S3 アクセス権限
    imagesBucket.grantReadWrite(appExecutionRole);
    
    // Cognito アクセス権限
    appExecutionRole.addToPolicy(new iam.PolicyStatement({
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
    // Secrets Manager
    // ====================
    const appSecrets = new secretsmanager.Secret(this, 'WhiskeyAppSecrets', {
      secretName: `whiskey-app-secrets-${environment}`,
      description: `Whiskey app secrets for ${environment} environment`,
      generateSecretString: {
        secretStringTemplate: JSON.stringify({
          DATABASE_URL: '', // RDS接続文字列（将来の拡張用）
          JWT_SECRET: '',
          API_KEY: '',
        }),
        generateStringKey: 'JWT_SECRET',
        excludeCharacters: '"@/\\',
      },
    });

    // ====================
    // ECS Task Definition & Service
    // ====================
    
    // ECS Task Definition
    const taskDefinition = new ecs.FargateTaskDefinition(this, 'WhiskeyApiTaskDefinition', {
      family: `whiskey-api-${environment}`,
      cpu: 256, // 0.25 vCPU
      memoryLimitMiB: 512, // 512 MB
      executionRole: appExecutionRole,
      taskRole: appExecutionRole,
    });

    // Container Definition
    const container = taskDefinition.addContainer('WhiskeyApiContainer', {
      containerName: 'whiskey-api',
      image: ecs.ContainerImage.fromEcrRepository(apiRepository, 'latest'),
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: 'whiskey-api',
        logGroup: logGroup,
      }),
      environment: {
        ENVIRONMENT: environment,
        AWS_REGION: envConfig.region,
        ALLOWED_HOSTS: [
          envConfig.apiDomain || 'localhost',
          '.elb.amazonaws.com', // ALBのドメインを許可
          'localhost',
          '127.0.0.1',
          '*' // 一時的にすべてのホストを許可（ALBヘルスチェック用）
        ].join(','),
        DYNAMODB_WHISKEYS_TABLE: whiskeysTable.tableName,
        DYNAMODB_REVIEWS_TABLE: reviewsTable.tableName,
        S3_IMAGES_BUCKET: imagesBucket.bucketName,
        COGNITO_USER_POOL_ID: userPool.userPoolId,
        CORS_ALLOWED_ORIGINS: envConfig.allowedOrigins.join(','),
      },
      secrets: {
        JWT_SECRET: ecs.Secret.fromSecretsManager(appSecrets, 'JWT_SECRET'),
      },
      portMappings: [
        {
          containerPort: 8000,
          protocol: ecs.Protocol.TCP,
        },
      ],
    });

    // ECS Security Group
    const ecsSecurityGroup = new ec2.SecurityGroup(this, 'EcsSecurityGroup', {
      vpc: vpc,
      description: 'Security group for ECS API tasks',
      allowAllOutbound: true,
    });

    // Allow ALB to communicate with ECS tasks
    ecsSecurityGroup.addIngressRule(
      albSecurityGroup,
      ec2.Port.tcp(8000),
      'Allow traffic from ALB'
    );

    // ECS Service
    const ecsService = new ecs.FargateService(this, 'WhiskeyApiService', {
      serviceName: `whiskey-api-service-${environment}`,
      cluster: cluster,
      taskDefinition: taskDefinition,
      desiredCount: environment === 'prod' ? 2 : 1, // 本番は2台、開発は1台
      assignPublicIp: false, // プライベートサブネットなので
      securityGroups: [ecsSecurityGroup],
      vpcSubnets: {
        subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
      },
    });

    // Attach ECS Service to Target Group
    ecsService.attachToApplicationTargetGroup(targetGroup);

    // ECR認証トークン取得権限（全リソースに対して必要）
    githubActionsRole.addToPolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: [
        'ecr:GetAuthorizationToken',
      ],
      resources: ['*'],
    }));

    // ECRリポジトリ操作権限
    githubActionsRole.addToPolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: [
        'ecr:BatchCheckLayerAvailability',
        'ecr:GetDownloadUrlForLayer',
        'ecr:BatchGetImage',
        'ecr:InitiateLayerUpload',
        'ecr:UploadLayerPart',
        'ecr:CompleteLayerUpload',
        'ecr:PutImage',
      ],
      resources: [apiRepository.repositoryArn],
    }));

    // ECS操作権限（より広範なリソース指定）
    githubActionsRole.addToPolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: [
        'ecs:UpdateService',
        'ecs:DescribeServices',
        'ecs:DescribeTasks',
        'ecs:DescribeTaskDefinition',
        'ecs:RegisterTaskDefinition',
        'ecs:ListTasks',
        'ecs:DescribeClusters',
      ],
      resources: [
        cluster.clusterArn,
        ecsService.serviceArn,
        `arn:aws:ecs:${this.region}:${this.account}:task-definition/whiskey-api-${environment}:*`,
        `arn:aws:ecs:${this.region}:${this.account}:task/whiskey-api-cluster-${environment}/*`,
      ],
    }));

    // ECS wait操作のためのpass role権限
    githubActionsRole.addToPolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: [
        'iam:PassRole',
      ],
      resources: [
        appExecutionRole.roleArn,
      ],
      conditions: {
        StringEquals: {
          'iam:PassedToService': 'ecs-tasks.amazonaws.com',
        },
      },
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
          target: route53.RecordTarget.fromAlias(new targets.LoadBalancerTarget(alb)),
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

    new cdk.CfnOutput(this, 'AppExecutionRoleArn', {
      value: appExecutionRole.roleArn,
      exportName: `whiskey-app-execution-role-arn-${environment}`,
    });

    new cdk.CfnOutput(this, 'GitHubActionsRoleArn', {
      value: githubActionsRole.roleArn,
      exportName: `whiskey-github-actions-role-arn-${environment}`,
    });

    new cdk.CfnOutput(this, 'SecretsManagerArn', {
      value: appSecrets.secretArn,
      exportName: `whiskey-secrets-arn-${environment}`,
    });

    // API関連の出力
    new cdk.CfnOutput(this, 'ApiRepositoryUri', {
      value: apiRepository.repositoryUri,
      exportName: `whiskey-api-repository-uri-${environment}`,
    });

    new cdk.CfnOutput(this, 'AlbDnsName', {
      value: alb.loadBalancerDnsName,
      exportName: `whiskey-alb-dns-${environment}`,
    });

    new cdk.CfnOutput(this, 'EcsClusterName', {
      value: cluster.clusterName,
      exportName: `whiskey-ecs-cluster-${environment}`,
    });

    new cdk.CfnOutput(this, 'EcsServiceName', {
      value: ecsService.serviceName,
      exportName: `whiskey-ecs-service-${environment}`,
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