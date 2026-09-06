# TASK 34b: follow-up fixes on `refactor/external-service-adapters`

Branch: `refactor/external-service-adapters` (already checked out, one commit ahead of `main`).

Two independent reviews of commit `5502182` found the items below. Fix all seven. Nothing here
changes the shape of the refactor — the ports and adapters stay.

---

## 1. Correctness regression: a misconfigured Places secret now degrades silently

**This is the important one.**

Before the refactor, `places.lambda_handler` fetched the API key eagerly, immediately after the 401
check and **outside** the request `try` block:

```python
    # Fetch the Places secret only after the caller is authenticated, so
    # unauthenticated requests never trigger a Secrets Manager lookup.
    api_key = _api_key()
    try:
        request_body = _parse_json_body(event)
```

A `RuntimeError` from a missing `PLACES_SECRET_NAME`, non-JSON secret, or wrong secret schema
therefore propagated as an unhandled Lambda error.

Now the key is loaded lazily inside `GooglePlaceDirectory.search_nearby` / `place_detail`, which are
called *inside* the `try`. The consequences:

- `POST /places` → the `RuntimeError` is caught and returned as **500 `{"error": "Internal server error"}"`**
- `POST /places/resolve` → it is raised inside a `ThreadPoolExecutor` future and swallowed by
  `except Exception: details[place_id] = None`, producing a **200** full of
  `店舗情報を取得できません` placeholders

A misconfigured secret must not look like a successful response.

**Fix:** add a `prepare()` operation to the `PlaceDirectory` protocol.

- `GooglePlaceDirectory.prepare()` forces `_load_api_key()`.
- `LocalPlaceDirectory.prepare()` is a no-op.
- `lambda_handler` calls `directory.prepare()` at exactly the old `api_key = _api_key()` position:
  after the 401 return, before `_parse_json_body`, **outside** every `try`.

Keep the explanatory comment about post-authentication fetching, updated to name `prepare()`.

Add a test that a `RuntimeError` from the secret lookup propagates out of `lambda_handler` for both
`/places` and `/places/resolve`, rather than becoming a 500 or a 200.

## 2. Remove the unreachable defensive branch

In `GooglePlaceDirectory._load_api_key`:

```python
            api_key = _PLACES_API_KEY
            if api_key is None:  # Defensive only; the branch above always assigns it.
                raise RuntimeError("PLACES_SECRET_NAME is required")
```

Unreachable by its own comment, and it reports the wrong cause if ever reached. Delete it.

## 3. Remove `_PLACES_API_KEY_LOCK`

The lock was not asked for. With `prepare()` restored (item 1), the module-level cache is populated
on the handler thread before any `ThreadPoolExecutor` worker runs — exactly as it was before the
refactor. Remove the lock and the `threading` import if nothing else uses it.

## 4. Rename the analyze port onto the glossary

`CONTEXT.md` defines **Analysis Result** ("a time-limited reading of one uploaded photo … containing
Whiskey Candidates and a suggested serving style") and **Whiskey Candidate**. It has no "bottle".
`docs/agents/domain.md` requires output to use glossary terms.

Rename in `lambda/drink-log-analyze/index.py` and its tests:

- `BottleReader` → `AnalysisReader`
- `BedrockBottleReader` → `BedrockAnalysisReader`
- `LocalBottleReader` → `LocalAnalysisReader`
- `select_bottle_reader` → `select_analysis_reader`
- the `bottle_reader=` parameter on `analyze_upload` and `_invoke_model` → `reader=`

Keep the method name `read`. Update its docstring to say it returns a raw Analysis Result payload.

## 5. Validate the model id before selecting the reader

`lambda_handler` currently does:

```python
    model_id = os.environ.get("BEDROCK_MODEL_ID", "")
    bottle_reader = select_bottle_reader(model_id)
    model_id = _validate_runtime_config(model_id)
```

The reader is constructed from an id that has not yet passed the allowlist check. Reorder so
`_validate_runtime_config()` runs first and the reader is built from the validated id.

Then drop the now-pointless indirection:

- `_validate_runtime_config(model_id: str | None = None)` — remove the optional parameter; it has
  one caller and the parameter causes a second read of `BEDROCK_MODEL_ID`.
- `select_analysis_reader(model_id)` — make `model_id` required, and remove the
  `or os.environ.get("BEDROCK_MODEL_ID", "")` fallback, which was a third read of the same variable.

Do not change what `_validate_runtime_config` validates or the error it raises.

## 6. Finish de-duplicating the local-fixture predicate

Both selectors now repeat the same shape:

```python
os.environ.get("ENVIRONMENT") == "local" and environment_flag_is_set("MOCK_PLACES")
```

Add to `whiskey_common/mock_guard.py`:

```python
def local_fixture_enabled(flag_name: str) -> bool:
    """Return whether a local-only fixture adapter is selected."""
```

Use it in both selectors. `environment_flag_is_set` is used for nothing else — make it private to
`mock_guard` (`_environment_flag_is_set`) and stop importing it into the two Lambda modules.

## 7. Two test assertions

- **Restore a weakened assertion.** `test_secret_schema_is_strict_and_cached` used to assert
  `places._load_api_key() == "abc"`. The rewrite asserts only that `search_nearby` returns `[]` and
  that Secrets Manager was called once — the secret value reaching the adapter is no longer checked
  anywhere. Assert it again through the new interface (for example, capture the
  `X-Goog-Api-Key` header the stubbed `requests.post` receives).
- **Complete a fixture assertion.** `test_mock_ai_output_uses_valid_new_schema` checks the key set
  and `name_ja` but not `Decimal("0.9")`, which the task called out explicitly. Assert the fixture
  verbatim, the way `test_local_place_directory_returns_documented_fixtures` does.

---

## Verification

```bash
python -m pytest tests
```

All tests must pass. No production behaviour may change beyond item 1, which **restores** the
pre-refactor behaviour.

## Out of scope

- `infra/`, `frontend/`, `local_api/`, `scripts/`, `lambda/drink-logs/`
- The port/adapter structure itself
- Prompts, model ids, field masks, limits, response schemas
