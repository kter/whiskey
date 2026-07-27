import json
from copy import deepcopy
from pathlib import Path

from scripts.catalog import promote_proposals as promotion


MODULE_PATH = (
    Path(__file__).parents[1] / "scripts" / "catalog" / "promote_proposals.py"
)


def brand(brand_key="known", brand_ja="既知", brand_en="Known", aliases=None):
    return {
        "brand_key": brand_key,
        "brand_ja": brand_ja,
        "brand_en": brand_en,
        "aliases": aliases or [brand_ja, brand_en],
        "distillery_ja": "",
        "distillery_en": "",
        "region": "",
        "country": "",
    }


def expression(brand_ja=None, brand_en=None, source_title=None):
    return {
        "brand_ja": brand_ja,
        "brand_en": brand_en,
        "source_title": source_title or brand_ja or brand_en or "",
    }


def write_json(path, document):
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")


def run_cli(
    tmp_path,
    expressions,
    brands=None,
    terms=None,
    *extra_args,
):
    extracted_path = tmp_path / "extracted.json"
    brands_path = tmp_path / "brands.json"
    terms_path = tmp_path / "generic_terms.json"
    output_path = tmp_path / "pending.json"
    write_json(extracted_path, {"version": 1, "expressions": expressions})
    write_json(brands_path, {"version": 1, "brands": brands or [brand()]})
    write_json(terms_path, {"version": 1, "terms": terms or []})
    result = promotion.main(
        [
            "--extracted",
            str(extracted_path),
            "--brands",
            str(brands_path),
            "--generic-terms",
            str(terms_path),
            "--output",
            str(output_path),
            *extra_args,
        ]
    )
    pending = (
        json.loads(output_path.read_text(encoding="utf-8"))
        if output_path.exists()
        else None
    )
    return result, pending, brands_path, terms_path


def test_cjk_whitespace_variants_are_grouped_together():
    candidates, _ = promotion.build_pending_brands(
        [
            expression("フェイマス グラウス"),
            expression("フェイマスグラウス"),
        ],
        [],
        [],
    )

    assert len(candidates) == 1
    assert candidates[0]["occurrence_count"] == 2
    assert set(candidates[0]["aliases"]) == {
        "フェイマス グラウス",
        "フェイマスグラウス",
    }


def test_japanese_article_and_whitespace_variants_are_grouped_together():
    candidates, _ = promotion.build_pending_brands(
        [
            expression("ザ フェイマスグラウス"),
            expression("フェイマス グラウス"),
        ],
        [],
        [],
    )

    assert len(candidates) == 1
    assert candidates[0]["occurrence_count"] == 2


def test_english_labels_are_not_overmerged():
    candidates, _ = promotion.build_pending_brands(
        [
            expression(brand_en="Arran"),
            expression(brand_en="Aran"),
            expression(brand_en="Glen Grant"),
            expression(brand_en="Glengrant"),
        ],
        [],
        [],
        min_occurrences=1,
    )

    assert len(candidates) == 4


def test_min_occurrences_excludes_single_observation():
    candidates, summary = promotion.build_pending_brands(
        [
            expression("二件候補"),
            expression("二件候補"),
            expression("一件候補"),
        ],
        [],
        [],
        min_occurrences=2,
    )

    assert [candidate["brand_ja"] for candidate in candidates] == ["二件候補"]
    assert summary["below_threshold_groups_excluded"] == 1


def test_default_cli_does_not_modify_brands(tmp_path):
    existing = {"version": 1, "brands": [brand()]}
    result, pending, brands_path, _ = run_cli(
        tmp_path,
        [expression("新候補"), expression("新候補")],
        existing["brands"],
    )

    assert result == 0
    assert pending["pending_brands"]
    assert json.loads(brands_path.read_text(encoding="utf-8")) == existing


def test_apply_appends_without_changing_existing_entries(tmp_path):
    existing_brand = brand()
    result, _, brands_path, _ = run_cli(
        tmp_path,
        [
            expression("新候補", "New Candidate"),
            expression("新候補", "New Candidate"),
        ],
        [existing_brand],
        [],
        "--apply",
    )

    updated = json.loads(brands_path.read_text(encoding="utf-8"))
    assert result == 0
    assert updated["brands"][0] == existing_brand
    assert len(updated["brands"]) == 2
    assert updated["brands"][1]["brand_key"] == "new_candidate"


def test_brand_key_collision_aborts_without_modifying_brands(tmp_path):
    existing = brand("alpha", "別候補", "Different", ["別候補", "Different"])
    result, _, brands_path, _ = run_cli(
        tmp_path,
        [
            expression(brand_en="Alpha!"),
            expression(brand_en="Alpha!"),
        ],
        [existing],
        [],
        "--apply",
    )

    assert result == 1
    assert json.loads(brands_path.read_text(encoding="utf-8")) == {
        "version": 1,
        "brands": [existing],
    }


def test_aliases_only_contain_observed_labels(tmp_path):
    observed = {"観測甲", "観測 甲", "Observed A"}
    _, pending, _, _ = run_cli(
        tmp_path,
        [
            expression("観測甲", "Observed A"),
            expression("観測 甲", "Observed A"),
        ],
    )

    candidate = pending["pending_brands"][0]
    assert set(candidate["aliases"]) == observed
    assert set(candidate["observed_variants"]) == observed


def test_generic_term_warning_is_controlled_only_by_configuration(tmp_path):
    expressions = [
        expression(brand_en="Example markerword"),
        expression(brand_en="Example markerword"),
    ]
    _, pending, _, terms_path = run_cli(
        tmp_path,
        expressions,
        terms=["markerword"],
    )
    assert "contains_generic_term" in pending["pending_brands"][0]["warnings"]

    write_json(terms_path, {"version": 1, "terms": []})
    terms = promotion.load_generic_terms(terms_path)
    candidates, _ = promotion.build_pending_brands(expressions, [], terms)
    assert "contains_generic_term" not in candidates[0]["warnings"]


def test_prefix_candidate_is_flagged_but_not_filtered():
    candidates, _ = promotion.build_pending_brands(
        [
            expression(brand_en="Parent"),
            expression(brand_en="Parent"),
            expression(brand_en="Parent Reserve"),
            expression(brand_en="Parent Reserve"),
        ],
        [],
        [],
    )
    candidates_by_name = {
        candidate["brand_en"]: candidate for candidate in candidates
    }

    assert "prefix_of_other_candidate" in candidates_by_name["Parent"]["warnings"]
    assert "prefix_of_other_candidate" not in candidates_by_name[
        "Parent Reserve"
    ]["warnings"]
    assert len(candidates) == 2


def test_company_and_brand_examples_are_not_hardcoded_in_tool():
    source = MODULE_PATH.read_text(encoding="utf-8")
    forbidden_literals = (
        "サントリー",
        "ニッカウヰスキー",
        "キリン",
        "マルス",
        "余市",
        "静岡",
    )

    assert all(literal not in source for literal in forbidden_literals)
