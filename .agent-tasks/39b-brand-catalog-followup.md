# Follow-up correction (task 39)

Branch `feat/brand-catalog-expansion`, uncommitted work present. Do not commit. Never run
`git checkout`/`git restore`/`git stash`. Do not touch `AGENTS.md`, `pyproject.toml`,
`scripts/agent_call_whiskey.py` or untracked user files. Do not change `candidate_resolution.py`,
`scripts/eval/results/*`, or manifests.

Note: after task 39 the orchestrator re-serialized `brands.json` with **2-space** indent (keep it:
`json.dumps(d, ensure_ascii=False, indent=2) + "\n"`) and removed product-name aliases
(Jim Beam White, ブラックニッカ クリア variants, マルス 駒ヶ岳 variants, 富士山ロク). Do not re-add them.
Every change to `scripts/catalog/brands.json` must be mirrored byte-identically into
`lambda/drink-log-analyze/brands.json`.

## Problems found

1. `torys` has `distillery_ja/en` = サントリーウイスキー / Suntory Whisky, owned by no other brand, so
   it is a safe distillery: `name_ja "サントリーウイスキー 角瓶"`, `brand_ja "サントリーウイスキー"`,
   `brand_en "Suntory Whisky"` → `brand_key torys` (wrong brand on very common bottles).
2. Moving Machrie Moor off `arran` dropped `マクリムーア`, `マクリー・ムーア`, `Macrie Moor` (they
   matched on main; now no match).
3. `black_bottle`: `distillery_ja` バーネット＆サンズ contradicts `distillery_en` Burn Stewart
   Distillers, and the unique "Burn Stewart Distillers" becomes a safe distillery for black_bottle.
4. `teachers`: distillery ビームサントリー / Beam Suntory (group name) unique to teachers.
5. `famous_grouse` lacks its observed variant `ザ フェイマスグラウス`.
6. Tests: the replay test's "becomes matched" case already matches on main (has
   `brand_en="Laphroaig"`); replay behaviors untested; the distillery-only test now contains a
   brand-name match (jim_beam) and has no genuine new distillery-only example.
7. Replay `--json` writes confidence as a string (Decimal), and `Decimal` is imported inside a try.

## Required fixes

1. Catalog:
   a. `torys`: `distillery_ja/en` → `サントリー` / `Suntory` (same as hibiki), so サントリー has two
      owners and is no longer a safe distillery for either. Update the
      `("サントリー 角瓶", "サントリー", "hibiki", ...)` expectation to the new truth (no brand match,
      name unchanged). Add a test: `brand_ja "サントリーウイスキー"`, `brand_en "Suntory Whisky"` does not
      resolve to `torys` (nor any brand).
   b. `machrie_moor.aliases` += `マクリムーア`, `マクリー・ムーア`, `Macrie Moor`.
   c. `black_bottle`: distillery → `ゴードン・グラハム` / `Gordon Graham & Co.`
   d. `teachers`: distillery → `ウィリアム・ティーチャー＆サンズ` / `William Teacher & Sons`.
   e. `famous_grouse.aliases` += `ザ フェイマスグラウス`.
   f. Make Heaven Hill spelling consistent with existing `elijah_craig` (`ヘヴンヒル蒸溜所`) in
      `evan_williams` and `iw_harper`.
2. `tests/lambda/test_drink_log_analyze.py`:
   - Keep the distillery-only test to genuine distillery-only cases; add e.g.
     `brand_ja "プルトニー蒸溜所"` → `old_pulteney` with name unchanged and no `ai_name_ja`
     (verify it is actually a safe distillery; pick another if not).
   - Separate brand-match test for jim_beam with `name_ja "ジムビーム ホワイト"`.
   - Test that `brand_ja "ジムビーム蒸溜所"` resolves to neither `knob_creek` nor `old_crow`.
   - Tests for new real-photo aliases: `ザ・チタ` reading → name rebuilt to the chita catalog
     `brand_ja`; `マクリームーア` → `machrie_moor` (not `arran`), name stays マクリームーア;
     `三郎丸` → `saburomaru`.
3. `tests/eval/test_run_brand_eval.py`:
   - The "becomes matched" reading must match only via a newly added alias (drop `brand_en`).
   - Tests: `ai_name_ja` fallback used as the reading; `--json` equal to the input → return code 1
     and input unchanged; `--json` writes a file with `mode == "replay"`; non-200 records passed
     through unchanged.
   - Assert on `main()` output (capsys / written JSON), not on a separate rerun.
4. `run_brand_eval.py`: move `Decimal` import to module level; write candidates' `confidence`
   back in the stored numeric form in replay output. Make replay's status handling consistent with
   `_aggregate_records` (missing status treated the same way).

## Preserve

Everything else from task 39: brands added, replay numbers (nova 20/0, sonnet 24/0, haiku 22/1
correct/wrong), empty `exact_name_collisions()`, removed product aliases.

## Verification

- `.venv/bin/python -m pytest tests`
- `--replay` on all three `scripts/eval/results/2026-08-02-*.json` (correct must not drop, wrong
  must not rise vs stored: nova 20/0, sonnet 24/0, haiku 21/1)
- `cmp scripts/catalog/brands.json lambda/drink-log-analyze/brands.json`
- `git diff --check`

## Completion report

Changes, files, each command and result, deviations.
