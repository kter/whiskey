# Follow-up correction (task 40)

Branch `fix/serving-style-unknown` in `/home/ttakahashi/workspace/whiskey`, uncommitted work present.
Do not commit. Never run `git checkout`/`git restore`/`git stash`. Do not touch `AGENTS.md`,
`pyproject.toml` or untracked user files. `scripts/eval/manifest.real.json` now carries
`expected_serving_style` labels written by the orchestrator — do not change the labels.

## Problems found

1. `--replay` scores serving style against the `case` copy embedded in the stored result
   (`scripts/eval/run_brand_eval.py` ~L954), so current manifest labels are ignored → "0 labeled".
2. Missing tests: frontend `applyAnalysis` serving-style handling, 「未設定」 chip first + checked in
   `new.vue`, `[id].vue` defaulting to `UNKNOWN`; backend `analyze_upload` empty-analysis fallback
   → `UNKNOWN`; `_validate_model_output` with `" rocks "` → `ROCKS`; create with override
   `serving_style: "UNKNOWN"` end to end.
3. Minor: `RecordingSessionItem.servingStyle` typed `ServingStyle | ''` though `''` is no longer
   assigned; 「迷ったら UNKNOWN にしてください。」 sits between the WATER and COCKTAIL cues;
   unhashable `expected_serving_style` raises `TypeError` instead of `ManifestError`;
   non-200 responses silently counted as serving-style wrong.

## Required fixes

1. Replay: add optional `--manifest PATH` (usable with `--replay`; default
   `scripts/eval/manifest.real.json`). Overlay `expected_serving_style` from the manifest onto each
   stored record's case, matched by `image`; report stored cases without a manifest match. Brand
   replay unchanged. Test: stored result without labels + synthetic manifest with labels → correct
   labeled count and accuracy.
2. Add the missing tests listed above (vitest and pytest).
3. Narrow the type to `ServingStyle` (keep the `|| 'UNKNOWN'` safety net in the payload builder);
   move the 「迷ったら…」 sentence to the end of the serving-style cues as a single closing rule;
   raise `ManifestError` for unhashable values; in the serving-style report, show error
   (non-200) cases as a separate count instead of folding them into wrong.

## Preserve

`UNKNOWN` first in the enum order, shared `servingStyleLabels`, always sending `serving_style` on
create, strict validation of `whiskeys`/`glass_type`, the MOCK_AI `NEAT` fixture, all task-40
behavior.

## Verification

- `.venv/bin/python -m pytest tests`
- `frontend/`: `npm run lint`, `npm run typecheck`, `npx vitest run`, `TZ=UTC npx vitest run`
- `.venv/bin/python scripts/eval/run_brand_eval.py --replay scripts/eval/results/2026-08-02-nova-2-lite.json`
  must report 27 labeled cases
- `.venv/bin/python scripts/eval/run_brand_eval.py --dry-run scripts/eval/manifest.real.json`

## Completion report

Changes, files, each command and result, deviations.
