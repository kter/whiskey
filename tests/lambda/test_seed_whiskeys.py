import copy
import json
from pathlib import Path

import pytest

from tests.lambda_module_loader import ROOT, load_lambda_module


seed_script = load_lambda_module(
    "seed_whiskeys_script_tests",
    "scripts/local/seed_whiskeys.py",
)
catalog = load_lambda_module(
    "whiskey_catalog_tests",
    "scripts/catalog/catalog.py",
)

BRANDS_PATH = ROOT / "scripts" / "catalog" / "brands.json"
EXPRESSIONS_PATH = ROOT / "scripts" / "catalog" / "expressions.json"
LEGACY_FIXTURE_PATH = ROOT / "scripts" / "local" / "seed_data" / "whiskeys.json"
NOW = "2026-01-01T00:00:00Z"


def _document(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _seed_items():
    return seed_script.build_seed_items(BRANDS_PATH, EXPRESSIONS_PATH, NOW)


def test_arran_10_is_in_curated_seed():
    arran = next(item for item in _seed_items() if item["brand_key"] == "arran")

    assert arran["canonical_name_ja"] == "アラン 10年"
    assert arran["age"] == 10
    assert arran["id"] == arran["catalog_key"]


def test_catalog_key_is_deterministic():
    expression = {
        "brand_key": "macallan",
        "expression_code": "double_cask",
        "age": 12,
        "edition": None,
        "cask": "Double Cask",
        "vintage": None,
        "bottler": None,
    }

    assert catalog.catalog_key(expression) == catalog.catalog_key(copy.deepcopy(expression))


def test_catalog_key_distinguishes_same_age_expressions():
    base = {
        "brand_key": "macallan",
        "age": 12,
        "edition": None,
        "cask": None,
        "vintage": None,
        "bottler": None,
    }

    assert catalog.catalog_key({**base, "expression_code": "double_cask"}) != catalog.catalog_key(
        {**base, "expression_code": "sherry_oak"}
    )


def test_existing_seed_ids_are_preserved():
    items_by_id = {item["id"]: item for item in _seed_items()}

    assert items_by_id["yamazaki-12"]["legacy_id"] == "yamazaki-12"


def test_every_seed_item_keeps_search_compatibility_fields():
    required = {"name", "normalized_name", "name_ja", "name_en"}

    assert all(required <= item.keys() for item in _seed_items())
    assert all(item["normalized_name"] for item in _seed_items())


def test_null_age_is_omitted_from_dynamodb_item():
    harmony = next(item for item in _seed_items() if item["id"] == "hibiki-japanese-harmony")

    assert "age" not in harmony


def test_unknown_brand_key_is_rejected(tmp_path):
    document = _document(EXPRESSIONS_PATH)
    document["expressions"] = [copy.deepcopy(document["expressions"][0])]
    document["expressions"][0]["brand_key"] = "missing_brand"
    expressions_path = tmp_path / "expressions.json"
    expressions_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown brand_key"):
        seed_script.build_seed_items(BRANDS_PATH, expressions_path, NOW)


def test_duplicate_catalog_key_is_rejected(tmp_path):
    expression = copy.deepcopy(_document(EXPRESSIONS_PATH)["expressions"][0])
    duplicate = copy.deepcopy(expression)
    duplicate["legacy_id"] = "different-legacy-id"
    duplicate["canonical_name_ja"] = "表示名だけ異なる"
    document = {"version": 1, "expressions": [expression, duplicate]}
    expressions_path = tmp_path / "expressions.json"
    expressions_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate catalog_key"):
        seed_script.build_seed_items(BRANDS_PATH, expressions_path, NOW)


def test_all_legacy_seed_expressions_were_migrated():
    legacy_ids = {item["id"] for item in _document(LEGACY_FIXTURE_PATH)}
    migrated_ids = {
        expression["legacy_id"]
        for expression in _document(EXPRESSIONS_PATH)["expressions"]
        if expression.get("legacy_id")
    }

    assert len(legacy_ids) == 50
    assert migrated_ids == legacy_ids
    assert len(_document(EXPRESSIONS_PATH)["expressions"]) == 51
