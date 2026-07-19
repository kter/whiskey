import * as cdk from 'aws-cdk-lib';
import * as route53 from 'aws-cdk-lib/aws-route53';
import { Construct } from 'constructs';

export const DNS_ACCOUNT = '031921999648';
export const ROOT_DOMAIN = 'whiskeybar.site';

export class DnsStack extends cdk.Stack {
  public readonly hostedZone: route53.IHostedZone;

  constructor(scope: Construct, id: string, props: cdk.StackProps) {
    super(scope, id, props);

    if (this.account !== DNS_ACCOUNT) {
      throw new Error(`WhiskeyDns must be synthesized for AWS account ${DNS_ACCOUNT}; received ${this.account}.`);
    }

    const hostedZone = new route53.PublicHostedZone(this, 'HostedZone', {
      zoneName: ROOT_DOMAIN,
    });
    hostedZone.applyRemovalPolicy(cdk.RemovalPolicy.RETAIN);
    this.hostedZone = hostedZone;

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
