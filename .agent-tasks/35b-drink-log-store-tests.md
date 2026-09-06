# TASK 35b: convert `tests/lambda/test_drink_logs.py` onto the `DrinkLogStore` interface

Branch: `refactor/drink-log-store` (already checked out).

## Context

The production side of the store refactor is **already committed** (`1c9ff59`):

- `lambda/drink-logs/drink_log_store.py` — new. `DrinkLogStore` binds the AWS wiring once and owns
  `create_upload_url`, `create_drink_log`, `get_timeline`, `get_owned`, `update`, `delete`, plus the
  private helpers `_prepare_initial_record`, `_finish_pending_create`, `_public_record`,
  `_read_s3_body`, `_completion_from_analysis`.
- `lambda/drink-logs/index.py` — now routing and validation only. `_RouteContext` carries
  `event, query, store, user_id, record_id`. The old free functions
  (`create_upload_url`, `create_drink_log`, `get_timeline`, `get_owned_drink_log`,
  `update_drink_log`, `delete_drink_log`, `_prepare_initial_record`, `_finish_pending_create`,
  `_completion_from_analysis`) **no longer exist on `index.py`**.
- `tests/lambda/test_drink_log_analyze.py` — already converted, passes.

`tests/lambda/test_drink_logs.py` was **not** converted and still calls the removed free functions,
so 32 of its 54 tests fail with `AttributeError: module 'drink_logs_lambda_tests' has no attribute …`.

**Only that one file needs changing.**

## What to do

Convert every call site in `tests/lambda/test_drink_logs.py` to the store's interface. **Preserve
every existing assertion exactly** — this is a mechanical rebinding, not a test rewrite. Do not
delete a test, do not relax a comparison, do not drop a comment.

### The store helper

Add near the other fakes at the top of the file:

```python
drink_log_store = sys.modules["drink_log_store"]


def _store(dynamodb, s3, *, table=None):
    return drink_log_store.DrinkLogStore(
        lifecycle=drink_logs.DrinkLogLifecycle(
            dynamodb, s3, "DrinkLogs-test", "AppState-test", "images-test"
        ),
        budget=cost_guard.UsageBudget(dynamodb, "AppState-test", drink_log_store._rfc3339),
        s3=s3,
        bucket_name="images-test",
        table=table,
    )
```

Import `cost_guard` the way the file already reaches shared modules (check the existing imports —
`from whiskey_common.cost_guard import UsageBudget` or via `load_lambda_module`; use whichever
matches the file's current style). `sys` may already be imported; check before adding it.

### The mapping

| old call on `drink_logs` | new |
| --- | --- |
| `create_upload_url(dynamodb, s3, app_state, bucket, user_id, ct)` | `_store(dynamodb, s3).create_upload_url(user_id, ct)` |
| `create_drink_log(dynamodb, s3, logs_tbl, app_state, bucket, user_id, data)` | `_store(dynamodb, s3).create_drink_log(user_id, data)` |
| `get_timeline(dynamodb, s3, logs_tbl, bucket, user_id, limit, start_key, filters)` | `_store(dynamodb, s3).get_timeline(user_id, limit, start_key, filters)` |
| `get_owned_drink_log(table, s3, bucket, user_id, record_id)` | `_store(dynamodb, s3, table=table).get_owned(user_id, record_id)` |
| `update_drink_log(table, user_id, record_id, data)` | `_store(None, None, table=table).update(user_id, record_id, data)` |
| `delete_drink_log(dynamodb, s3, logs_tbl, app_state, bucket, user_id, record_id)` | `_store(dynamodb, s3).delete(user_id, record_id)` |
| `_prepare_initial_record(dynamodb, s3, app_state, bucket, user_id, analysis_pk, upload_uuid, idx, overrides?)` | `_store(dynamodb, s3)._prepare_initial_record(user_id, analysis_pk, upload_uuid, idx, overrides?)` |
| `_finish_pending_create(dynamodb, s3, logs_tbl, app_state, bucket, record)` | `_store(dynamodb, s3)._finish_pending_create(record)` |
| `drink_logs._completion_from_analysis(...)` | `drink_log_store._completion_from_analysis(...)` (same arguments) |

`monkeypatch.setattr(drink_logs, "_utc_now", …)` and `monkeypatch.setattr(drink_logs, "uuid", …)`
must now target `drink_log_store` for any clock or UUID the store uses. Check which module actually
reads each patched name — `index.py` still has its own `_utc_now` for `_validate_create_datetime`,
so some patches may need to be applied to **both** modules. Getting this wrong makes tests pass for
the wrong reason; verify each one by reading the code that consumes it.

Validation helpers (`validate_upload_input`, `validate_create_input`, `validate_update_input`,
`parse_timeline_query`, `ValidationError`) stay on `drink_logs` — do not move those call sites.

### One new test

Add a test that `delete` refuses a record owned by another user: seed a `complete` record owned by
`user-2`, call `_store(...).delete("user-1", record_id)`, and assert it returns `False`, the record
still has `status == "complete"`, its image is still in the S3 fake, and no transaction was recorded
on the client (no storage quota was released). Place it near the other delete/timeline tests.

## Things that will bite you — check each one

- **`_store(None, None, table=…)`** works only for `update`, which touches nothing but the table.
  Do not use that shortcut for any other operation.
- **`RecordingClient` / `StateTable` / `StaticTable` / `FakeDynamoDB` / `MemoryS3` / `PresignS3`
  stay as they are.** They are still needed; this task does not delete fakes.
- **`FakeDynamoDB` takes a client** in some constructions and not others. Match the existing call at
  each site rather than standardising.
- **Assertion counts matter.** Several tests assert on `table.query_calls`, `s3.url_calls`,
  `client.transactions`, and `s3.post_call`. If the store constructs a `Table` differently from the
  old free function, a count can shift. If one does, **say so in your summary** rather than editing
  the expected number.
- **Do not touch** `lambda/`, `tests/lambda/test_drink_log_analyze.py`, or any other file.

## Verification

```bash
python -m pytest tests
```

All tests must pass — 331 expected (330 on `main`, plus the one new ownership test).

Then prove the new test bites: temporarily change its caller to the owning user, confirm it fails,
and put it back. **Restore it by editing the file, never with `git checkout` or `git restore`** —
the file has uncommitted work in it. Say in your summary that you did this.
