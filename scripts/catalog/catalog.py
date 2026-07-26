"""Load and validate the versioned curated whiskey catalog."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable


BRAND_KEY_PATTERN = re.compile(r"^[a-z0-9_]+$")
IDENTITY_FIELDS = (
    "brand_key",
    "expression_code",
    "age",
    "edition",
    "cask",
    "vintage",
    "bottler",
)
EXPRESSION_REQUIRED_FIELDS = {
    "brand_key",
    "expression_code",
    "age",
    "edition",
    "cask",
    "vintage",
    "bottler",
    "abv",
    "type",
    "canonical_name_ja",
    "canonical_name_en",
}
BRAND_REQUIRED_FIELDS = {
    "brand_key",
    "brand_ja",
    "brand_en",
    "aliases",
    "distillery_ja",
    "distillery_en",
    "region",
    "country",
}
BOTTLER_REQUIRED_FIELDS = {
    "bottler_key",
    "bottler_ja",
    "bottler_en",
    "aliases",
}


def _normalize_identity_value(value: Any) -> str:
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKC", str(value)).strip().lower()
    return " ".join(normalized.split())


def catalog_key(source: dict[str, Any]) -> str:
    """Return the stable liquid-identity hash for one expression."""
    identity = [_normalize_identity_value(source.get(field)) for field in IDENTITY_FIELDS]
    payload = json.dumps(identity, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _load_versioned_list(path: Path, collection_key: str) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as source_file:
        document = json.load(source_file)
    if not isinstance(document, dict) or document.get("version") != 1:
        raise ValueError(f"{path} must use catalog version 1")
    records = document.get(collection_key)
    if not isinstance(records, list) or not records:
        raise ValueError(f"{path} must contain a non-empty {collection_key} list")
    return records


def load_brands(path: Path) -> dict[str, dict[str, Any]]:
    """Load brand definitions keyed by validated brand_key."""
    brands: dict[str, dict[str, Any]] = {}
    for position, brand in enumerate(_load_versioned_list(path, "brands")):
        if not isinstance(brand, dict):
            raise ValueError(f"brand {position} must be an object")
        missing = BRAND_REQUIRED_FIELDS - brand.keys()
        if missing:
            raise ValueError(f"brand {position} is missing fields: {sorted(missing)}")
        brand_key = brand["brand_key"]
        if not isinstance(brand_key, str) or not BRAND_KEY_PATTERN.fullmatch(brand_key):
            raise ValueError(f"invalid brand_key at brand {position}: {brand_key!r}")
        if brand_key in brands:
            raise ValueError(f"duplicate brand_key: {brand_key}")
        aliases = brand["aliases"]
        if (
            not isinstance(aliases, list)
            or not aliases
            or any(not isinstance(alias, str) or not alias.strip() for alias in aliases)
        ):
            raise ValueError(f"brand {brand_key} must have non-empty string aliases")
        for field in BRAND_REQUIRED_FIELDS - {"brand_key", "aliases"}:
            if not isinstance(brand[field], str):
                raise ValueError(f"brand {brand_key} field {field} must be a string")
        brands[brand_key] = brand
    return brands


def load_bottlers(path: Path) -> dict[str, dict[str, Any]]:
    """Load bottler definitions keyed by validated bottler_key."""
    bottlers: dict[str, dict[str, Any]] = {}
    for position, bottler in enumerate(_load_versioned_list(path, "bottlers")):
        if not isinstance(bottler, dict):
            raise ValueError(f"bottler {position} must be an object")
        missing = BOTTLER_REQUIRED_FIELDS - bottler.keys()
        if missing:
            raise ValueError(
                f"bottler {position} is missing fields: {sorted(missing)}"
            )
        bottler_key = bottler["bottler_key"]
        if (
            not isinstance(bottler_key, str)
            or not BRAND_KEY_PATTERN.fullmatch(bottler_key)
        ):
            raise ValueError(
                f"invalid bottler_key at bottler {position}: {bottler_key!r}"
            )
        if bottler_key in bottlers:
            raise ValueError(f"duplicate bottler_key: {bottler_key}")
        aliases = bottler["aliases"]
        if (
            not isinstance(aliases, list)
            or not aliases
            or any(not isinstance(alias, str) or not alias.strip() for alias in aliases)
        ):
            raise ValueError(
                f"bottler {bottler_key} must have non-empty string aliases"
            )
        for field in ("bottler_ja", "bottler_en"):
            if not isinstance(bottler[field], str) or not bottler[field].strip():
                raise ValueError(
                    f"bottler {bottler_key} field {field} must be a non-empty string"
                )
        bottlers[bottler_key] = bottler
    return bottlers


def load_expressions(path: Path, brands: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Load expressions and reject missing brands or duplicate identities."""
    expressions: list[dict[str, Any]] = []
    seen_catalog_keys: set[str] = set()
    seen_legacy_ids: set[str] = set()
    for position, expression in enumerate(_load_versioned_list(path, "expressions")):
        if not isinstance(expression, dict):
            raise ValueError(f"expression {position} must be an object")
        missing = EXPRESSION_REQUIRED_FIELDS - expression.keys()
        if missing:
            raise ValueError(f"expression {position} is missing fields: {sorted(missing)}")
        brand_key = expression["brand_key"]
        if brand_key not in brands:
            raise ValueError(f"unknown brand_key at expression {position}: {brand_key!r}")
        if not isinstance(expression["expression_code"], str) or not expression[
            "expression_code"
        ].strip():
            raise ValueError(f"expression {position} must have a non-empty expression_code")
        age = expression["age"]
        if age is not None and (isinstance(age, bool) or not isinstance(age, int) or age <= 0):
            raise ValueError(f"expression {position} age must be a positive integer or null")
        for field in ("canonical_name_ja", "canonical_name_en", "type"):
            if not isinstance(expression[field], str) or not expression[field].strip():
                raise ValueError(f"expression {position} must have a non-empty {field}")
        legacy_id = expression.get("legacy_id")
        if legacy_id is not None:
            if not isinstance(legacy_id, str) or not legacy_id.strip():
                raise ValueError(f"expression {position} has an invalid legacy_id")
            if legacy_id in seen_legacy_ids:
                raise ValueError(f"duplicate legacy_id: {legacy_id}")
            seen_legacy_ids.add(legacy_id)
        key = catalog_key(expression)
        if key in seen_catalog_keys:
            raise ValueError(f"duplicate catalog_key: {key}")
        seen_catalog_keys.add(key)
        expressions.append(expression)
    return expressions


def load_catalog(
    brands_path: Path,
    expressions_path: Path,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Load and cross-validate both catalog source files."""
    brands = load_brands(brands_path)
    return brands, load_expressions(expressions_path, brands)


def to_dynamodb_item(
    expression: dict[str, Any],
    brand: dict[str, Any],
    now: str,
    normalize_text: Callable[[str], str],
) -> dict[str, Any]:
    """Expand one expression and its brand into a search-compatible DynamoDB item."""
    key = catalog_key(expression)
    name_ja = expression["canonical_name_ja"].strip()
    name_en = expression["canonical_name_en"].strip()
    item: dict[str, Any] = {
        "id": expression.get("legacy_id") or key,
        "catalog_key": key,
        "catalog_schema_version": 2,
        "brand_key": brand["brand_key"],
        "brand_ja": brand["brand_ja"],
        "brand_en": brand["brand_en"],
        "brand_aliases": list(brand["aliases"]),
        "expression_code": expression["expression_code"],
        "canonical_name_ja": name_ja,
        "canonical_name_en": name_en,
        "distillery_ja": brand["distillery_ja"],
        "distillery_en": brand["distillery_en"],
        "distillery": brand["distillery_ja"],
        "region": brand["region"],
        "country": brand["country"],
        "type": expression["type"],
        "name": name_ja,
        "name_ja": name_ja,
        "name_en": name_en,
        "normalized_name": normalize_text(f"{name_ja}|{name_en}"),
        "source": "curated_seed",
        "confidence": Decimal("1"),
        "created_at": now,
        "updated_at": now,
    }
    if expression.get("legacy_id"):
        item["legacy_id"] = expression["legacy_id"]
    for field in ("age", "edition", "cask", "vintage", "bottler", "abv"):
        if expression.get(field) is not None:
            item[field] = expression[field]
    return item
