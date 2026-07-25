import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as route53 from 'aws-cdk-lib/aws-route53';
import { Construct } from 'constructs';

export const DNS_ACCOUNT = '031921999648';
export const ROOT_DOMAIN = 'whiskeybar.site';

export interface DnsStackProps extends cdk.StackProps {
  zoneName: string;
  delegationTargetAccounts?: string[];
  parentZone?: {
    account: string;
    zoneName: string;
  };
}

function contextBoolean(scope: Construct, key: string, fallback: boolean): boolean {
  const value = scope.node.tryGetContext(key);
  if (value === undefined) {
    return fallback;
  }
  if (value === true || value === 'true') {
    return true;
  }
  if (value === false || value === 'false') {
    return false;
  }
  throw new Error(`Context ${key} must be true or false.`);
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
