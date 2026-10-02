# Task

Stage 1 of the post-real-photo fixes: stop the fixed 95% confidence (#54), show the catalog's
official brand name when a brand matches (#53), and make daily-limit errors understandable without
burning upload quota (#56, frontend part only).

Branch: `fix/analyze-accuracy-and-quota-messages` (already checked out). Do not commit.

## Goal

A real-photo run of 32 images showed: every candidate reported 95% confidence (including a wrong
brand), brands present in `brands.json` were displayed with the model's misspelling, and the third
batch of 10 failed with "リクエストが集中しています" while the real cause was a UTC-day quota that
only resets at 09:00 JST. These are small, high-impact fixes.

## Repository context

- Backend: Python Lambdas. Analysis: `lambda/drink-log-analyze/index.py` (`PROMPT`,
  `_validate_model_output`, `analyze_upload`). Catalog matching:
  `lambda/common/python/whiskey_common/candidate_resolution.py` (`BrandCatalog`,
  `WhiskeyCatalog`, `CandidateResolver`). Brand data: `scripts/catalog/brands.json` (packaged copy
  `lambda/drink-log-analyze/brands.json`, kept identical by an existing test — do not edit either).
- Quotas: `lambda/common/python/whiskey_common/cost_guard.py`. Daily keys use the **UTC** date.
  Error bodies today: analyze 429 `{"error": "Daily analysis limit exceeded"}`, analyze 503
  `"Monthly analysis budget exhausted"`, upload-url 429 `"Daily upload limit exceeded"`,
  create 429 `"Daily create or storage limit exceeded"`, search/list 429 `"Daily scan budget exceeded"`.
- Frontend: Nuxt 3 + Vitest. `frontend/composables/useApi.ts` (`errorMessageFor`, `ApiError`),
  `frontend/composables/useDrinkLogRecordingSession.ts` (batch of up to 10, concurrency 2:
  resize → getUploadUrl → uploadToS3 → analyze), `frontend/pages/logs/new.vue` (candidate UI),
  `frontend/composables/useDrinkLogs.ts` (`DrinkLogCandidate` type).
- API spec: `swagger.yml` `DrinkLogCandidate`; `tests/lambda/test_openapi_contract.py` checks it.
- The create flow (`lambda/drink-logs/drink_log_store.py::_candidate_brand`) stores the selected
  candidate's `brand_text` as the log's brand. `brand_source` is `matched` only when the candidate
  has `whiskey_id`.
- Repo `AGENTS.md` exists; follow it. Uncommitted user edits exist in `AGENTS.md`,
  `pyproject.toml`, `scripts/agent_call_whiskey.py` and several untracked files — never touch,
  restore, or reformat them. Never run `git checkout`/`git restore`/`git stash`.

## Part A — #54 confidence anchoring

Current: the `PROMPT` JSON example contains `"confidence":0.95`, and the model copies it.

Required:
1. Replace the literal example value so no concrete number appears (e.g. `"confidence":<0から1の数値>`),
   and add a short Japanese rubric: ラベルの銘柄名がはっきり全部読めた→高く(0.8以上)、一部だけ
   読めた・形やラベル色から推測した→低く(0.5以下)、など。Keep everything else in the prompt
   semantically unchanged. Make sure `_validate_model_output` still accepts the output format.
2. Server-side cap in `CandidateResolver.resolve()`: if the candidate has **no** brand match
   (`brand_key` absent), cap `confidence` at `Decimal("0.6")` (keep the value if lower). Do
   **not** boost matched candidates — a wrong-but-catalogued brand (e.g. Machrie Moor read as
   Macallan) would then look safer. Put the cap value in a named module constant.
3. Frontend: in `logs/new.vue`, show a 「要確認」 badge next to a candidate (both the multi-candidate
   buttons and the single-candidate "AIの読み取り" line) when `brand_key` is absent or
   `confidence < 0.7`. Put the threshold/predicate in one exported helper (e.g. in
   `frontend/utils/drinkLogs.ts`) and unit test it. Add optional `brand_key?: string`
   (and the new field from Part B) to the `DrinkLogCandidate` TS type if missing.

## Part B — #53 official brand name on brand match

Current: on a `BrandCatalog` match, `CandidateResolver.resolve()` only adds `brand_key` /
`distillery_ja`; `brand_text` and `name_ja` keep the model's (often misspelled) text.
`BrandCatalog.resolve_exact` already matches on `brand_ja` **or** `brand_en` (normalized, with
aliases), so a correctly read English brand rescues a misspelled Japanese one.

Required:
1. When `brand_matched` is not None and the matched record has a non-empty `brand_ja`:
   - Derive the suffix (age/edition text) from the model's `name_ja`: if `name_ja` starts with the
     model's own `brand_ja` (compare after whitespace trimming; also try NFKC), the suffix is the
     remainder, stripped. Otherwise, fall back to the suffix of `name_en` after the model's
     `brand_en` **only** for an age pattern like `12 Year Old` / `12 Years` / `12yo` → `12年`.
     If neither works, the suffix is empty.
   - Rebuilt name = catalog `brand_ja` + (" " + suffix if suffix). Set both `brand_text` and
     `name_ja` to it, and set `brand_ja` to the catalog `brand_ja`.
   - If the model's `name_ja` already equals the rebuilt name, nothing changes.
   - Preserve the model's original reading in a new optional field `ai_name_ja` **only when it
     differs** from the rebuilt name.
2. If a `WhiskeyCatalog` (whiskey master) exact match exists (`whiskey_id` set), keep the current
   behavior for `whiskey_id` / `match_source`; still apply the brand-name rebuild. Do not change
   `match_source` semantics.
3. Leave `name_en` as the model returned it.
4. Add `ai_name_ja: {type: string}` (optional) to `DrinkLogCandidate` in `swagger.yml`.
5. Frontend: in the single-candidate line, when `ai_name_ja` exists show it, e.g.
   「AIの読み取り: ラフロアヒグ 10年 → ラフロイグ 10年（ブランド一致）」. Label: `match_source ===
   'catalog'` → カタログ一致; else `brand_key` present → ブランド一致; else AI読取.
6. Regression tests (pytest, in the existing test module for candidate resolution / analyze —
   find it under `tests/lambda/`) using **model outputs** from the real run, where the English
   brand was read correctly but Japanese was misspelled. Use real `brand_key`s from
   `scripts/catalog/brands.json` (verify each exists and use the catalog's actual `brand_ja`):
   - `name_ja "ラフロアヒグ 10年"`, `brand_ja "ラフロアヒグ"`, `brand_en "Laphroaig"` → `ラフロイグ 10年`
   - `"バナナブハイン 12年"` / `"バナナブハイン"` / `"Bunnahabhain"` → `<catalog brand_ja> 12年`
   - `"宮城京"` / `"宮城京"` / `"Miyagikyo"` → catalog `brand_ja` for miyagikyo
   - `"ユイザ"` / `"ユイザ"` / `"Yuza"` → catalog `brand_ja` for yuza
   - suffix fallback: `name_ja "ラフロアヒグ"` (no age) with `name_en "Laphroaig 10 Year Old"` → `ラフロイグ 10年`
   - no brand match (e.g. `"ミステリーモルト"` / `"Mystery Malt"`) → name unchanged, no `ai_name_ja`,
     confidence capped at 0.6
   - already-correct name → unchanged, no `ai_name_ja`
   - matched brand keeps model confidence (e.g. 0.92 stays 0.92)
   If a listed brand_en does not match the catalog as-is, report it rather than editing the catalog
   (alias work is a separate issue, #60).

## Part C — #56 daily-limit messaging (frontend only)

Required:
1. `useApi.ts` `errorMessageFor`: inspect the body `error` string for 429/503 and return specific
   Japanese messages:
   - `Daily analysis limit exceeded` → 「本日の画像解析の上限に達しました。{reset} にリセットされます。」
   - `Daily upload limit exceeded` → 「本日の画像アップロードの上限に達しました。{reset} にリセットされます。」
   - `Daily create or storage limit exceeded` → 「本日の記録作成の上限（または保存容量の上限）に達しました。{reset} にリセットされます。」
   - `Daily scan budget exceeded` → 「本日の検索の上限に達しました。{reset} にリセットされます。」
   - `Monthly analysis budget exhausted` (503) → 「今月の画像解析の上限に達しました。」
   - anything else keeps the current generic 429 / 503 message.
   `{reset}` = the next UTC midnight formatted in the browser's local time zone as e.g.
   「10月2日 9:00」(ja-JP, month/day/hour/minute). Make the clock injectable (`now` parameter or
   similar) so tests are deterministic; test with `timeZone: 'Asia/Tokyo'` explicitly rather than
   relying on the machine zone. Do not hardcode numeric limits (the frontend does not know them).
   Export a small predicate so callers can detect a daily-quota error (e.g.
   `isDailyQuotaError(error: unknown): boolean`, true for `ApiError` 429 with one of the four daily
   bodies above, plus the monthly 503).
2. `useDrinkLogRecordingSession.ts`: once any item in the current session fails with a daily/monthly
   quota error from `getUploadUrl` or `analyze`, items that have not yet called `getUploadUrl` must
   not call it; they become `failed` with the same quota message. Items already past upload continue.
   A new `processFiles` call (new session) clears this state. `retryProcessing` of a failed item is
   still allowed (the user may retry after the reset) and clears the stop flag only if that retry
   succeeds past `getUploadUrl` — keep it simple and document the chosen rule in a one-line comment.
3. Tests (Vitest) for: each message mapping and the reset-time formatting; the session stopping
   further uploads after an analyze 429 `Daily analysis limit exceeded` (assert `getUploadUrl` call
   count); a new session resetting the stop.

## Allowed scope

- `lambda/drink-log-analyze/index.py`
- `lambda/common/python/whiskey_common/candidate_resolution.py`
- `swagger.yml` (`DrinkLogCandidate` only)
- `tests/lambda/**` (new or existing test files)
- `frontend/composables/useApi.ts`, `frontend/composables/useDrinkLogRecordingSession.ts`,
  `frontend/composables/useDrinkLogs.ts` (types only), `frontend/utils/drinkLogs.ts`,
  `frontend/pages/logs/new.vue`
- `frontend/tests/**`

## Do not change

- `scripts/catalog/*.json`, `lambda/drink-log-analyze/brands.json`
- `cost_guard.py` limits, keys, reset timing; any infra/CDK; quota-remaining API (later issue)
- serving-style logic (#55, separate)
- Stored record schema / `brand_source` semantics / `drink_log_store.py`
- The user's uncommitted files listed above

## Acceptance criteria

- No literal confidence number in the prompt's JSON example.
- Unmatched candidates never exceed 0.6 confidence; matched ones keep the model value.
- The regression cases above pass and show official names; `ai_name_ja` present only when changed.
- Analyze response remains backward compatible (only an optional field added); OpenAPI contract
  test passes.
- 429 messages are specific with a local-time reset; the session stops calling `getUploadUrl` after
  a quota error.
- 「要確認」 badge rule implemented once and tested.

## Verification

From repo root:
- `.venv/bin/python -m pytest tests` (baseline: 359 passed, 5 skipped)

From `frontend/`:
- `npm run lint`
- `npm run typecheck`
- `npm run test -- --run`

## Constraints

- Follow existing design and naming conventions
- Make the minimal change needed — no unrelated refactors or reformatting
- Do not add new dependencies
- Preserve backward compatibility of existing public APIs
- Add tests for any testable behavior change
- Do not hide failing or skipped tests — report them
- If the task turns out to need a large design change, stop and report instead of improvising

## Completion report

Report: what changed and why, files touched, each verification command and result, any listed
brand that did not match the catalog, and any deviations from this task.
