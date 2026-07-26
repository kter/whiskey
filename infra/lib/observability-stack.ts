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
  readonly restApiName: string;
  /**
   * Functions that get their own Errors alarm. Deliberately narrowed to the
   * functions that spend money per invocation (Bedrock, Google Places), because
   * CloudWatch bills per metric referenced by an alarm and the account only gets
   * 10 alarm metrics free. Failures elsewhere surface through the API 5xx alarm.
   */
  readonly errorAlarmFunctionNames: string[];
}

export class ObservabilityStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: ObservabilityStackProps) {
    super(scope, id, props);

    const topic = sns.Topic.fromTopicArn(this, 'TokyoNotificationsTopic', props.notificationTopicArn);
    const action = new cloudwatchActions.SnsAction(topic);
    const fiveMinuteMetric = (
      namespace: string,
      metricName: string,
      dimensionsMap?: Record<string, string>,
    ): cloudwatch.Metric =>
      new cloudwatch.Metric({
        namespace,
        metricName,
        statistic: 'Sum',
        period: cdk.Duration.minutes(5),
        dimensionsMap,
      });
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
    const api5xxAlarm = new cloudwatch.Alarm(this, 'Api5xxAlarm', {
      alarmName: `whiskey-${props.environment}-api-5xx-high`,
      metric: fiveMinuteMetric('AWS/ApiGateway', '5XXError', {
        ApiName: props.restApiName,
      }),
      threshold: 5,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });

    const environmentSuffix = `-${props.environment}`;
    const shortName = (resourceName: string): string =>
      resourceName.endsWith(environmentSuffix)
        ? resourceName.slice(0, -environmentSuffix.length)
        : resourceName;
    const lambdaErrorsAlarms = props.errorAlarmFunctionNames.map((functionName, index) =>
      new cloudwatch.Alarm(this, `LambdaErrorsAlarm${index}`, {
        alarmName: `whiskey-${props.environment}-lambda-errors-${shortName(functionName)}`,
        metric: fiveMinuteMetric('AWS/Lambda', 'Errors', { FunctionName: functionName }),
        threshold: 3,
        evaluationPeriods: 1,
        comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      }));
    const lambdaThrottlesAlarm = new cloudwatch.Alarm(this, 'LambdaThrottlesAlarm', {
      alarmName: `whiskey-${props.environment}-lambda-throttles`,
      // Lambda publishes a dimensionless regional aggregate across all functions. This
      // covers every consumer of the shared account concurrency pool, including new functions.
      metric: fiveMinuteMetric('AWS/Lambda', 'Throttles'),
      threshold: 1,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });
    // No per-table DynamoDB throttle alarms: every table is PAY_PER_REQUEST, so
    // throttling is rare, and four more alarm metrics would push the account past
    // the free tier. Throttles that do matter show up as API 5xx or Lambda errors.

    for (const alarm of [
      tmpPostRequestsAlarm,
      logsGetRequestsAlarm,
      reconcilerErrorsAlarm,
      api5xxAlarm,
      ...lambdaErrorsAlarms,
      lambdaThrottlesAlarm,
    ]) {
      alarm.addAlarmAction(action);
    }
  }
}
