import * as cdk from 'aws-cdk-lib';
import * as acm from 'aws-cdk-lib/aws-certificatemanager';
import * as route53 from 'aws-cdk-lib/aws-route53';
import { Construct } from 'constructs';

interface CertificateStackProps extends cdk.StackProps {
  environment: string;
  domain: string;
  hostedZoneId: string;
  hostedZoneName: string;
}

export class CertificateStack extends cdk.Stack {
  public readonly certificate: acm.Certificate;

  constructor(scope: Construct, id: string, props: CertificateStackProps) {
    super(scope, id, props);

    const { environment, domain, hostedZoneId, hostedZoneName } = props;

    // Hosted Zone の取得または参照
    let hostedZone: route53.IHostedZone;
    if (hostedZoneId) {
      hostedZone = route53.HostedZone.fromHostedZoneAttributes(this, 'HostedZone', {
        hostedZoneId,
        zoneName: hostedZoneName,
      });
    } else {
      hostedZone = route53.HostedZone.fromLookup(this, 'HostedZone', {
        domainName: hostedZoneName,
      });
    }

    // CloudFront用のSSL証明書（us-east-1リージョン）
    this.certificate = new acm.Certificate(this, 'Certificate', {
      domainName: domain,
      subjectAlternativeNames: [`*.${domain}`],
      validation: acm.CertificateValidation.fromDns(hostedZone),
    });

    // 証明書ARNを出力（クロスリージョン参照時はexportName不要）
    new cdk.CfnOutput(this, 'CertificateArn', {
      value: this.certificate.certificateArn,
      // exportName: `whiskey-certificate-arn-${environment}`, // crossRegionReferences使用時は不要
    });
  }
}