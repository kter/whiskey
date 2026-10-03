# Task

#55: add an explicit `UNKNOWN` serving style, stop defaulting to NEAT, give the model concrete
visual cues, and make serving-style accuracy measurable in the eval harness.

Branch: `fix/serving-style-unknown` (already checked out from `main`). Do not commit.
Never run `git checkout`/`git restore`/`git stash`. Do not touch the user's uncommitted files
(`AGENTS.md`, `pyproject.toml`, `scripts/agent_call_whiskey.py`, untracked files).

## Decision (approved by the user)

Add `UNKNOWN` to the serving-style enum (display label 「未設定」). `serving_style` stays a
**required** field on Drink Logs; existing records are not migrated or changed. No null/absent
representation.

## Repository context

- Enum definitions kept in sync by `tests/test_drink_log_contract.py` (regex-extracted):
  `lambda/common/python/whiskey_common/serving_styles.py` (`SERVING_STYLES` set),
  `frontend/types/whiskey.ts` (`SERVING_STYLES` tuple), `swagger.yml` (`ServingStyle` enum).
- Analyze: `lambda/drink-log-analyze/index.py` — `PROMPT` (only cue today: 「ハイボールは
  serving_style を SODA」), `SERVING_STYLE_ALIASES`, `_validate_model_output` (rejects unknown
  values), empty-analysis fallback `"serving_style": "NEAT"` in `analyze_upload`, the local/mock
  reader returns `"NEAT"` (fine to keep).
- Create / update: `lambda/drink-logs/drink_log_store.py` (`_completion_from_analysis` uses
  `result.get("serving_style", "NEAT")`; overrides), `lambda/drink-logs/index.py` (update
  validation against `SERVING_STYLES`).
- Frontend: `frontend/pages/logs/new.vue` (radio chips over `SERVING_STYLES`, `styleLabels`),
  `frontend/pages/logs/[id].vue` (edit form defaults `'NEAT'` when missing, own `styleLabels`?),
  `frontend/utils/drinkLogs.ts` `servingStyleLabel`, `frontend/composables/useDrinkLogs.ts`
  (payload builders; `servingStyle` omitted when empty),
  `frontend/composables/useDrinkLogRecordingSession.ts` (`applyAnalysis`, item `servingStyle`).
- Local adapter: `local_api/` may mirror validation — check it.
- Eval: `scripts/eval/run_brand_eval.py`, `scripts/eval/manifest.schema.json`,
  `scripts/eval/manifest.real.json` (27 cases), stored results contain `response.serving_style`.

## Requirements

### Backend
1. Add `UNKNOWN` to all three enum definitions (contract test must pass unchanged in spirit).
2. Analyze:
   - Empty-analysis fallback → `UNKNOWN`.
   - `_validate_model_output`: accept `UNKNOWN`; also map common model spellings to it
     (`UNKNOWN`, `UNSURE`, `NONE`, `N/A`, empty string) via `SERVING_STYLE_ALIASES`. A
     completely unrecognized value should become `UNKNOWN` rather than discarding the whole
     reading — the bottle identification is still valuable. Keep rejecting non-string types as
     today if that is the existing contract; make the minimal change and test it.
   - Prompt: replace the single SODA sentence with concrete cues, in Japanese, e.g.
     - 氷が入っていて泡がない → ROCKS
     - 縦長のグラスで炭酸の泡が見える（氷の有無を問わない） → SODA
     - 氷がなく、小さなテイスティンググラス・ショットグラス・脚付きグラスに少量 → NEAT
     - 明らかに水で割った淡い色で量が多い → WATER（迷ったら UNKNOWN）
     - フルーツやガーニッシュ、ウイスキー以外の色 → COCKTAIL
     - グラスが写っていない、グラスが空、または判断できない → UNKNOWN
     Update the JSON example's `serving_style` line to include `UNKNOWN`.
3. Create / update:
   - `_completion_from_analysis`: missing `serving_style` on a (legacy, ≤30-min TTL) analysis
     item → `UNKNOWN` instead of `NEAT`.
   - Overrides and PATCH accept `UNKNOWN` (they validate against `SERVING_STYLES`, so this should
     follow automatically — add tests).
4. `swagger.yml`: enum updated; add a short description that `UNKNOWN` means the user/AI did not
   determine the serving style.

### Frontend
1. `SERVING_STYLES` includes `UNKNOWN`; label 「未設定」 everywhere (`styleLabels`,
   `servingStyleLabel`). Avoid duplicated label maps if a shared one is easy; otherwise update each.
2. New-log page: render the 「未設定」 chip **first** (before NEAT). When analysis returns
   `UNKNOWN` (or nothing usable) the item starts with 「未設定」 selected — no real style is
   pre-selected. Saving with 「未設定」 sends `serving_style: 'UNKNOWN'` explicitly.
3. Edit page `[id].vue`: default to `UNKNOWN` (not `NEAT`) when the record lacks a value; the
   「未設定」 chip is selectable.
4. Timeline / detail display 「未設定」 for `UNKNOWN`.

### Eval
1. Manifest: optional per-case `expected_serving_style` (enum incl. `UNKNOWN`) in
   `manifest.schema.json` and the harness's allowed fields / validation.
2. Scoring: for cases that have `expected_serving_style`, report serving-style accuracy
   (correct / labeled), a per-expected-value breakdown, and how often the model said `UNKNOWN`.
   Reuse the existing metrics plumbing; include it in `--replay` output using the **stored**
   `response.serving_style` (replay does not re-run the model, so this measures the stored run).
3. Do **not** edit `manifest.real.json` labels — the orchestrator will label the 27 photos
   separately. Add tests with a synthetic manifest/result.

## Allowed scope

The files listed above, their tests under `tests/` and `frontend/tests/`, and `local_api/` if it
duplicates serving-style validation.

## Do not change

Catalog JSON, `candidate_resolution.py`, cost guard, infra/CDK, stored eval results/manifests,
existing DynamoDB records (no migration).

## Acceptance criteria

- `UNKNOWN` round-trips: analyze can return it, create stores it, PATCH can set it, UI shows 「未設定」.
- No code path silently defaults to `NEAT` anymore (grep and report remaining `"NEAT"` literals and
  why each is fine, e.g. mock fixtures).
- Contract test passes with the new value in all three places.
- Eval reports serving-style accuracy when labels exist.

## Verification

- `.venv/bin/python -m pytest tests`
- `frontend/`: `npm run lint`, `npm run typecheck`, `npx vitest run`, `TZ=UTC npx vitest run`
- `.venv/bin/python scripts/eval/run_brand_eval.py --replay scripts/eval/results/2026-08-02-nova-2-lite.json`
- `.venv/bin/python scripts/eval/run_brand_eval.py --dry-run scripts/eval/manifest.real.json`

## Constraints

- Minimal change, existing conventions, no new dependencies, add tests for behavior changes,
  report failures honestly, stop and report if a larger design change is needed.

## Completion report

Changes, files, remaining `"NEAT"` literals with justification, each command and result,
deviations.
