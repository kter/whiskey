# TASK 37: make the cross-language Drink Log constants drift into a failing test

Branch: `test/drink-log-contract` (create from an up-to-date `main`).

## Context

Several Drink Log facts are stated independently in Python, TypeScript, and CDK, with nothing
asserting they agree. Two of them already carry a comment naming the file they must match, which is
the whole enforcement mechanism today.

**Upload size limit — `3670016` bytes, six independent statements:**

- `lambda/drink-logs/index.py:358` and `:521` — `int(os.environ.get("UPLOAD_MAX_BYTES", "3670016"))`
- `lambda/drink-log-analyze/index.py:517` — same default
- `infra/lib/whiskey-infra-stack.ts:577` and `:606` — `UPLOAD_MAX_BYTES: '3670016'`
- `frontend/utils/imageResize.ts:4` — `const MAX_OUTPUT_SIZE = 3_670_016`
- `scripts/eval/run_brand_eval.py:45` and `scripts/eval/import_real_photos.py:33` — `3_670_016`

The frontend one is a hard-coded literal while the Lambda one is environment-overridable, so raising
the CDK value silently desynchronises the client that does the resizing.

**Store-name placeholders:**

- `lambda/drink-log-analyze/places.py:45` — `PLACEHOLDER_NAME = "店舗情報を取得できません"`
- `frontend/utils/drinkLogs.ts:60` — `STORE_NAME_PLACEHOLDERS` includes that exact string, and its
  doc comment says so in prose: *"(`PLACEHOLDER_NAME` in lambda/drink-log-analyze/places.py)"*
- `frontend/components/DrinkLogStoreDisplay.vue:15` mints the other two placeholders

The repo already solves this class of problem with a test rather than a build step:
`tests/lambda/test_drink_log_analyze.py:745` asserts the two `brands.json` copies are byte-identical,
and `tests/lambda/test_openapi_contract.py` asserts `swagger.yml` against `API_REFERENCE.md`.

Follow that precedent. **Do not introduce a code generator or a build step.**

## What to do

Add a contract test module — `tests/test_drink_log_contract.py` — that reads the real files and
fails when the values disagree. It must read each source as text and extract the value, not import
the frontend.

### 1. Upload size limit

Assert a single expected value (`3670016`) equals, at minimum:

- the default in `lambda/drink-logs/index.py` (both occurrences)
- the default in `lambda/drink-log-analyze/index.py`
- `UPLOAD_MAX_BYTES` in `infra/lib/whiskey-infra-stack.ts` (both occurrences)
- `MAX_OUTPUT_SIZE` in `frontend/utils/imageResize.ts`
- `UPLOAD_MAX_BYTES` in `scripts/eval/run_brand_eval.py`
- `OUTPUT_MAX_BYTES` in `scripts/eval/import_real_photos.py`

Do the same for `IMAGE_MAX_BYTES` (`1572864`), which appears in both Lambdas and in CDK.

Write the extraction so a **missing** constant fails loudly. A regex that silently matches nothing
and passes is worse than no test — assert the match was found before comparing.

### 2. Store-name placeholder

Assert that `PLACEHOLDER_NAME` in `lambda/drink-log-analyze/places.py` appears in
`STORE_NAME_PLACEHOLDERS` in `frontend/utils/drinkLogs.ts`.

### 3. A note at each site

At each duplicated constant, add a one-line comment pointing at the contract test — the same way
`frontend/utils/drinkLogs.ts:55-59` already points at `places.py`. Keep it to one line; do not
reformat surrounding code.

## Things that will bite you — check each one

- **The test must be resilient to formatting, not to value changes.** `3_670_016`, `3670016`, and
  `'3670016'` are the same value written three ways; normalise underscores and quotes before
  comparing. But a genuinely different number must fail.
- **Do not change any current value.** This task adds a test and comments. If a value turns out to
  already disagree, **stop and report it** rather than editing either side.
- **Paths are resolved from the repo root**, following the pattern in
  `tests/lambda/test_drink_log_analyze.py:745` (`Path(__file__).resolve().parents[…]`).
- **`tests/` is the pytest testpath** (`pyproject.toml`). The new file must be collected by
  `python -m pytest tests` with no configuration change.
- **`DrinkLogStoreDisplay.vue:15`'s two placeholders are frontend-only** — they never cross the
  wire. Do not invent a Python counterpart for them.

## Verification

```bash
python -m pytest tests
```

Then prove the test actually bites: temporarily change one of the constants, confirm the test fails,
and revert it. Say in your summary that you did this and which constant you used.

## Out of scope — do not touch

- Any production behaviour, any constant's value
- `swagger.yml`, `API_REFERENCE.md`
- The serving-style enum, field-length limits, and the places batch size — a later change
- Introducing a shared JSON contract file, a code generator, or a build step
