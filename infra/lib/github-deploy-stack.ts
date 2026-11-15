import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

/**
 * GitHub Actions roles for the approval-gated CDK deploy workflow
 * (.github/workflows/cdk-deploy.yml).
 *
 * - plan role: may only assume the CDK bootstrap lookup role, so `cdk diff --method template`
 *   is the most it can do. Its GitHub environment (plan-<env>) has no reviewer.
 * - deploy role: may assume the CDK bootstrap deploy/publishing roles (effectively admin via
 *   the cfn-exec role) plus the few direct calls `deploy.sh --frontend` makes. Its GitHub
 *   environment (deploy-<env>) requires the owner's approval.
 *
 * The GitHub OIDC provider is referenced by ARN, never created or imported here: it already
 * exists in each account (verify with `aws iam list-open-id-connect-providers`).
 *
 * The owner applies this stack locally (`deploy.sh <env> --ci-roles`); deploy.sh refuses to
 * apply it with workflow credentials, so the workflow can never widen its own trust.
 */
export const GITHUB_REPOSITORY = 'kter/whiskey';
export const CDK_QUALIFIER = 'hnb659fds';
export const CDK_BOOTSTRAP_REGIONS = ['ap-northeast-1', 'us-east-1'] as const;

export interface GithubDeployStackProps extends cdk.StackProps {
  /** 'dev' or 'prd'. Used in role names, GitHub environment names and app resource names. */
  environment: string;
  /** Account the stack is deployed into; must match props.env.account. */
  account: string;
}

export class GithubDeployStack extends cdk.Stack {
  public readonly planRole: iam.Role;
  public readonly deployRole: iam.Role;

  constructor(scope: Construct, id: string, props: GithubDeployStackProps) {
    super(scope, id, props);

    const { environment, account } = props;
    const environmentName = environment.charAt(0).toUpperCase() + environment.slice(1);
    const providerArn =
      `arn:aws:iam::${account}:oidc-provider/token.actions.githubusercontent.com`;

    const bootstrapRoleArns = (kinds: string[]): string[] =>
      kinds.flatMap((kind) => CDK_BOOTSTRAP_REGIONS.map((region) =>
        `arn:aws:iam::${account}:role/cdk-${CDK_QUALIFIER}-${kind}-role-${account}-${region}`));
    const bootstrapVersionParameterArns = CDK_BOOTSTRAP_REGIONS.map((region) =>
      `arn:aws:ssm:${region}:${account}:parameter/cdk-bootstrap/${CDK_QUALIFIER}/version`);

    const githubPrincipal = (githubEnvironment: string) => new iam.WebIdentityPrincipal(
      providerArn,
      {
        StringEquals: {
          'token.actions.githubusercontent.com:aud': 'sts.amazonaws.com',
          'token.actions.githubusercontent.com:sub':
            `repo:${GITHUB_REPOSITORY}:environment:${githubEnvironment}`,
        },
      },
    );

    // --- plan: read-only cdk diff through the lookup role ---
    this.planRole = new iam.Role(this, 'PlanRole', {
      roleName: `whiskey-gha-plan-${environment}`,
      description: `GitHub Actions cdk diff (template method) for ${environment}`,
      assumedBy: githubPrincipal(`plan-${environment}`),
      maxSessionDuration: cdk.Duration.hours(1),
    });
    this.planRole.addToPolicy(new iam.PolicyStatement({
      sid: 'AssumeCdkLookupRole',
      actions: ['sts:AssumeRole'],
      resources: bootstrapRoleArns(['lookup']),
    }));
    this.planRole.addToPolicy(new iam.PolicyStatement({
      sid: 'ReadCdkBootstrapVersion',
      actions: ['ssm:GetParameter'],
      resources: bootstrapVersionParameterArns,
    }));

    // --- deploy: cdk deploy through the bootstrap roles + deploy.sh --frontend ---
    this.deployRole = new iam.Role(this, 'DeployRole', {
      roleName: `whiskey-gha-deploy-${environment}`,
      description: `GitHub Actions approval-gated deploy for ${environment}`,
      assumedBy: githubPrincipal(`deploy-${environment}`),
      maxSessionDuration: cdk.Duration.hours(1),
    });
    this.deployRole.addToPolicy(new iam.PolicyStatement({
      sid: 'AssumeCdkBootstrapRoles',
      actions: ['sts:AssumeRole'],
      resources: bootstrapRoleArns(['deploy', 'file-publishing', 'image-publishing', 'lookup']),
    }));
    this.deployRole.addToPolicy(new iam.PolicyStatement({
      sid: 'ReadCdkBootstrapVersion',
      actions: ['ssm:GetParameter'],
      resources: bootstrapVersionParameterArns,
    }));
    // deploy.sh --frontend: aws cloudformation describe-stacks --stack-name WhiskeyApp-<Env>
    this.deployRole.addToPolicy(new iam.PolicyStatement({
      sid: 'ReadAppStackOutputs',
      actions: ['cloudformation:DescribeStacks'],
      resources: [
        `arn:aws:cloudformation:ap-northeast-1:${account}:stack/WhiskeyApp-${environmentName}/*`,
      ],
    }));
    // deploy.sh --frontend: aws s3 sync .output/public s3://<WebAppBucketName> --delete
    // Bucket name pattern from WhiskeyInfraStack (whiskey-webapp-<env>-<account>, SSE-S3).
    const webAppBucketArn = `arn:aws:s3:::whiskey-webapp-${environment}-${account}`;
    this.deployRole.addToPolicy(new iam.PolicyStatement({
      sid: 'ListWebAppBucket',
      actions: ['s3:ListBucket'],
      resources: [webAppBucketArn],
    }));
    this.deployRole.addToPolicy(new iam.PolicyStatement({
      sid: 'SyncWebAppObjects',
      actions: ['s3:GetObject', 's3:PutObject', 's3:DeleteObject', 's3:AbortMultipartUpload'],
      resources: [`${webAppBucketArn}/*`],
    }));
    // deploy.sh --frontend: aws cloudfront create-invalidation. The distribution ID lives in
    // WhiskeyApp-<Env> and is not known here, so scope to this account's distributions.
    this.deployRole.addToPolicy(new iam.PolicyStatement({
      sid: 'InvalidateWebDistribution',
      actions: ['cloudfront:CreateInvalidation'],
      resources: [`arn:aws:cloudfront::${account}:distribution/*`],
    }));

    new cdk.CfnOutput(this, 'PlanRoleArn', {
      value: this.planRole.roleArn,
      description: `Set as AWS_ROLE_ARN on the GitHub environment plan-${environment}`,
    });
    new cdk.CfnOutput(this, 'DeployRoleArn', {
      value: this.deployRole.roleArn,
      description: `Set as AWS_ROLE_ARN on the GitHub environment deploy-${environment}`,
    });
  }
}
