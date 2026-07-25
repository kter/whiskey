import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';

export interface GithubOidcStackProps extends cdk.StackProps {
  createOidcProvider: boolean;
  deploymentBucketName: string;
}

export class GithubOidcStack extends cdk.Stack {
  public readonly role: iam.Role;

  constructor(scope: Construct, id: string, props: GithubOidcStackProps) {
    super(scope, id, props);

    const provider = props.createOidcProvider
      ? new iam.OpenIdConnectProvider(this, 'GithubProvider', {
          url: 'https://token.actions.githubusercontent.com',
          clientIds: ['sts.amazonaws.com'],
        })
      : iam.OpenIdConnectProvider.fromOpenIdConnectProviderArn(
          this,
          'GithubProvider',
          `arn:${cdk.Aws.PARTITION}:iam::${this.account}:oidc-provider/token.actions.githubusercontent.com`,
        );

    this.role = new iam.Role(this, 'GithubActionsRole', {
      roleName: 'whiskey-github-actions-role-dev',
      assumedBy: new iam.WebIdentityPrincipal(provider.openIdConnectProviderArn, {
        StringEquals: {
          'token.actions.githubusercontent.com:aud': 'sts.amazonaws.com',
          'token.actions.githubusercontent.com:sub': 'repo:kter/whiskey:environment:dev',
        },
      }),
    });

    const deploymentBucket = s3.Bucket.fromBucketName(
      this,
      'DeploymentBucket',
      props.deploymentBucketName,
    );
    deploymentBucket.grantReadWrite(this.role);

    this.role.addToPolicy(new iam.PolicyStatement({
      actions: ['cloudfront:CreateInvalidation'],
      resources: [`arn:${cdk.Aws.PARTITION}:cloudfront::${this.account}:distribution/*`],
    }));
    this.role.addToPolicy(new iam.PolicyStatement({
      actions: ['cloudformation:DescribeStacks'],
      resources: [
        `arn:${cdk.Aws.PARTITION}:cloudformation:*:${this.account}:stack/Whiskey*/*`,
      ],
    }));
    this.role.addToPolicy(new iam.PolicyStatement({
      actions: ['cloudformation:ListStacks'],
      resources: ['*'],
    }));

    new cdk.CfnOutput(this, 'GithubActionsRoleArn', {
      value: this.role.roleArn,
    });
  }
}
