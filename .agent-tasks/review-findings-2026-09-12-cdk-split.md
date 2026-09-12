# Task: finish splitting the CDK stack constructor

## Context

The previous task's work package B8 asked for the 874-line
`infra/lib/whiskey-infra-stack.ts` constructor to be split into cohesive private
methods. Only two were extracted (`createImageStorage`, `createTables`). The
constructor still runs from line 56 to line 774 — **719 lines** — so the
Divergent Change smell the review flagged is still there: every unrelated infra
change still edits one enormous block.

This task finishes that split. Nothing else.

## Ground rules

- **Hard constraint: the synthesized CloudFormation must not change.** No new
  `Construct` scopes, no nested stacks, no changed construct ids, no reordered
  resource creation. Pure code movement.
- Do not change any resource property, IAM statement, or environment variable.
- Do not commit.

## What to do

1. Read the constructor end to end and identify the remaining cohesive groups.
   Based on the current shape they are roughly:
   - the IAM roles and log groups for the Lambda functions
   - the Lambda functions themselves (list, search, drink-logs, analyze, places,
     reconciler) and the shared layer
   - the REST API: API Gateway, the Cognito authorizer, resources, methods, CORS
   - Cognito: user pool, client, domain, Google identity provider
   - the reconciler schedule and any remaining outputs

   Use the grouping the code actually has, not this list, if they disagree.

2. Extract each group into a `private` method on the same class, called from the
   constructor in the same order the code runs today.

3. **Fix the parameter clump while you are in there.** `createImageStorage`
   already takes seven positional parameters (`environment`, `envConfig`,
   `props`, `retainResources`, `removalPolicy`, `allowedOrigins`,
   `enableCustomDomain`) and the remaining methods would take more. Do not
   propagate that.

   Instead, compute those shared values once at the top of the constructor and
   hold them as `private readonly` fields (or one `private readonly` settings
   object), so each extracted method reads what it needs from `this` and takes
   only the arguments genuinely specific to it — the constructs produced by an
   earlier step. Rework `createImageStorage` and `createTables` to that shape
   too.

   Also reconsider the name `createImageStorage`: it currently creates the
   images bucket, the web-app bucket, the security-headers policy and the
   CloudFront distribution. Split or rename it so the name tells the truth.

4. The constructor should end up as a short, readable sequence of named steps.

## Verification (all must pass)

```bash
cd infra && npm run build && npx jest        # 46 tests pass today
```

and the template-identity check, which is the one that matters:

```bash
cd infra
CDK_LOCAL_BUNDLING=1 npx cdk synth -c env=dev WhiskeyApp-Dev > /tmp/after.yaml
```

Compare against the current template — it must be **byte-identical**, not merely
similar. This task changes no Lambda code, so even the asset hashes must match.
Generate the "before" template first, from the current working tree, before you
edit anything.

Also run `python -m pytest tests -q` (361 pass) — `tests/test_drink_log_contract.py`
reads constants out of `infra/lib/whiskey-infra-stack.ts` with regexes anchored
on `NAME: value` object properties, so moving those lines between methods must
not break it.

## If you cannot hold the template identical

Stop, revert your changes, and report exactly which extraction broke it and how.
A partially-extracted constructor that still synthesizes identically is a better
outcome than a fully-extracted one that does not — but say plainly how far you
got rather than reporting the task as complete.

---

## Follow-up round 2

The first round landed the `settings` field, `createStorageAndDistribution`,
`createTables`, `createCognitoResources` and `createReconcilerSchedule`, and held
the template byte-identical. The constructor is still **610 lines** (71–681).

Extract the four groups that were reported as not done, in this order, each into
a `private` method on the same class reading shared values from `this.settings`:

1. the Lambda execution roles and their log groups
2. the shared Lambda layer and the six Lambda functions
3. the REST API: API Gateway, the Cognito authorizer, resources, methods, CORS
4. the custom-domain records and the stack outputs

Same hard constraint as before: **the synthesized template must stay
byte-identical** — no new scopes, no changed construct ids, no reordering. Take
the groups one at a time and re-synth after each; if one of them cannot hold the
template, keep the ones that can, revert only the one that breaks, and name it.

The constructor should end as a short sequence of named steps. Report the final
constructor line count.
