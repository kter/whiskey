# TASK 36: drop the dead global state in `useDrinkLogs` and unify the error-message helper

Branch: `refactor/drink-logs-composable` (create from an up-to-date `main`).

## Context

`frontend/composables/useDrinkLogs.ts` keeps three pieces of global state:

```ts
const loadingCount = useState<number>('drink-logs-loading-count', () => 0)   // :187
const error = useState<string | null>('drink-logs-error', () => null)        // :188
const loading = computed(() => loadingCount.value > 0)                       // :189
```

`loading` and `error` are exported (:310-328) and **no caller reads either one**. The four call
sites — `pages/logs/index.vue:12`, `pages/logs/[id].vue:19`, `components/DrinkLogImage.vue:16`,
`composables/useVisiblePlaceResolver.ts:15`, plus `useDrinkLogRecordingSession.ts:147` — destructure
only the operations and the `logs` / `upsertLog` / `upsertLogs` / `removeLog` store. Each page keeps
its own `initialLoading` / `loadingMore` / `saving` / `deleting` / `pageError` refs instead.

That makes `run()` (:191-202) pure overhead: it increments a counter nobody reads, writes a message
into a ref nobody renders, and rethrows the original cause unchanged. The per-operation Japanese
fallback strings it passes in are never displayed — `useApi`'s `errorMessageFor` (`useApi.ts:31`)
already produces the message that actually reaches the user.

Separately, the same three-line helper exists **four times**:

- `useDrinkLogs.ts:131` `normalizeDrinkLogError` (exported)
- `pages/logs/index.vue:31` `errorMessage`
- `pages/logs/[id].vue:56` `errorMessage`
- `composables/useDrinkLogRecordingSession.ts:354` `errorMessage`

They are semantically identical: `ApiError` extends `Error`, so `cause instanceof Error &&
cause.message ? cause.message : fallback` covers the `instanceof ApiError` branch too.

## What to do

**No user-visible behaviour may change.** No rendered string, no loading indicator, no error banner
may differ.

### 1. Remove the dead global state

- Delete `loadingCount`, `loading`, `error`, and the `run()` wrapper.
- Each operation calls `api.request(...)` (or `uploadToS3`) directly and returns its promise.
- Remove `loading` and `error` from the returned object.
- Delete the per-operation Japanese fallback strings that existed only as `run()`'s first argument.

Keep everything else in the composable exactly as it is: `logs`, `upsertLog`, `upsertLogs`,
`removeLog`, `uploadToS3` and its XHR progress shim, `buildDrinkLogPayload`, `sortDrinkLogs`, and
all the transport DTO types.

### 2. One error-message helper

Keep `normalizeDrinkLogError` as the single implementation. Move it to `frontend/utils/drinkLogs.ts`
so a page can import it without pulling in the composable, re-export it from `useDrinkLogs.ts` if
anything already imports it from there, and replace the three inline `errorMessage` copies with it.

## Things that will bite you — check each one

- **Confirm the state really is unread before deleting.** Grep the whole of `frontend/` (including
  `components/`, `layouts/`, and tests) for `drink-logs-loading-count` and `drink-logs-error`, and
  for `.loading` / `.error` accessed off a `useDrinkLogs()` result. If any consumer exists, stop and
  say so in your summary rather than deleting it.
- **`run()` also resets `error.value = null` on every call.** Nothing observes that either, but
  verify it before removing.
- **`uploadToS3` is not wrapped in `run()`** in the same way as the others — check its current shape
  before touching it. Its progress callback and XHR error handling must be untouched.
- **Order of `await` inside the operations must not change.** Some call sites rely on the request
  starting before other work; keep each operation a direct return of the request promise.
- **`useDrinkLogRecordingSession` injects these operations** through `DrinkLogRecordingSessionDependencies`
  (`:49`). The injected function types must not change shape.
- **Do not touch `useApi.ts`.** In particular, leave the `navigateTo('/login')` call at `useApi.ts:60`
  alone — where the auth-redirect seam belongs is a separate question, not this change.

## Verification (run all of these)

```bash
cd frontend
npm run lint
npm run typecheck
npx vitest run
```

(`npm test` is watch mode in this repo — use `npx vitest run`.)

`frontend/tests/composables/useDrinkLogs.test.ts` must pass. Update it where it asserts on removed
state, but do not weaken an assertion about the transport behaviour. Add a test that the unified
helper returns the cause's message when present and the fallback otherwise.

## Out of scope — do not touch

- `lambda/`, `infra/`, `local_api/`, `scripts/`
- `useApi.ts`
- Any page's own `pageError` / `loadError` / `actionError` refs, or its loading refs
- `useVisiblePlaceResolver.ts`
