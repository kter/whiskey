# Follow-up correction (task 38)

Branch: `fix/analyze-accuracy-and-quota-messages` (already checked out, uncommitted work from task
38 present). Do not commit. Never run `git checkout`/`git restore`/`git stash`. Do not touch
`AGENTS.md`, `pyproject.toml`, `scripts/agent_call_whiskey.py` or other untracked user files.

## Problems found

1. **Distillery/company matches rename the product** —
   `lambda/common/python/whiskey_common/candidate_resolution.py` `CandidateResolver.resolve()`
   rebuilds the name on any `BrandCatalog.resolve_exact` match, but `exact_names` also contains
   "safe" distillery names. Reproduced with `scripts/catalog/brands.json`:
   `name_ja "サントリー 角瓶"`, `brand_ja "サントリー"` → `"響 角瓶"`;
   `"ジムビーム ホワイト"` / `"ジムビーム"` → `"ノブクリーク ホワイト"`.
2. **Rebuild is lossy** — `_brand_suffix` only uses `startswith` and otherwise collapses to the bare
   catalog brand: `"ザ・マッカラン 12年"`/`"マッカラン"` (name_en `"The Macallan 12"`, brand_en
   `"Macallan"`) → `"マッカラン"`; `"フロム・ザ・バレル"`/`"ニッカ"` → `"ニッカ"`;
   `"シングルモルト 山崎"`/`"山崎"` → `"山崎"`; `"ラフロアヒグ"` + name_en
   `"Laphroaig Quarter Cask"` → `"ラフロイグ"`.
3. **Quota message tests depend on machine TZ** — `errorMessageFor` calls
   `formatDailyQuotaReset(now)` with no time zone; `frontend/tests/composables/useApi.test.ts`
   hard-codes `10月2日 9:00`. `TZ=UTC npx vitest run tests/composables/useApi.test.ts` → 4 failed.
   CI (`.github/workflows/deploy.yml`) runs on UTC.
4. **Cap applied to exact whiskey-master matches** — a candidate with `whiskey_id`
   (`match_source == "catalog"`) but no `brand_key` is capped at 0.6 and flagged 要確認.
5. `frontend/composables/useDrinkLogRecordingSession.ts`: the inner try/catch around `analyze`
   duplicates the outer catch's quota handling; parameter `retryingQuotaError` is misnamed (it is
   true for every retry).

## Required fixes

1. Rebuild only when the match came from the brand's own names (`brand_ja`, `brand_en`,
   `aliases` — via `normalized_brand_variants`), not from distillery names. Implement as a small
   helper on `BrandCatalog` (e.g. `matches_brand_name(record_or_key, whiskey) -> bool`) reusing the
   existing normalization. On a distillery-only match keep the previous behavior: attach
   `brand_key` / `distillery_ja`, leave `name_ja` / `brand_text` / `brand_ja` untouched, no
   `ai_name_ja`.
2. Make the rebuild non-lossy by **in-place replacement**:
   - Locate the model's `brand_ja` inside `name_ja` (plain, then NFKC). If found, replace only that
     span with the catalog `brand_ja`, keeping text before and after (then collapse doubled spaces
     and strip). A leading `ザ・` / `ザ ` immediately before the span may be dropped together with it.
     e.g. `ザ・マッカラン 12年` → `マッカラン 12年`; `シングルモルト 山崎` stays `シングルモルト 山崎`.
   - Else, if `name_ja` (trimmed) equals the model's `brand_ja`, i.e. the name is just the brand:
     rebuild as catalog `brand_ja` + optional English age suffix (keep the existing fallback;
     accept `12-Year-Old`, and strip a leading `The ` from both name_en and brand_en before the
     prefix check).
   - Otherwise leave the name unchanged and do not set `ai_name_ja`.
   - `ai_name_ja` only when the final name differs from the model's `name_ja`.
3. Do not cap confidence when the candidate has a `whiskey_id` (exact whiskey-master match), and
   make `candidateNeedsConfirmation` (`frontend/utils/drinkLogs.ts`) return false-for-missing-brand
   when `whiskey_id` is present (still true when confidence < 0.7). Add optional `whiskey_id` to the
   helper's parameter type if needed.
4. `errorMessageFor(status, body, now?, timeZone?)` (or an options object) forwards the zone to
   `formatDailyQuotaReset`; the production call path keeps using the browser zone. Tests pass
   `'Asia/Tokyo'` explicitly. Must pass under `TZ=UTC`.
5. Remove the redundant inner try/catch in `processItem`; rename `retryingQuotaError` → `isRetry`.
   Keep the documented retry rule.

## Tests to add

- pytest (`tests/lambda/test_drink_log_analyze.py` or wherever the task-38 cases live):
  - `"サントリー 角瓶"`/`"サントリー"` and `"ジムビーム ホワイト"`/`"ジムビーム"`: name unchanged, no
    `ai_name_ja` (brand_key may still be set — assert what the code does).
  - `"ザ・マッカラン 12年"`/`"マッカラン"` → contains `12年`.
  - `"フロム・ザ・バレル"`/`"ニッカ"` unchanged.
  - `"ラフロアヒグ"` + name_en `"Laphroaig Quarter Cask"` → not collapsed to a misleading name
    (assert the chosen deterministic result and that no information is lost vs. the rule above).
  - `name_en "The Laphroaig 10-Year-Old"` fallback → `ラフロイグ 10年`.
  - A candidate with a whiskey-master exact match keeps `whiskey_id`, `match_source == "catalog"`,
    and its confidence is not capped even without brand_key.
- vitest:
  - In the stop test, assert the skipped item is `failed` with the quota message.
  - `getUploadUrl` rejecting with 429 `Daily upload limit exceeded` stops remaining items.
  - `retryProcessing` after a stop calls `getUploadUrl` and clears the stop for later items.
  - `candidateNeedsConfirmation` with `whiskey_id` and no `brand_key`.

## Preserve

- The four regression cases (ラフロイグ 10年, ブナハーブン 12年, 宮城峡, 遊佐) and their expected names.
- Unmatched cap 0.6 (when neither brand_key nor whiskey_id), matched confidence unchanged.
- Prompt changes, swagger `ai_name_ja`, quota message wording, getUploadUrl-count behavior.

## Verification

- repo root: `.venv/bin/python -m pytest tests`
- `frontend/`: `npm run lint`, `npm run typecheck`, `npx vitest run`, and `TZ=UTC npx vitest run`

## Completion report

What changed, files touched, each command and result, deviations.
