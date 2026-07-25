import { Construct } from 'constructs';

export function contextBoolean(scope: Construct, key: string, fallback: boolean): boolean {
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
