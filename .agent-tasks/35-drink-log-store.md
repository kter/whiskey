# TASK 35: bind the Drink Log store once instead of threading wiring through every operation

Branch: `refactor/drink-log-store` (create from an up-to-date `main`).

## Context

`main` already established the pattern this task finishes. Two modules take their AWS clients and
table names **once, at construction**, and expose operations in domain terms:

- `lambda/drink-logs/lifecycle.py` — `DrinkLogLifecycle(dynamodb, s3, drinklogs_table_name, app_state_table_name, bucket_name)`
- `lambda/common/python/whiskey_common/cost_guard.py` — `UsageBudget`

The request path in `lambda/drink-logs/index.py` was not converted. Every remaining operation still
restates the same wiring in its own signature:

- `create_upload_url(dynamodb, s3, app_state_table_name, bucket_name, user_id, content_type)` (:342)
- `_prepare_initial_record(dynamodb, s3, app_state_table_name, bucket_name, user_id, …)` (:466)
- `_finish_pending_create(dynamodb, s3, drinklogs_table_name, app_state_table_name, bucket_name, record)` (:576)
- `create_drink_log(dynamodb, s3, drinklogs_table_name, app_state_table_name, bucket_name, user_id, data)` (:668)
- `_public_record(item, s3, bucket_name, user_id)` (:762)
- `get_timeline(dynamodb, s3, drinklogs_table_name, bucket_name, user_id, limit, start_key, filters)` (:778)
- `get_owned_drink_log(table, s3, bucket_name, user_id, record_id)` (:836)
- `update_drink_log(table, user_id, record_id, data)` (:849)
- `delete_drink_log(dynamodb, s3, drinklogs_table_name, app_state_table_name, bucket_name, user_id, record_id)` (:906)

`_RouteContext` (:925) exists only to carry that bag — five of its eleven fields are wiring, and
each `_handle_*` function's job is largely to unpack them again.

The cost lands on the tests: `tests/lambda/test_drink_logs.py` hand-builds `StaticTable`,
`RecordingClient`, and `TransactionCanceled` doubles because there is no interface to test through.

## What to do

**This is a pure refactor. No externally observable behaviour may change** — same status codes,
same response bodies (Japanese strings byte for byte), same headers, same DynamoDB expressions,
same transaction contents and ordering, same presigned-URL parameters and expiries, same exception
types raised in the same situations.

### 1. Add a `DrinkLogStore`

A module in `lambda/drink-logs/` — a frozen dataclass, matching `DrinkLogLifecycle`'s style — that
takes the clients and names once and **composes the two existing bound modules** rather than
duplicating them:

```python
@dataclass(frozen=True)
class DrinkLogStore:
    lifecycle: DrinkLogLifecycle
    budget: UsageBudget
    s3: Any
    bucket_name: str
    ...
    @classmethod
    def from_environment(cls, dynamodb, s3) -> "DrinkLogStore": ...
```

It owns the operations listed above, in domain terms:

```
store.create_upload_url(user_id, content_type)
store.create_drink_log(user_id, data)            -> (record, created)
store.get_timeline(user_id, limit, start_key, filters)
store.get_owned(user_id, record_id)
store.update(user_id, record_id, data)
store.delete(user_id, record_id)
```

Private helpers (`_prepare_initial_record`, `_finish_pending_create`, `_public_record`,
`_read_s3_body`, `_safe_image_key`, `_analysis_identity`, `_extract_upload_uuid`) become
implementation of that module. Pure validation (`validate_*`, `parse_timeline_query`,
`_validate_rating`, `_completion_from_analysis`, `_candidate_brand`) has no wiring and must
**stay a free function** — do not drag it inside the store.

### 2. Shrink `_RouteContext`

Replace `dynamodb`, `s3`, `table`, `drinklogs_table_name`, `app_state_table_name`, `bucket_name`
with a single `store` field. `_RouteContext` should end up as `event, query, store, user_id,
record_id`. The `_handle_*` functions, `_route_key`, `_map_exception`, `_dispatch`, and the error
mappers keep their current shape and behaviour.

### 3. Build it once in `lambda_handler`

`lambda_handler` reads the environment and constructs the store once, then dispatches. Environment
variable names, defaults, and the point at which a missing variable raises must not change.

## Things that will bite you — check each one

- **`get_owned_drink_log` and `update_drink_log` take a `table`, not a `dynamodb`.** They are called
  with `context.table`, which `lambda_handler` builds separately. Folding these into the store must
  not turn a single `Table` reference into a fresh `dynamodb.Table(...)` call per operation if that
  changes call counts a test asserts on. Check `DrinkLogLifecycle.table` — it is a property that
  constructs on each access; match whatever the existing tests expect.
- **`ConsistentRead`.** Several reads set it explicitly. Preserve it exactly per call site; do not
  standardise.
- **Timeline paging.** `get_timeline` loops up to `TIMELINE_MAX_PAGES` (env-overridable, default
  `MAX_TIMELINE_PAGE_QUERIES`) and builds filter expressions conditionally. The number of `query`
  calls and the `next_token` encoding must not change — `tests/lambda/test_drink_logs.py` asserts
  on `query_calls`.
- **Presigned URLs.** `PRESIGNED_POST_SECONDS = 120` and `PRESIGNED_GET_SECONDS = 900`, and the
  conditions/fields on the presigned POST, must be byte-identical.
- **`INTERNAL_FIELDS` stripping** happens in `_public_record`. Every response path that returns a
  record must still strip exactly that set and still attach the presigned `image_url`.
- **Exception identity.** `create_drink_log` raises `KeyError(record_id)` for a foreign record and
  `CreateConflict` for a deleting one; `_map_exception` distinguishes them. Do not convert these to
  a new store-level exception type.
- **`UsageBudget` and `DrinkLogLifecycle` already own their pieces.** Do not re-implement counter
  updates or state transitions in the store — call them. If the store needs something they do not
  expose, add it to the module that owns it, not to the store.

## Verification (run all of these)

```bash
python -m pytest tests
```

`tests/lambda/test_drink_logs.py` and `tests/local_api/` must pass. Update tests to exercise the
store's interface rather than the old free functions, and **delete the hand-rolled boto3 doubles
that the new interface makes unnecessary** — but only where an equivalent assertion survives at the
store's interface. Do not weaken an assertion to make it pass.

Add tests at the new interface covering, at minimum:

- `create_drink_log` returning `(record, created=False)` for an already-complete record
- resuming a `pending` record through `create_drink_log`
- `get_timeline` filter and paging behaviour
- `delete` on a record owned by another user

## Out of scope — do not touch

- `infra/`, `frontend/`, `scripts/`
- `local_api/main.py` — it imports `lambda_handler` by path and must keep working untouched
- `lambda/drink-log-analyze/`
- `lifecycle.py` and `cost_guard.py` behaviour (you may add to them, not change what exists)
- The HTTP contract in `swagger.yml`
