# Task: close the five review follow-ups on the working-tree change

## Context

The uncommitted change on `chore/review-findings-2026-09-12` passed an
independent review with no critical or important issues, but five minor findings
and two test gaps were raised. This task closes all of them. Do not re-do
anything else in the working tree, and do not commit.

## Verification (all must pass when you are done)

```bash
python -m pytest tests -q                                            # 362 pass today
cd infra && npm run build && npx jest                                # 46 pass today
cd frontend && npm run lint && npx vitest run && npm run typecheck
```

`npm test` in `frontend/` is a watch mode that never exits — use `npx vitest run`.

---

## F1 — `DrinkLogCandidate` in `swagger.yml` describes fields that do not exist

`swagger.yml`'s `DrinkLogCandidate` declares `ai_name_ja` and `ai_name_en`.
`CandidateResolver.resolve`
(`lambda/common/python/whiskey_common/candidate_resolution.py:271-299`) never
emits them — I confirmed the only other references are dead optional fields on
the frontend interface. A client written against this spec would wait for a
field that never arrives.

The resolver always emits `brand_text`, `name_ja`, `name_en`, `confidence` and
`match_source`, and conditionally emits `whiskey_id`, `brand_ja`, `brand_en`,
`brand_key` and `distillery_ja`.

- Remove `ai_name_ja` and `ai_name_en` from the `DrinkLogCandidate` schema.
- Set its `required` list to exactly the five always-present fields.
- Remove the matching dead `ai_name_ja?` / `ai_name_en?` fields from
  `frontend/composables/useDrinkLogs.ts:14-15`. Check nothing reads them first
  (nothing does, outside generated `.nuxt`/`.output` artefacts, which you must
  not edit).

## F2 — finish resolving the CDK parameter clump

`infra/lib/whiskey-infra-stack.ts` now has a 92-line constructor, but
`createLambdaFunctions` takes **19 positional arguments**, including six
consecutive `iam.Role` and then six consecutive `logs.LogGroup`. Transposing
`drinkLogAnalyzeRole` and `drinkLogPlacesRole` at the call site type-checks
silently and would ship the Bedrock policy to the Places function.
`createLambdaRolesAndLogGroups` (5) and `createRestApi` (7) have the same shape.

`createCustomDomainRecordsAndOutputs` already takes a single named object
literal. Apply that shape to the other three methods so every argument is
named at the call site.

**Hard constraint: the synthesized CloudFormation must stay byte-identical.**
This is a signature change only — no new scopes, no changed construct ids, no
reordering. Generate the before-template first, then compare:

```bash
cd infra
CDK_LOCAL_BUNDLING=1 npx cdk synth -c env=dev WhiskeyApp-Dev > /tmp/before.yaml
# ...edit...
CDK_LOCAL_BUNDLING=1 npx cdk synth -c env=dev WhiskeyApp-Dev > /tmp/after.yaml
cmp /tmp/before.yaml /tmp/after.yaml
```

Note `infra/tsconfig.json` has `noUnusedLocals` and `noUnusedParameters` set to
`false`, so the compiler will not tell you about a field you stop passing —
check by hand that every field of each new object is both passed and read.

## F3 — the 501 anti-rot test has a hole

`tests/lambda/test_openapi_contract.py:33-39` asserts
`"501" not in operation["responses"]`. A future `501:` written **unquoted** in
YAML parses as the Python `int` 501, and the assertion silently passes. Compare
on `str(key)` over the response keys instead. Add a brief comment saying why,
since the bug is invisible otherwise.

## F4 — `ServiceUnavailable`'s description is wrong for the drink-log routes

`swagger.yml` describes the `ServiceUnavailable` response as *"A monthly Usage
Budget was exhausted or a budget transaction could not converge"*. But
`lambda/drink-logs/index.py:394` maps **every** `UsageBudgetExceeded` — monthly
scope included — to 429 through `_rate_limit_error`. On `/api/drink-logs` and
`/api/drink-logs/upload-url`, 503 can only come from `BudgetTransactionConflict`.
Only `/api/drink-logs/analyze` forwards `exc.status_code` and can therefore
return 503 for a monthly budget.

Reword so it is accurate for both callers — verify the claim against
`_EXCEPTION_MAPPERS` and `whiskey_common/cost_guard.py` before you write it,
rather than trusting this description.

## F5 — the four POST routes have no `requestBody`

`/api/drink-logs/upload-url`, `/analyze`, `/places` and `/places/resolve` declare
400 responses for validation failures whose request shape the spec never states
(`POST /api/drink-logs` is currently the only operation in the file with a
`requestBody`).

Add a `requestBody` to each, with a schema matching what the handler actually
validates. The validators are the authority — read them, do not guess:

- `validate_upload_input` in `lambda/drink-logs/index.py`
- `_parse_input` in `lambda/drink-log-analyze/index.py`
- `validate_nearby_input` and the resolve-input validator in
  `lambda/drink-log-analyze/places.py`

Each of these rejects unknown fields with "Field is not accepted", so set
`additionalProperties: false` and mark the mandatory fields `required`.
Keep the existing note that GPS coordinates are body-only and never persisted.

## F6 — guard that the upload limits stay in their one home

`tests/test_drink_log_contract.py` used to assert the `UPLOAD_MAX_BYTES` /
`IMAGE_MAX_BYTES` defaults inside `lambda/drink-logs/drink_log_store.py` and
`lambda/drink-log-analyze/index.py`. Those cases now point at
`lambda/common/python/whiskey_common/upload_limits.py` instead, so
re-introducing `int(os.environ.get("UPLOAD_MAX_BYTES", "4000000"))` inside a
handler would go undetected.

Add a test asserting that no `UPLOAD_MAX_BYTES` or `IMAGE_MAX_BYTES` environment
read exists anywhere under `lambda/` outside `upload_limits.py`. Follow the
file's existing style (read the sources, regex, assert with a message naming the
offending file). It must pass today.

## F7 — tie the declared statuses to the handlers

Much of the new `swagger.yml` was hand-transcribed from the handlers, and
nothing stops the two drifting apart again.

Add a test that extracts the integer status literals the handlers actually
produce — the first argument of `create_response(` in `lambda/drink-logs/index.py`,
`lambda/drink-log-analyze/index.py` and `lambda/drink-log-places`'s `places.py`,
plus the status codes returned from the `_handle_*` route functions and
`_EXCEPTION_MAPPERS` in `lambda/drink-logs/index.py` — and asserts each is
declared somewhere in `swagger.yml` for that module's routes.

Be pragmatic: a per-module "every status this module can emit appears in the set
of statuses swagger declares for that module's paths" assertion is enough. Two
statuses are legitimately undeclared because API Gateway makes them unreachable
— `405` (`lambda/drink-logs/index.py:411` and `places.py:487`) and the
`404 Not found` at `places.py:513`. Exclude them with a named, commented
allowlist rather than weakening the assertion.

Put this in `tests/lambda/test_openapi_contract.py`.

---

## Report back

State per item what you changed and which verification command you ran. If an
item is wrong on contact with the code, leave it untouched, say so explicitly,
and finish the rest. Do not report an item as complete when it is partial — the
previous round did that on the CDK split and it cost a re-run.
