import * as cdk from 'aws-cdk-lib';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as cloudwatchActions from 'aws-cdk-lib/aws-cloudwatch-actions';
import * as sns from 'aws-cdk-lib/aws-sns';
import { Construct } from 'constructs';

export interface ObservabilityStackProps extends cdk.StackProps {
  readonly environment: string;
  readonly notificationTopicArn: string;
  readonly imagesBucketName: string;
  readonly reconcilerFunctionName: string;
}

export class ObservabilityStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: ObservabilityStackProps) {
    super(scope, id, props);

    const topic = sns.Topic.fromTopicArn(this, 'TokyoNotificationsTopic', props.notificationTopicArn);
    const action = new cloudwatchActions.SnsAction(topic);
    const hourlyMetric = (metricName: string, filterId: string): cloudwatch.Metric =>
      new cloudwatch.Metric({
        namespace: 'AWS/S3',
        metricName,
        statistic: 'Sum',
        period: cdk.Duration.hours(1),
        dimensionsMap: {
          BucketName: props.imagesBucketName,
          FilterId: filterId,
        },
      });

    // These alarms notify operators; AppState counters, not alarms, enforce cost ceilings.
    const tmpPostRequestsAlarm = new cloudwatch.Alarm(this, 'TmpPostRequestsAlarm', {
      alarmName: `whiskey-${props.environment}-tmp-post-requests-high`,
      metric: hourlyMetric('PostRequests', 'tmp'),
      threshold: 300,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });
    const logsGetRequestsAlarm = new cloudwatch.Alarm(this, 'LogsGetRequestsAlarm', {
      alarmName: `whiskey-${props.environment}-logs-get-requests-high`,
      metric: hourlyMetric('GetRequests', 'logs'),
      threshold: 2000,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });
    const reconcilerErrorsAlarm = new cloudwatch.Alarm(this, 'ReconcilerErrorsAlarm', {
      alarmName: `whiskey-${props.environment}-drink-log-reconciler-errors`,
      metric: new cloudwatch.Metric({
        namespace: 'AWS/Lambda',
        metricName: 'Errors',
        statistic: 'Sum',
        period: cdk.Duration.minutes(5),
        dimensionsMap: { FunctionName: props.reconcilerFunctionName },
      }),
      threshold: 1,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });

    for (const alarm of [tmpPostRequestsAlarm, logsGetRequestsAlarm, reconcilerErrorsAlarm]) {
      alarm.addAlarmAction(action);
    }
  }
}
