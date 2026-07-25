import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as route53 from 'aws-cdk-lib/aws-route53';
import { Construct } from 'constructs';
import { contextBoolean } from './context';

export const DNS_ACCOUNT = '031921999648';

export interface DnsStackProps extends cdk.StackProps {
  zoneName: string;
  delegationTargetAccounts?: string[];
  parentZone?: {
    account: string;
    zoneName: string;
  };
}

export class DnsStack extends cdk.Stack {
  public readonly hostedZone: route53.IHostedZone;

  constructor(scope: Construct, id: string, props: DnsStackProps) {
    super(scope, id, props);

    const hostedZone = new route53.PublicHostedZone(this, 'HostedZone', {
      zoneName: props.zoneName,
    });
    hostedZone.applyRemovalPolicy(cdk.RemovalPolicy.RETAIN);
    this.hostedZone = hostedZone;

    const delegationPrincipals = (props.delegationTargetAccounts ?? [])
      .map((account) => new iam.AccountPrincipal(account));
    if (delegationPrincipals.length > 0) {
      const delegationRole = new iam.Role(this, 'DelegationRole', {
        roleName: 'WhiskeyDnsDelegationRole',
        assumedBy: new iam.CompositePrincipal(...delegationPrincipals),
      });
      // Accepted risk: with the pinned CDK version, grantDelegation grants UPSERT/DELETE
      // of NS records across this entire apex zone; it does not apply Route 53's
      // ChangeResourceRecordSetsNormalizedRecordNames condition key. AccountPrincipal
      // trusts the whole dev account, so any dev principal allowed to sts:AssumeRole
      // can change NS records for any name below whiskeybar.site. A future migration can
      // use the custom resource Lambda's role ARN (ArnPrincipal) and a name condition.
      // Narrowing the principal before its first deployment creates a chicken-and-egg
      // dependency, so this task intentionally leaves assumedBy unchanged.
      hostedZone.grantDelegation(delegationRole);

      new cdk.CfnOutput(this, 'DelegationRoleArn', {
        value: delegationRole.roleArn,
      });
    }

    if (props.parentZone && contextBoolean(this, 'enableZoneDelegation', true)) {
      new route53.CrossAccountZoneDelegationRecord(this, 'ParentZoneDelegation', {
        delegatedZone: hostedZone,
        parentHostedZoneName: props.parentZone.zoneName,
        delegationRole: iam.Role.fromRoleArn(
          this,
          'ParentDelegationRole',
          `arn:aws:iam::${props.parentZone.account}:role/WhiskeyDnsDelegationRole`,
        ),
      });
    }

    new cdk.CfnOutput(this, 'HostedZoneId', {
      value: hostedZone.hostedZoneId,
    });

    for (let index = 0; index < 4; index += 1) {
      new cdk.CfnOutput(this, `NameServer${index + 1}`, {
        value: cdk.Fn.select(index, hostedZone.hostedZoneNameServers ?? []),
      });
    }
  }
}
