import * as iam from 'aws-cdk-lib/aws-iam';

export type ProfileBedrockModel = {
  readonly type: 'profile';
  readonly profileArn: string;
  readonly destinationArns: readonly string[];
};

export type DirectBedrockModel = {
  readonly type: 'direct';
  readonly modelArn: string;
};

export type BedrockModel = ProfileBedrockModel | DirectBedrockModel;

export function bedrockModelAllowlist(models: readonly BedrockModel[]): string[] {
  return models.map((model) => model.type === 'profile'
    ? model.profileArn.split('/').at(-1)!
    : model.modelArn.split('/').at(-1)!);
}

/**
 * Build exact InvokeModel permissions for inference profiles and direct models.
 * Profile destinations are usable only when Bedrock reports an approved profile ARN.
 */
export function bedrockInvokeStatements(models: readonly BedrockModel[]): iam.PolicyStatement[] {
  const profiles = models.filter((model): model is ProfileBedrockModel => model.type === 'profile');
  const directModels = models.filter((model): model is DirectBedrockModel => model.type === 'direct');
  const statements: iam.PolicyStatement[] = [];

  if (profiles.length > 0) {
    statements.push(new iam.PolicyStatement({
      actions: ['bedrock:InvokeModel'],
      resources: profiles.map((model) => model.profileArn),
    }));
    statements.push(new iam.PolicyStatement({
      actions: ['bedrock:InvokeModel'],
      resources: profiles.flatMap((model) => model.destinationArns),
      conditions: {
        StringEquals: {
          'bedrock:InferenceProfileArn': profiles.map((model) => model.profileArn),
        },
      },
    }));
  }

  if (directModels.length > 0) {
    statements.push(new iam.PolicyStatement({
      actions: ['bedrock:InvokeModel'],
      resources: directModels.map((model) => model.modelArn),
    }));
  }

  return statements;
}
