import * as cdk from 'aws-cdk-lib';
import * as budgets from 'aws-cdk-lib/aws-budgets';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as subscriptions from 'aws-cdk-lib/aws-sns-subscriptions';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import { Construct } from 'constructs';

const EMAIL_PARAMETER = '/whiskey/notifications/email';

export interface NotificationsStackProps extends cdk.StackProps {
  kind: 'budget' | 'alarms';
}

export class NotificationsStack extends cdk.Stack {
  public readonly topic: sns.Topic;

  constructor(scope: Construct, id: string, props: NotificationsStackProps) {
    super(scope, id, props);

    this.topic = new sns.Topic(this, 'NotificationsTopic', {
      displayName: props.kind === 'budget' ? 'Whiskey budget notifications' : 'Whiskey alarm notifications',
    });

    const email = ssm.StringParameter.valueForStringParameter(this, EMAIL_PARAMETER);
    this.topic.addSubscription(new subscriptions.EmailSubscription(email));

    if (props.kind === 'budget') {
      const policyResult = this.topic.addToResourcePolicy(new iam.PolicyStatement({
        principals: [new iam.ServicePrincipal('budgets.amazonaws.com')],
        actions: ['sns:Publish'],
        resources: [this.topic.topicArn],
        conditions: {
          StringEquals: { 'aws:SourceAccount': this.account },
          ArnLike: {
            'aws:SourceArn': `arn:${cdk.Aws.PARTITION}:budgets::${this.account}:*`,
          },
        },
      }));

      const budget = new budgets.CfnBudget(this, 'MonthlyBudget', {
        budget: {
          budgetName: 'WhiskeyMonthlyCost',
          budgetType: 'COST',
          timeUnit: 'MONTHLY',
          budgetLimit: { amount: 20, unit: 'USD' },
        },
        notificationsWithSubscribers: [
          {
            notification: {
              comparisonOperator: 'GREATER_THAN',
              notificationType: 'ACTUAL',
              threshold: 80,
              thresholdType: 'PERCENTAGE',
            },
            subscribers: [
              { address: this.topic.topicArn, subscriptionType: 'SNS' },
            ],
          },
        ],
      });
      budget.node.addDependency(policyResult.policyDependable!);
    } else {
      this.topic.addToResourcePolicy(new iam.PolicyStatement({
        principals: [new iam.ServicePrincipal('cloudwatch.amazonaws.com')],
        actions: ['sns:Publish'],
        resources: [this.topic.topicArn],
        conditions: {
          StringEquals: { 'aws:SourceAccount': this.account },
          ArnLike: {
            'aws:SourceArn': `arn:aws:cloudwatch:*:${this.account}:alarm:*`,
          },
        },
      }));
    }

    new cdk.CfnOutput(this, 'TopicArn', { value: this.topic.topicArn });
  }
}
