# Task: close the spec/code contradictions and the naming smells found in review

## Context

A two-axis review of the whole repository found five spec/code contradictions and
a set of naming and structure smells. The backend deduplication half is already
done and committed (`89a5a55`); this task is the rest.

## Ground rules

- Behaviour must not change anywhere. No HTTP response shape changes, no
  DynamoDB schema changes, no IAM changes, no new dependencies.
- Do not commit. Leave the work in the working tree.
- `CLAUDE.md` has **uncommitted edits by the user already in the working tree**.
  Edit only the two specific lines named in B3. Do not reformat, reorder, or
  revert anything else in that file.
- Lambda runtime is Python 3.12 — do not use syntax newer than that.

## Verification commands (all must pass when you are done)

```bash
python -m pytest tests -q                          # 362 tests pass today
cd infra && npm run build && npx jest              # 46 tests pass today
cd frontend && npm run lint && npx vitest run && npm run typecheck
```

`npm test` in `frontend/` is a watch mode that never exits — use `npx vitest run`.

---

## B1 — make `swagger.yml` describe the API that actually exists

Ten drink-log routes still declare only

```yaml
        '501': {$ref: '#/components/responses/NotImplemented'}
```

whose description reads *"Phase 4 route stub; Tasks 07 and 08 install the
implementation"* (`swagger.yml:161`). Those tasks shipped long ago: the routes
are wired in `infra/lib/whiskey-infra-stack.ts` (~`:799-822`) and implemented in
`lambda/drink-logs/index.py` and `lambda/drink-log-analyze/`. The
`DrinkLog` and `Error` schemas are defined but referenced by no response.

Replace every `'501'` stub on these ten operations with the responses the code
actually returns. **`API_REFERENCE.md` and the handlers are the authority** —
read `lambda/drink-logs/index.py` (`_dispatch`, `_handle_*`, `_map_exception`)
and `lambda/drink-log-analyze/index.py` / `places.py` and describe what they
really produce, including the error statuses they map to (400, 401, 404, 409,
429, 503 — check, do not assume).

- `POST /api/drink-logs` → 201 with `DrinkLog`
- `GET /api/drink-logs` → 200 with the collection shape `API_REFERENCE.md`
  fixes: `{results, count, next_token}`. Add a `DrinkLogPage` schema for it and
  reference it.
- `GET /api/drink-logs/{id}` → 200 with `DrinkLog`
- `PUT /api/drink-logs/{id}` → 200 with `DrinkLog`
- `DELETE /api/drink-logs/{id}` → whatever the handler returns
- `POST /api/drink-logs/upload-url`, `/analyze`, `/places`, `/places/resolve` →
  their real success shapes; add schemas where a shape is worth naming

Delete the now-unused `NotImplemented` response component. Every schema defined
under `components/schemas` must be referenced by at least one response or
request.

Keep the existing `bearerAuth` security blocks and the existing descriptions
about GPS coordinates and Google display names never being persisted.

Then extend `tests/lambda/test_openapi_contract.py` with a test asserting that
`swagger.yml` contains **no** `501` response and no `NotImplemented` component —
so this cannot silently rot back.

Note `tests/test_drink_log_contract.py::test_serving_styles_match_across_contracts`
reads the `ServingStyle` enum out of `swagger.yml` with a regex anchored on
`^    ServingStyle:\n      type: string\n      enum: [...]`. If you reformat that
block, update the regex.

## B2 — put the Drink Log lifecycle in the glossary

`CLAUDE.md:190` names `CONTEXT.md` as the place *"コードの命名はここに従う"*, and
`CLAUDE.md:192-193` describes a `pending → complete → deleting → tombstone`
lifecycle. But `CONTEXT.md` defines six nouns and **no lifecycle at all**, and
"tombstone" is not a fourth state: `lambda/drink-logs/lifecycle.py:250`
`create_tombstone` writes `"status": "deleting"`, and both `swagger.yml` and
`API_REFERENCE.md` enumerate status as `[pending, complete, deleting]`.

What a tombstone actually is, per `lambda/drink-logs/reconciler.py:176`: a
`deleting` record the reconciler creates for an **orphan image** that has no
record, so the image can be deleted under the same conditional-write exclusion
as the create path. Read `create_tombstone` and `reconcile_log_objects` and
describe it accurately.

Add to `CONTEXT.md`, in the existing style (term, definition, `_Avoid_:` line):

- a **Tombstone** entry with the accurate definition above
- a short `## Drink Log lifecycle` section naming the three real statuses,
  `pending`, `complete`, `deleting`, what moves a record between them, and where
  a Tombstone enters. Keep it to a handful of lines — a glossary, not a design doc.

Use the vocabulary already in the glossary (Drink Log, Usage Budget, Completion).

## B3 — correct the two wrong lines in `CLAUDE.md`

Only these two edits, nothing else in that file:

1. `CLAUDE.md:192-193` currently reads
   `pending → complete → deleting → tombstone の遷移と補償`.
   Correct it so the states are `pending → complete → deleting` and the
   tombstone is described as what it is (the reconciler's orphan-image record),
   consistent with what you write in B2.
2. The **Lambda Environment Variables** block lists `WHISKEY_SEARCH_TABLE` but
   not the fact that it is now the *only* name for that table. Commit `89a5a55`
   retired the stale `WHISKEYS_TABLE` alias; if the block or the surrounding
   prose still implies otherwise, correct it. If it is already accurate, leave
   it alone and say so in your report.

## B4 — resolve the `DrinkLogStore` name collision

`DrinkLogStore` currently means two unrelated things:

- `lambda/drink-logs/drink_log_store.py:1` — the DynamoDB repository
- `frontend/composables/useDrinkLogs.ts:27` — the **bar/shop** a drink was had at

`CONTEXT.md` uses the word "place" for the latter concept. Rename the
**frontend interface only**:

- `DrinkLogStore` → `DrinkLogPlace` in `frontend/composables/useDrinkLogs.ts`
  and every reference to the type across `frontend/`

Do **not** rename the wire field `store` (it is the API contract), do **not**
rename the `DrinkLogStoreDisplay.vue` component, and do **not** rename the
Python `DrinkLogStore` class. Type-name change only; `npm run typecheck` proves
it is complete.

Add a matching **Place** entry to `CONTEXT.md` if B2 has not already covered it.

## B5 — drop the alias indirection

These aliases only rename `CONTEXT.md`'s "Usage Budget" vocabulary away from it:

- `lambda/drink-logs/index.py:57-58`
  `RateLimitExceeded = UsageBudgetExceeded` and
  `TransientConflict = BudgetTransactionConflict`
- `lambda/drink-log-analyze/index.py` `BudgetExceeded = UsageBudgetExceeded`
- `lambda/drink-log-analyze/places.py` `BudgetExceeded = UsageBudgetExceeded`

Delete all four and use `UsageBudgetExceeded` / `BudgetTransactionConflict`
directly at their call sites. Check whether any test imports an alias by name
and update it. If an alias turns out to be part of a module's imported surface
that something outside the repo depends on, stop and say so instead.

## B6 — one accessor for the upload size limits

`os.environ.get("UPLOAD_MAX_BYTES", "3670016")` and the `IMAGE_MAX_BYTES`
equivalent are read as bare env lookups with magic string defaults at
`lambda/drink-logs/drink_log_store.py:212,285` and
`lambda/drink-log-analyze/index.py:517`.

Add an `UploadLimits` accessor to `whiskey_common` (e.g.
`whiskey_common/upload_limits.py`) exposing `upload_max_bytes()` and
`image_max_bytes()`, each reading its env var with the current default, and use
it at all three sites.

**This moves the constants that `tests/test_drink_log_contract.py` guards.**
That test asserts the defaults in `lambda/drink-logs/drink_log_store.py` and
`lambda/drink-log-analyze/index.py` match `infra/lib/whiskey-infra-stack.ts`.
Update its parametrised cases to point at the new single home, keeping the
`infra/lib/whiskey-infra-stack.ts` source-of-truth comparison intact — the CDK
stack stays the truth source per `CLAUDE.md`. The frontend
`frontend/utils/imageResize.ts` case must stay exactly as it is.

## B7 — name the analysis deadline

In `lambda/drink-log-analyze/index.py`, the pair `(context, started)` travels
together through `_remaining_budget_ms`, `_invoke_model`,
`_master_snapshot_within_budget` and `analyze_upload` — an unborn type.

Introduce a small frozen dataclass (e.g. `HandlerDeadline`) holding the Lambda
context and the monotonic start time, with the remaining-budget calculation as a
method on it, and thread that single value through instead of the pair. Keep the
existing budget arithmetic and constants (`HANDLER_BUDGET_MS`,
`INVOKE_SAFETY_MS`, `MIN_INVOKE_BUDGET_MS`) exactly as they are — this is a
shape change, not a behaviour change. Existing tests must pass unmodified where
they do not construct the pair directly.

## B8 — split the 874-line CDK constructor

`infra/lib/whiskey-infra-stack.ts` builds buckets, the CDN, three tables, six
Lambdas, the API and Cognito in a single constructor, so every infra change
edits one file for unrelated reasons.

Extract cohesive **private methods on the same class** (for example
`#createImageStorage`, `#createTables`, `#createApiLambdas`, `#createHttpApi`,
`#createAuth`), called in the same order from the constructor.

**Hard constraint: the synthesized CloudFormation must be identical.** Do not
introduce a nested stack, do not create new `Construct` scopes, do not change a
construct id, and do not reorder resource creation. This is a pure code-movement
refactor. Verify with:

```bash
cd infra && npm run build && npx jest
CDK_LOCAL_BUNDLING=1 npx cdk synth -c env=dev WhiskeyApp-Dev > /tmp/after.yaml
```

and confirm the template differs from the current one in nothing but Lambda
asset hashes (which B5/B6/B7 legitimately change). If you cannot hold the
template identical, **stop on this work package**, revert just it, and say so —
the other work packages must still land.

---

## Report back

State, per work package, what you changed and which verification command you
ran. If a work package is wrong or unsafe on contact with the code, leave it
untouched, say so explicitly, and complete the rest.
