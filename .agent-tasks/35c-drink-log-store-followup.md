# TASK 35c: review follow-up on `refactor/drink-log-store`

Branch: `refactor/drink-log-store` (already checked out, two commits ahead of `main`).

Two independent reviews of `639321e` confirmed the refactor is behaviour-preserving — every DynamoDB
expression, transaction, presigned-URL parameter, `INTERNAL_FIELDS` strip, and exception identity
was checked line for line and is unchanged. The one real defect they found (a missing
`UsageBudgetExceeded` import turning a 429 into a 500) is **already fixed** in `7ea1b59`.

The items below are what remains. None of them may change behaviour.

---

## 1. Document the store's public interface

`CLAUDE.md`: *"YOU MUST: すべての公開APIにドキュメントを記載"*. `DrinkLogStore`'s six public
methods — `create_upload_url`, `create_drink_log`, `get_timeline`, `get_owned`, `update`, `delete` —
carry no docstrings, only the class does. The sibling modules it composes (`lifecycle.py`,
`cost_guard.py`) document their public surface.

Add a one- or two-line docstring to each. Say what it returns and, where it matters, what it raises
— `create_drink_log` returning `(record, created)`, `get_owned` returning `None` for a record that
is missing, foreign, or not `complete`, `delete` returning `False` when the conditional write is
refused, and which of `UsageBudgetExceeded` / `AnalysisConflict` / `CreateConflict` / `KeyError`
each can raise. Match the existing style; do not write essays.

## 2. `_public_record` is called across the seam

`index.py:352` and `index.py:396` call `context.store._public_record(...)`. A private method is part
of the adapter contract, which defeats the point of binding the store.

Make the store return response-shaped records itself. `update` already returns a public record;
`create_drink_log` and the detail path should too, so the route handlers never call
`_public_record`. If a route genuinely needs to shape a record the store returned raw, make the
method public and document it — but prefer the first option.

Keep the returned bodies byte-identical.

## 3. Drop the redundant `table` field

```python
table: Any | None = field(default=None, repr=False, compare=False)

def _table(self) -> Any:
    return self.table if self.table is not None else self.lifecycle.table
```

`DrinkLogLifecycle.table` is already a property over `dynamodb.Table(drinklogs_table_name)`. Two
fields for one resource plus a picker is accidental complexity, and `from_environment` only sets it
"to keep the request adapter's existing one-time Table construction".

If that one-time construction actually matters (it saves repeated `dynamodb.Table(...)` calls per
request), fix it where it belongs: give `DrinkLogLifecycle` a cached table handle, and delete both
`DrinkLogStore.table` and `_table()`. If it does not matter, just delete them and use
`self.lifecycle.table`.

**Check the tests before choosing.** Several assert on `table.query_calls`, `s3.url_calls`, and
`client.transactions`; `_store(..., table=…)` is used by the test helper to inject a fake table. If
you remove the field, update the helper to inject through the lifecycle instead. Call counts asserted
by existing tests must not change — if one would, stop and report it rather than editing the number.

## 4. Stop borrowing `UsageBudget`'s wiring

`_prepare_initial_record` reads the Analysis Result with:

```python
self.budget.dynamodb.Table(self.budget.app_state_table_name).get_item(...)
```

and reaches for `self.budget.app_state_table_name` again when building the `consume` Delete. The
Analysis Result is not a Usage Budget concern; the store is walking another module's fields to get
at a table.

Give `DrinkLogStore` its own `dynamodb` and `app_state_table_name` fields, set once in
`from_environment`, and use those. Do not add a read method to `cost_guard` for this.

## 5. One clock, one timestamp format

`_utc_now`, `_rfc3339`, and `_is_missing_s3_error` are now defined in `index.py`, in
`drink_log_store.py`, and (as `utc_now` / `rfc3339` / `_is_missing_s3_error`) in `lifecycle.py`.
Two clocks can drift, and the tests already have to patch both.

`lifecycle.py` owns them. Import from there in both `index.py` and `drink_log_store.py` and delete
the copies.

**This changes what the tests must monkeypatch.** Some tests currently patch `_utc_now` on
`drink_logs`, some on `drink_log_store`, and some on both. After consolidating, patch the one module
that defines it. Verify by reading each test, not by trial and error — a patch applied to the wrong
module makes a test pass for the wrong reason.

## 6. Put "completion" in the glossary

`docs/agents/domain.md` requires output to use `CONTEXT.md`'s vocabulary. "Completion" /
`_completion` is not in it.

**Do not rename the `_completion` DynamoDB attribute.** It is persisted on pending records
(`lifecycle.py:151`, `drink_log_store.py:314`) and written by the currently deployed Lambda; renaming
it would strand in-flight pending records.

Instead add the term to `CONTEXT.md`, in the same shape as the entries already there — a bolded
term, a one- or two-sentence definition, and an `_Avoid_:` line. It names the set of confirmed
fields staged on a pending Drink Log and applied when its image is finalised.

---

## Deliberately not changing

- `delete()` delegating straight to `lifecycle.delete()` was flagged as a Middle Man. Keep it: the
  route handlers must reach the store and nothing behind it, so a uniform store interface is worth
  one thin method.
- `_completion_from_analysis` and `_candidate_brand` stay in `drink_log_store.py`. They are pure and
  free functions as the spec required, and their only caller is `_prepare_initial_record`.

## Verification

```bash
python -m pytest tests
```

332 tests must pass. No production behaviour may change.

## Out of scope

- `infra/`, `frontend/`, `local_api/`, `scripts/`, `lambda/drink-log-analyze/`
- `cost_guard.py` behaviour
- Any DynamoDB attribute name, response body, status code, or expression
