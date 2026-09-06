# TASK 34: replace the `MOCK_AI` / `MOCK_PLACES` in-implementation branches with injected adapters

Branch: `refactor/external-service-adapters` (already created from an up-to-date `main`).

## Context

Two external services are reached from `lambda/drink-log-analyze/`:

- **Google Places** (`places.py`) — nearby search and place details over HTTPS.
- **Amazon Bedrock** (`index.py`) — the Converse call that produces an Analysis Result.

Both already have two real behaviours: the production one, and a local-only fixture used by
`local_api` and by `tests/local_api/test_drink_logs_flow.py`. But the fixture is not an adapter —
it is an `if` branch *inside the production implementation*, checked at four separate points:

- `places.py:110` `_api_key()` returns `"local-mock-not-sent"`
- `places.py:219` `search_nearby()` returns fixture rows
- `places.py:343` `_place_detail()` returns a fixture row
- `index.py:285` `_invoke_model()` returns a fixture Analysis Result

Because a mis-set environment variable would otherwise serve fabricated data in `dev` or `prd`,
this is defended by a **runtime assertion** — `_validate_mock_guard()` — which is itself written
out twice (`places.py:73` and `index.py:119`) and called at the top of each `lambda_handler`.

Two behaviours across one interface is a real seam. Declare it, and the fixture leaves the
production path entirely.

## What to do

**This is a pure refactor. No externally observable behaviour may change** — same response bodies
(including the Japanese strings, byte for byte), same status codes, same error classes, same
ordering of validation and authentication, same Secrets Manager call timing, same fixture values.

### 1. `places.py` — a place-directory port with two adapters

Define an interface with exactly the two operations the handler needs:

```python
class PlaceDirectory(Protocol):
    def search_nearby(self, lat: float, lng: float, *, deadline: float | None = None) -> list[dict[str, Any]]: ...
    def place_detail(self, place_id: str, *, deadline: float) -> dict[str, Any] | None: ...
```

- `GooglePlaceDirectory` — holds the API key and performs the HTTP calls. It absorbs the current
  bodies of `search_nearby`, `_place_detail`, `_json_response`, `_attributions`, `_display_name`,
  and the API-key loading in `_load_api_key`. The module-level `_PLACES_API_KEY` cache must keep
  its current behaviour: the secret is fetched **lazily, only after the caller is authenticated**,
  and cached across invocations in the same execution environment. Do not move the lookup earlier.
- `LocalPlaceDirectory` — returns the current fixture values verbatim: `mock-place-1` /
  `モックバー` / `東京都モック区1-1` / `[]` for search, and `モック店舗 {place_id}` / `[]` for detail.
- A selector — e.g. `select_place_directory()` — that validates the mock guard and returns the
  local adapter when `ENVIRONMENT == "local"` and `MOCK_PLACES` is set, otherwise the Google one.

`resolve_places(...)` and the handler take the directory **as a parameter** instead of `api_key`.
Delete `_api_key()` and `_mock_places_enabled()`; no `MOCK_PLACES` check may remain below the
selector.

### 2. `index.py` — a bottle-reader port with two adapters

Same shape, one operation:

```python
class BottleReader(Protocol):
    def read(self, image: bytes, *, timeout_seconds: float) -> dict[str, Any] | None: ...
```

- `BedrockBottleReader` — absorbs `_bedrock_client`, the `converse` call, the fence stripping, the
  `_validate_model_output` call, and the current exception mapping. Keep the exact current return
  contract: `None` on `BotoCoreError`/`ClientError`, `{}` on JSON/type/value errors, otherwise the
  validated payload or `{}`.
- `LocalBottleReader` — returns the current fixture dict verbatim, including
  `Decimal("0.9")` for confidence.
- A selector that validates the mock guard and picks one.

The **budget check must stay where it is**: `_invoke_model` currently returns `None` *before*
touching the client when `remaining_ms < MIN_INVOKE_BUDGET_MS`. That decision belongs to the
caller, not the adapter — keep it outside the reader so `LocalBottleReader` is also skipped when
the budget is exhausted, exactly as today.

### 3. One mock guard

`_validate_mock_guard` is currently duplicated verbatim in both files. Move it into
`lambda/common/python/whiskey_common/` (a small module, or an existing suitable one) and have both
adapters' selectors call it. Its message and exception type must not change:
`RuntimeError("MOCK_AI and MOCK_PLACES are permitted only in local")`.

## Things that will bite you — check each one

- **Selection must happen per invocation, not at import.** `tests/local_api/test_drink_logs_flow.py`
  and several Lambda tests `monkeypatch.setenv("MOCK_PLACES", ...)` *after* the module is imported.
  If you build the adapter at module scope, those tests will read stale environment. Select inside
  `lambda_handler` (or in a function it calls per request).
- **The guard runs before authentication.** `_validate_mock_guard()` is currently the first thing
  in both handlers, before the 401 path. A request with `MOCK_PLACES` set in `dev` must still raise
  rather than return 401. Preserve that ordering.
- **The secret lookup runs after authentication.** `places.py:445` has a comment saying so
  explicitly. Constructing `GooglePlaceDirectory` must not fetch the secret; only its first call
  may. Keep the lazy cache.
- **Deadlines are threaded through, not stored.** `_place_detail` takes an absolute
  `time.monotonic()` deadline and raises `UpstreamTimeout` when it has passed; `search_nearby`
  takes an optional one. Keep them as call arguments — do not bind a deadline into the adapter at
  construction, since `resolve_places` recomputes it per batch attempt.
- **`MAX_BATCH_ATTEMPTS` retry behaviour** in `resolve_places` must be unchanged, including which
  exceptions it retries and when it falls back to `_placeholder(log_id)`.
- **`local_api/main.py`** imports these modules by path and sets `MOCK_AI` / `MOCK_PLACES`. It must
  keep working with no change to `main.py` — if you find yourself editing it, the seam is in the
  wrong place.

## Verification (run all of these)

```bash
python -m pytest tests
```

Existing tests must pass **unchanged in intent**. You may add tests, and you may adjust tests that
poke at now-private helpers (`_api_key`, `_mock_places_enabled`, `_invoke_model`) so they exercise
the adapters through the new interface instead — but do not weaken an assertion to make it pass,
and do not delete a test without replacing its coverage.

Add tests that cover, at the new interface:

- `LocalPlaceDirectory` and `LocalBottleReader` return the documented fixtures.
- The selector returns the local adapter only when `ENVIRONMENT == "local"` **and** the flag is set.
- The selector raises `RuntimeError` when a `MOCK_*` flag is set outside `local`.
- `resolve_places` works against an injected fake directory with no environment variables at all.

## Out of scope — do not touch

- `infra/`, `frontend/`, `local_api/`, `scripts/`
- `lambda/drink-logs/`
- Any change to prompts, model ids, field masks, limits, or the response schema
- `brands.json` (either copy)
