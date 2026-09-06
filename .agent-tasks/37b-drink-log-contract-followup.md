# TASK 37b: close the false-pass hole in the Drink Log contract test

Branch: `test/drink-log-contract` (already checked out, one commit ahead of `main`).

Review of `75e6cf0` found a defect in the test itself plus four cleanups. No production value may
change; the production diff must stay comments-only.

---

## 1. The value regex matches a prefix, so the test passes on drift

`_environment_default` / `_assignment` / `_object_property` capture `(?P<value>['\"]?[\d_]+['\"]?)`.
That matches a *prefix* of a larger expression, so:

```ts
const MAX_OUTPUT_SIZE = 3_670_016 * 2
```

extracts `3_670_016` and **passes**. Confirmed by hand: doubling the frontend limit this way leaves
all 10 tests green. That is a false pass on exactly the "value silently desynchronised" scenario
this test exists to catch.

Anchor the value group so it cannot be followed by more of an expression — a negative lookahead for
`[\d_*/+\-]` (and any other operator that could continue it) after the captured number, applied to
all three pattern builders.

Then prove it: temporarily change one site to `3_670_016 * 2` and confirm the test now fails, and
separately confirm a plain wrong number still fails. Restore by **editing the file back, never with
`git checkout` or `git restore`** — the tree has uncommitted work in it. Say in your summary that
you did both probes.

## 2. Drop the exact per-file occurrence counts

`count=2` for `lambda/drink-logs/index.py` means a third legitimate call site fails a *contract*
test with `expected 2 matching constant(s), found 3` — a message about arithmetic, not about drift.

Replace the exact count with "at least one match, and every extracted value equals the expected
one". A constant that is renamed, removed, or moved to another file still fails loudly with zero
matches, which is the guarantee that matters.

## 3. Stop restating the number in the test

`EXPECTED_UPLOAD_MAX_BYTES = 3_670_016` and `EXPECTED_IMAGE_MAX_BYTES = 1_572_864` make the test a
seventh and third statement of the same fact. The precedent this follows —
`test_packaged_brand_catalog_matches_curated_source` — states its fact zero extra times, by
comparing one file against another.

Do the same: designate `infra/lib/whiskey-infra-stack.ts` as the source of truth (it is what
actually configures the deployed Lambdas), read the value from there, and compare every other site
against it. If the CDK file's own two occurrences disagree with each other, that must fail too.

## 4. Collapse the two near-identical test functions

`test_upload_size_limits_match` and `test_normalized_image_size_limits_match` differ only by which
constant they expect. Parametrise over the constant as well, or otherwise express the shared shape
once.

## 5. Fix three misplaced comments and thin out the CDK ones

- `lambda/drink-log-analyze/index.py` — the comment is wedged *inside* a multi-line boolean `or`
  chain. Move it above the whole condition, or drop it there.
- `lambda/drink-logs/index.py` (the `_finish_pending_create` one) — it sits above
  `normalized = normalize_image(`, two lines from the constant it refers to. Put it on the line that
  carries the constant.
- `frontend/utils/drinkLogs.ts` — a `//` line was inserted between the existing `/** … */` block and
  `export const`, which likely severs the doc-comment association, and that block already names
  `places.py` in prose. Fold the pointer into the existing block comment instead of adding a second
  mechanism.
- `infra/lib/whiskey-infra-stack.ts` — the identical comment is repeated on adjacent lines, twice
  over. One comment per environment block is enough.

Keep every other comment where it is. Do not reformat surrounding code.

---

## Verification

```bash
python -m pytest tests
```

All tests must pass. The production diff against `main` must remain **comments only** — no value,
expression, or behaviour may change. Confirm with `git diff main -- lambda frontend infra scripts`
that there are no deletions other than comment lines you deliberately moved.

## Out of scope

- Any constant's value
- `frontend/components/DrinkLogStoreDisplay.vue` — its two placeholders are frontend-only
- Introducing a shared JSON contract file, a code generator, or a build step
- `swagger.yml`, `API_REFERENCE.md`, `pyproject.toml`
