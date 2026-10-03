# Task

#60: expand the brand-layer catalog (`brands.json`) from the reviewed Rakuten observations, add the
brands and orthographic aliases found in the 2026-09 real-photo run, and add an AWS-free replay
mode to the brand eval so the acceptance criteria can be checked offline.

Branch: `feat/brand-catalog-expansion` (already checked out, from `main`). Do not commit.
Never run `git checkout`/`git restore`/`git stash`. Do not touch the user's uncommitted files
(`AGENTS.md`, `pyproject.toml`, `scripts/agent_call_whiskey.py`, untracked files).

## Repository context

- Catalog: `scripts/catalog/brands.json` (version 1, 60 brands; fields `brand_key, brand_ja,
  brand_en, aliases, distillery_ja, distillery_en, region, country`). A packaged copy
  `lambda/drink-log-analyze/brands.json` must stay byte-identical (existing test enforces).
- `scripts/catalog/bottlers.json` (`bottler_key, bottler_ja, bottler_en, aliases`).
- Candidates for promotion: `scripts/catalog/pending_brands.json` (86 entries with
  `observed_variants`, `occurrence_count`, `warnings`); tool `scripts/catalog/promote_proposals.py`
  (has `--apply`, `--exclude-warned`). Read it and reuse its normalization/dedup logic where it fits.
- Matching: `lambda/common/python/whiskey_common/candidate_resolution.py`. `BrandCatalog` matches
  brand_ja/brand_en/aliases exactly after `normalized_brand_variants`, plus distillery names that
  are owned by exactly one brand ("safe distilleries"). `CandidateResolver` rebuilds the display
  name only when the match came through the brand's own names (`matches_brand_name`).
  **Consequence: a brand's own aliases must be names of that brand, never a product line of a
  different label** — otherwise the display name is rewritten to the wrong brand.
- Eval: `scripts/eval/run_brand_eval.py` (modes `--target dev`, `--dry-run`,
  `--propose-brand-keys`), manifest `scripts/eval/manifest.real.json` (27 real photos), stored
  results `scripts/eval/results/2026-08-02-{nova-2-lite,sonnet-4-6,haiku-4-5}.json`. Each result
  record holds the analyze `response.candidates`, which still carry the model's own
  `name_ja/name_en/brand_ja/brand_en/confidence` (recorded before the #53 rename logic existed) and
  the master-match `whiskey_id`. Tests: `tests/eval/test_run_brand_eval.py`.

## Part A — promote reviewed brands from `pending_brands.json`

Promote every pending entry **except** these exclusions:
- Company / group names (would swallow every product): サントリー, キリン, ニッカウヰスキー, マツイ.
- Product names or generic fragments, not brands: サントリー ローヤル, キングウイスキー 凛,
  キリンウイスキー 陸.
- Entries that duplicate an existing brand (e.g. イチローズモルト, キルホーマン, ロッホローモンド,
  桜尾, シングルモルト静岡, ニッカ ウイスキー シングルモルト 余市, フォアローゼス — check all
  against existing names/aliases): do **not** add a new brand; add their genuine name variants as
  aliases of the existing brand only when they are clean brand names (e.g. `桜尾` for sakurao is
  fine; `シングルモルト静岡` is not — it contains a generic term).
- Fold sub-variants into one brand: ブラックニッカ クリア → alias of a new `black_nikka`;
  マルスウイスキー / マルス 駒ヶ岳 → one `mars` brand (brand_ja マルス). Do not alias 駒ヶ岳 alone.

For each promoted brand fill `brand_ja`, `brand_en`, `aliases` (observed clean variants, include
both scripts and common spellings, e.g. `アイル オブ ジュラ`/`ジュラ`/`Jura`), `distillery_ja`,
`distillery_en`, `region`, `country`, following the style of existing entries (look at several).
Use well-established public facts only. For blends / independent-bottler labels without one
distillery (e.g. Big Peat, Scallywag-type, Timorous Beastie, Scarabus, The Famous Grouse,
White Horse, Teacher's, Cutty Sark, Ancient Clan, Old Parr), follow how existing blends
(johnnie_walker, chivas_regal, monkey_shoulder) fill `distillery_*` — match their convention.
`brand_key`: lowercase snake_case English, consistent with existing keys.

Known interaction: adding `jim_beam` makes `ジムビーム` a brand name, so `knob_creek`'s distillery
`ジムビーム蒸溜所` stops being a safe distillery for knob_creek. That is correct. Update the
existing test `test_distillery_only_match_keeps_model_product_name` (tests/lambda/
test_drink_log_analyze.py) so its ジムビーム case reflects the new truth (jim_beam brand match,
name unchanged because it already equals the catalog name), keeping the サントリー 角瓶 case as
the distillery-only example; if possible add another genuine distillery-only example.

## Part B — real-photo additions

1. New brand `machrie_moor`: brand_ja マクリームーア, brand_en Machrie Moor, aliases incl.
   `マクリー ムーア`, `マクリームア`, `Machrie Moor`; distillery アラン蒸溜所 / Arran Distillery
   (spell exactly as the existing `arran` entry does). It is a separate brand like
   `port_charlotte`, NOT an alias of arran (an alias would rewrite the name to アラン).
2. New brand `saburomaru`: 三郎丸 / Saburomaru, distillery 三郎丸蒸留所 / Saburomaru Distillery,
   Japan.
3. `bottlers.json`: add `elixir_distillers` (エリクサー ディスティラーズ / Elixir Distillers),
   aliases incl. `エリクサー・ディスティラーズ`, `Elixir Distillers`. Do not add bare `Elixir`.
4. Orthographic / phonetic misreading aliases on existing brands (these are model readings from
   the real run; add only if not already present):
   - laphroaig: ラフロアヒグ
   - bunnahabhain: バナナブハイン
   - miyagikyo: 宮城京
   - yuza: ユイザ
   - fuji: 富士山ロク
   - akkeshi: アッケシ
   - sakurao: サクラオ
   - chita: チタ, ザ・チタ (check how normalization handles ザ・)
   - hibiki: ヒビキ
   - kilchoman: キルホマン
   **Do not** add semantic hallucinations (e.g. 八千代 for yoichi, マッカラン-type wrong brands).
   Do not add expression names (マキヤーベイ, マチルベイ) as brand aliases.

## Part C — replay mode for the brand eval

Add a mutually exclusive mode `--replay RESULT_JSON` to `run_brand_eval.py`:
- Load a stored result file, and for each record with a 200 response, rebuild the model reading
  of each candidate: `name_ja` = `ai_name_ja` if present else `name_ja`, plus `name_en`,
  `brand_ja`, `brand_en`, `confidence` (skip absent optional fields). Re-run
  `CandidateResolver` (current `scripts/catalog/brands.json`) on those readings, then carry over the
  stored `whiskey_id` / `match_source` for each candidate unchanged (the whiskey master is not
  available offline and is unaffected by this change).
- Score with the existing scoring / metrics functions and print a side-by-side of the brand-layer
  metrics: stored vs replayed (at least `brand_confirmed_correct`, `brand_confirmed_wrong`,
  `brand_not_confirmed`, and their rates), plus per-case lines where the brand verdict changed.
- `--json PATH` optionally writes the replay result; never overwrite the input file. No AWS calls,
  no boto3 session creation in this mode.
- Tests in `tests/eval/test_run_brand_eval.py` with a small synthetic result fixture (not the
  real files): a reading that becomes brand-matched after an alias is added, an unchanged one, and
  a check that no AWS client is constructed.

## Allowed scope

- `scripts/catalog/brands.json`, `lambda/drink-log-analyze/brands.json` (identical copy),
  `scripts/catalog/bottlers.json` (and its packaged copy if one exists)
- `scripts/eval/run_brand_eval.py`, `tests/eval/test_run_brand_eval.py`
- `tests/lambda/test_drink_log_analyze.py` (the ジムビーム case and new catalog tests)
- `scripts/catalog/pending_brands.json` only if `promote_proposals.py --apply` naturally rewrites
  it; otherwise leave it.

## Do not change

- `candidate_resolution.py` logic, analyze Lambda, frontend, infra, `expressions.json`,
  `proposed_*.json`, `scripts/eval/manifest*.json`, `scripts/eval/results/*` (read only).

## Acceptance criteria

- `BrandCatalog.from_file(...).exact_name_collisions()` is empty (add/keep a test asserting it).
- Brand count increases substantially (report before/after numbers and the full list added).
- Replay of all three stored results: `brand_confirmed_correct` does not decrease and
  `brand_confirmed_wrong` does not increase versus stored, for each model. Report the numbers.
- All existing tests pass.

## Verification

- `.venv/bin/python -m pytest tests`
- `.venv/bin/python scripts/eval/run_brand_eval.py --replay scripts/eval/results/2026-08-02-nova-2-lite.json`
  (and the sonnet / haiku files)
- `.venv/bin/python scripts/eval/run_brand_eval.py --dry-run scripts/eval/manifest.real.json`

## Constraints

- Minimal changes, existing conventions, no new dependencies.
- If a fact for a field is uncertain, still fill it with your best well-known value but list it
  under "uncertain fields" in the report.
- If the task needs a matcher logic change to satisfy the acceptance criteria, stop and report
  instead of changing `candidate_resolution.py`.

## Completion report

What changed, brands added (key + brand_ja), aliases added per brand, exclusions applied, uncertain
fields, replay numbers for all three models, every verification command and its result,
deviations.
