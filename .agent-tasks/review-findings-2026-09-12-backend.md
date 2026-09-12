# Task: eliminate the duplicated Lambda helpers and the constant drift found in review

## Context

A two-axis code review of the whole repository found that `CLAUDE.md`'s rule

> ### 共通モジュール（`lambda/common/python/whiskey_common/`）
> Lambda レイヤとして各関数に付く。**同じことを各 Lambda で再実装しないこと。**

is the most-breached rule in the codebase, and that several constants have drifted
across languages without a guarding test.

This task fixes the **backend** half. Docs/OpenAPI/frontend are a separate task —
do not touch `swagger.yml`, `API_REFERENCE.md`, `CONTEXT.md`, `CLAUDE.md`, or
`frontend/` in this task.

## Ground rules

- Behaviour must not change, except where a work package says so explicitly.
- Public HTTP response shapes must not change, except W6.
- Do not add dependencies. Do not change DynamoDB schema. Do not touch IAM.
- Do not commit. Leave the work in the working tree.
- Python 3.14 is the local interpreter; the Lambda runtime is Python 3.12 —
  do not use syntax newer than 3.12.
- The repo root is the working directory for `pytest`.

## Verification commands (all must pass when you are done)

```bash
python -m pytest tests -q          # from the repo root; 360 tests pass today
cd infra && npm run build && npx jest
```

`frontend` is untouched by this task, so you do not need to run its checks.

---

## W1 — one home for the time helpers

`_utc_now` / `_rfc3339` exist in four places:

- `lambda/common/python/whiskey_common/cost_guard.py:42` (`_rfc3339` only)
- `lambda/drink-logs/lifecycle.py:22,26` (`utc_now`, `rfc3339` — **public**)
- `lambda/drink-logs/reconciler.py:30,34`
- `lambda/drink-log-analyze/index.py:114,118`

**They are not all identical.** `lifecycle.rfc3339` formats with
`isoformat(timespec="milliseconds")`; the other three use the default
`isoformat()` (microseconds). Persisted timestamps therefore differ in
precision between the lifecycle writer and the rest.

Create `lambda/common/python/whiskey_common/timeutils.py` exporting:

- `utc_now() -> datetime`
- `rfc3339(value: datetime) -> str` — default `isoformat()` precision, i.e. the
  behaviour of `cost_guard`, `reconciler` and `drink-log-analyze` today
- `rfc3339_millis(value: datetime) -> str` — `timespec="milliseconds"`, i.e. the
  behaviour of `lifecycle` today

Re-export `utc_now`, `rfc3339` and `rfc3339_millis` from
`whiskey_common/__init__.py` alongside the existing names.

Then delete the four local copies and import from `whiskey_common.timeutils`.
**Preserve each call site's current precision** — `lifecycle` keeps millisecond
output (bind `rfc3339 = rfc3339_millis` at the lifecycle module level, or update
its call sites; `lifecycle.utc_now` and `lifecycle.rfc3339` are referenced from
`lambda/drink-logs/index.py` as `lifecycle_module.utc_now()` /
`lifecycle_module.rfc3339(...)`, so those two names must stay importable from
`lifecycle`). This work package must not change a single stored timestamp's
format. If a test asserts on precision, that assertion must still pass unchanged.

## W2 — one `ValidationError`

`class ValidationError(ValueError)` with a `fields: dict[str, str]` attribute is
defined three times with byte-identical bodies:

- `lambda/drink-logs/drink_log_store.py:44`
- `lambda/drink-log-analyze/index.py:91`
- `lambda/drink-log-analyze/places.py:49`

Move it to a new `lambda/common/python/whiskey_common/errors.py`, re-export from
`whiskey_common/__init__.py`, and import it in all three modules. Keep the name
`ValidationError` importable from each of the three modules exactly as it is
today (tests and `local_api/` import it from them).

## W3 — one `_parse_json_body`

Duplicated verbatim at `lambda/drink-logs/index.py:92` and
`lambda/drink-log-analyze/places.py:94`, and inlined again inside
`lambda/drink-log-analyze/index.py` (~line 136).

Put `parse_json_body(event) -> dict[str, Any]` in
`whiskey_common/requests.py` (new module), raising the shared
`ValidationError` from W2 with the same two messages it raises today
(`{"body": "A JSON object is required"}` and `{"body": "Malformed JSON"}`).
Replace all three sites.

## W4 — one `_request_id`

The same four-line "aws_request_id → requestContext.requestId → 'unknown'"
fallback appears at `lambda/drink-logs/index.py:85`,
`lambda/drink-log-analyze/index.py`, and inlined in
`lambda/whiskeys-search/index.py:80` and `lambda/whiskeys-list/index.py:37`.

Add `request_id(event, context) -> str` to the same new
`whiskey_common/requests.py` and replace all four sites.

## W5 — one `UUID_TEXT`

The identical UUID regex source string is declared at
`lambda/drink-log-analyze/index.py:56`, `lambda/drink-logs/reconciler.py:26` and
`lambda/drink-logs/drink_log_store.py:39`.

Put `UUID_TEXT` in `whiskey_common/normalize.py` (it already holds text
primitives) or in `whiskey_common/requests.py` — your call, but one home — and
import it at all three sites. The composed regexes (`UPLOAD_KEY_RE`,
`LOG_KEY_RE`, `ANALYSIS_ID_RE`) stay where they are.

## W6 — drop the two dead response fields

Both are unreachable or unconsumed dead weight:

1. `lambda/drink-logs/index.py:350` — `_handle_timeline` returns the same list
   under both `"results"` and `"drink_logs"`. `API_REFERENCE.md` fixes the
   collection shape as `{results, count, next_token}`; `drink_logs` appears in no
   spec and `grep -r drink_logs frontend/` finds zero consumers. Remove the
   `"drink_logs"` key.
2. `lambda/whiskeys-search/index.py:74` — the search response hardcodes a
   top-level `"distillery": ""` that is always the empty string. Remove that
   top-level key.

**Do not** remove the per-item `distillery` field from
`transform_whiskey_item` (`whiskeys-search/index.py:35`) or from
`whiskeys-list/index.py:68` — the frontend still displays it and that is a
deliberate decision. Only the always-empty top-level key goes.

Update any test that asserts on the removed keys.

## W7 — retire the stale `WHISKEYS_TABLE` env var name

`CLAUDE.md` documents `WHISKEY_SEARCH_TABLE` and declares the `Whiskeys-dev`
table retired, but `lambda/whiskeys-list/index.py:60` still reads
`os.environ["WHISKEYS_TABLE"]`, and the CDK stack sets **both** names to the
same table for the search Lambda:

- `infra/lib/whiskey-infra-stack.ts:523` — list Lambda: `WHISKEYS_TABLE`
- `infra/lib/whiskey-infra-stack.ts:544,545` — search Lambda: both names

Make `WHISKEY_SEARCH_TABLE` the only name:

- `lambda/whiskeys-list/index.py` reads `os.environ["WHISKEY_SEARCH_TABLE"]`
- `infra/lib/whiskey-infra-stack.ts:523` sets `WHISKEY_SEARCH_TABLE`
- delete the redundant `WHISKEYS_TABLE` at `:544`
- update `local_api/main.py:32-33` (drop the `WHISKEYS_TABLE` entry)
- update `tests/lambda/test_whiskeys_search.py:21-22` and
  `tests/local_api/test_drink_logs_flow.py:24` accordingly

This is an env-var rename only. It must not rename the DynamoDB table, change a
CDK logical ID, or alter the CDK construct tree. `cd infra && npx jest` must
still pass.

## W8 — `SERVING_STYLES` has one owner per language, and a test that says so

The set is declared three times:

- `lambda/drink-logs/drink_log_store.py:22`
- `lambda/drink-log-analyze/index.py:53`
- `frontend/types/whiskey.ts:1` (do **not** edit the frontend in this task)

Move the Python set to `whiskey_common` (a new
`whiskey_common/serving_styles.py`, or `normalize.py` — one home) and import it
in both Lambda modules, keeping `SERVING_STYLES` importable from
`drink_log_store` (`lambda/drink-logs/index.py:42` imports it from there).

Then extend `tests/test_drink_log_contract.py` with a test that fails when the
Python set, `frontend/types/whiskey.ts`'s `SERVING_STYLES` array, and
`swagger.yml`'s `ServingStyle` enum disagree. Follow the file's existing style:
read each file's text, extract the members with a regex, compare the sets, and
assert with a message naming the file that drifted. Note in a comment that the
three are cross-language duplicates kept in step by this test, mirroring the
`UPLOAD_MAX_BYTES` precedent. All three agree today, so the new test passes.

## W9 — reuse the shared scan pagination in the reconciler

`lambda/drink-logs/reconciler.py:67` `_scan_all` is a hand-rolled unbounded scan
loop that reimplements `whiskey_common/scan_utils.py:scan_all_pages`.

The two differ: `_scan_all` loops until exhaustion with no page cap;
`scan_all_pages` caps at `max_pages` and returns a continuation token instead of
raising. The reconciler is a daily job that **must** see every record — do not
silently truncate it.

Replace `_scan_all` with a call to `scan_all_pages`, passing a `max_pages` high
enough for the job (define it as a named module constant such as
`RECONCILER_MAX_SCAN_PAGES`), and **raise** if the returned continuation token is
not `None` — a truncated reconciliation pass must fail loudly rather than
under-report. Add a test in `tests/lambda/` covering that raise.

---

## Report back

State, per work package, what you changed and which verification command you ran.
If a work package turns out to be wrong or unsafe on contact with the code, stop
on that one, leave it untouched, say so explicitly, and complete the rest.
