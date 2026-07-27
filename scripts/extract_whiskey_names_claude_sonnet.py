#!/usr/bin/env python3
"""Extract reviewable whiskey catalog candidates from Rakuten product titles."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from catalog.catalog import catalog_key, load_bottlers, load_brands  # noqa: E402


DEFAULT_MODEL_ID = "jp.anthropic.claude-sonnet-4-6"
DEFAULT_REGION = "ap-northeast-1"
DEFAULT_BATCH_SIZE = 20
DEFAULT_MAX_RETRIES = 2
DEFAULT_MAX_TOKENS = 8_000
DEFAULT_BRANDS_PATH = SCRIPT_DIR / "catalog" / "brands.json"
DEFAULT_BOTTLERS_PATH = SCRIPT_DIR / "catalog" / "bottlers.json"
DEFAULT_OUTPUT_PATH = SCRIPT_DIR / "catalog" / "extracted_expressions.json"
DEFAULT_PROPOSALS_PATH = SCRIPT_DIR / "catalog" / "proposed_brands.json"
DEFAULT_BOTTLER_PROPOSALS_PATH = SCRIPT_DIR / "catalog" / "proposed_bottlers.json"
DEFAULT_CHECKPOINT_PATH = (
    SCRIPT_DIR / "catalog" / "extracted_expressions.checkpoint.json"
)
DEFAULT_FAILED_BATCHES_DIR = SCRIPT_DIR / "catalog" / "failed_batches"
MODEL_RESULT_FIELDS = {
    "is_whiskey",
    "is_multi_bottle_set",
    "brand_ja",
    "brand_en",
    "distillery_ja",
    "bottler_ja",
    "bottler_en",
    "expression",
    "edition",
    "age",
    "vintage",
    "cask",
    "abv",
    "volume_ml",
    "confidence",
}
TEXT_FIELDS = (
    "brand_ja",
    "brand_en",
    "distillery_ja",
    "bottler_ja",
    "bottler_en",
    "expression",
    "edition",
    "cask",
)


def utc_now() -> str:
    """Return a timezone-aware extraction timestamp."""
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, document: dict[str, Any]) -> None:
    """Atomically write a UTF-8 JSON document."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def normalize_label(value: str) -> str:
    """Normalize a human-readable label for exact catalog matching."""
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return " ".join(normalized.split())


def _without_leading_article(value: str) -> str | None:
    """Remove one English or Japanese leading article when enough text remains."""
    if value.startswith("the "):
        candidate = value[4:].strip()
    elif value.startswith("ザ・"):
        candidate = value[2:].strip()
    elif value.startswith("ザ "):
        candidate = value[2:].strip()
    elif value.startswith("ザ"):
        candidate = value[1:].strip()
    else:
        return None
    remaining_characters = re.sub(r"\s+", "", candidate)
    return candidate if len(remaining_characters) >= 3 else None


def comparison_keys(value: str) -> set[str]:
    """Return conservative comparison forms without creating catalog aliases."""
    normalized = normalize_label(value)
    keys = {normalized}
    without_article = _without_leading_article(normalized)
    if without_article is not None:
        keys.add(without_article)
    return keys


def proposed_brand_key(
    brand_ja: str | list[str] | None,
    brand_en: str | list[str] | None = None,
) -> str:
    """Build an order-independent review key from observed brand labels."""
    if isinstance(brand_ja, str):
        observed_variants = [brand_ja]
    else:
        observed_variants = list(brand_ja or [])
    if isinstance(brand_en, str):
        english_variants = [brand_en]
    else:
        english_variants = list(brand_en or [])
    for value in english_variants:
        if value not in observed_variants:
            observed_variants.append(value)

    slugs: set[str] = set()
    for value in english_variants:
        normalized_value = normalize_label(value)
        canonical_value = (
            _without_leading_article(normalized_value) or normalized_value
        )
        ascii_candidate = (
            unicodedata.normalize("NFKD", canonical_value)
            .encode("ascii", "ignore")
            .decode("ascii")
            .casefold()
        )
        slug = re.sub(r"[^a-z0-9]+", "_", ascii_candidate).strip("_")
        if slug:
            slugs.add(slug)
    if slugs:
        return min(slugs)

    canonical_labels = {
        comparison_key
        for value in observed_variants
        for comparison_key in comparison_keys(value)
    }
    if not canonical_labels:
        canonical_labels.add("unknown")
    observed = min(canonical_labels, key=lambda value: (len(value), value))
    digest = hashlib.sha256(observed.encode("utf-8")).hexdigest()[:10]
    return f"proposed_{digest}"


def proposed_bottler_key(observed_variants: list[str]) -> str:
    """Build a deterministic review key for an unknown observed bottler."""
    english_variant = next(
        (
            value
            for value in observed_variants
            if unicodedata.normalize("NFKD", value)
            .encode("ascii", "ignore")
            .decode("ascii")
            .strip()
        ),
        "",
    )
    ascii_candidate = (
        unicodedata.normalize("NFKD", english_variant)
        .encode("ascii", "ignore")
        .decode("ascii")
        .casefold()
    )
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_candidate).strip("_")
    if slug:
        return slug

    observed = normalize_label(observed_variants[0] if observed_variants else "unknown")
    digest = hashlib.sha256(observed.encode("utf-8")).hexdigest()[:10]
    return f"proposed_bottler_{digest}"


def expression_code(value: str | None) -> str:
    """Return the identity value used by the version-1 catalog key."""
    return normalize_label(value) if value else "core"


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float) and value.is_integer():
        return int(value) if value >= 0 else None
    if isinstance(value, str) and re.fullmatch(r"\d+", value.strip()):
        return int(value)
    return None


def _optional_year(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int) and 1800 <= value <= 2100:
        return value
    if isinstance(value, str) and re.fullmatch(r"\d{4}", value.strip()):
        year = int(value)
        return year if 1800 <= year <= 2100 else None
    return None


def _optional_abv(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    match = re.fullmatch(r"(\d{1,3}(?:\.\d+)?)\s*(?:%|％|度)?", text)
    if not match:
        return None
    numeric_value = float(match.group(1))
    return match.group(1) if 0 < numeric_value <= 100 else None


def _confidence(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return round(max(0.0, min(1.0, float(value))), 4)


def _observed_in_title(value: str | None, source_title: str) -> str | None:
    """Reject translated or otherwise invented textual values."""
    if not value:
        return None
    compact_value = normalize_label(value).replace(" ", "")
    compact_title = normalize_label(source_title).replace(" ", "")
    return value if compact_value in compact_title else None


def _observed_age(value: int | None, source_title: str) -> int | None:
    if value is None or not 0 < value <= 100:
        return None
    normalized_title = unicodedata.normalize("NFKC", source_title)
    pattern = rf"(?<!\d){value}\s*(?:年|years?\s*old|y\.?o\.?)(?!\w)"
    return value if re.search(pattern, normalized_title, re.IGNORECASE) else None


def _observed_vintage(value: int | None, source_title: str) -> int | None:
    if value is None:
        return None
    normalized_title = unicodedata.normalize("NFKC", source_title)
    without_date_codes = re.sub(r"(?<!\d)(?:19|20)\d{6}(?!\d)", "", normalized_title)
    return value if re.search(rf"(?<!\d){value}(?!\d)", without_date_codes) else None


def _observed_abv(value: str | None, source_title: str) -> str | None:
    if value is None:
        return None
    normalized_title = unicodedata.normalize("NFKC", source_title)
    return (
        value
        if re.search(rf"(?<!\d){re.escape(value)}\s*(?:%|度)", normalized_title)
        else None
    )


def _observed_volume(value: int | None, source_title: str) -> int | None:
    if value is None or not 0 < value <= 10_000:
        return None
    normalized_title = unicodedata.normalize("NFKC", source_title)
    return (
        value
        if re.search(
            rf"(?<!\d){value}\s*(?:ml|ミリリットル)", normalized_title, re.IGNORECASE
        )
        else None
    )


def _compact_search_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _remove_aliases(value: str | None, aliases: list[str]) -> str | None:
    """Remove curated aliases while preserving the model's remaining label."""
    if not value:
        return None
    cleaned = unicodedata.normalize("NFKC", value)
    for alias in sorted(
        aliases,
        key=lambda item: len(_compact_search_text(item)),
        reverse=True,
    ):
        normalized_alias = unicodedata.normalize("NFKC", alias)
        whitespace_flexible = r"\s*".join(
            re.escape(part) for part in normalized_alias.split()
        )
        cleaned = re.sub(whitespace_flexible, " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\(\s*\)|（\s*）|\[\s*\]|【\s*】", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip(" \t\r\n・･,，、/／_-")
    return cleaned or None


class BottlerMatcher:
    """Find known bottlers anywhere in a title using curated aliases only."""

    def __init__(self, bottlers: dict[str, dict[str, Any]]):
        self.bottlers = bottlers

    def match_title(self, source_title: str) -> dict[str, Any] | None:
        """Return one unambiguous strongest bottler match, otherwise None."""
        compact_title = _compact_search_text(source_title)
        matches: list[tuple[int, str]] = []
        for bottler_key, bottler in self.bottlers.items():
            matched_lengths = [
                len(compact_alias)
                for alias in bottler["aliases"]
                if (compact_alias := _compact_search_text(alias))
                and compact_alias in compact_title
            ]
            if matched_lengths:
                matches.append((max(matched_lengths), bottler_key))
        if not matches:
            return None
        strongest_length = max(length for length, _ in matches)
        strongest_keys = {
            bottler_key
            for length, bottler_key in matches
            if length == strongest_length
        }
        if len(strongest_keys) != 1:
            return None
        return self.bottlers[next(iter(strongest_keys))]

    def separate(self, record: dict[str, Any], source_title: str) -> None:
        """Set canonical bottler fields and remove its aliases from brand fields."""
        bottler = self.match_title(source_title)
        if bottler is None:
            variants = [
                value
                for value in (record.get("bottler_ja"), record.get("bottler_en"))
                if value
            ]
            if variants:
                record["_unknown_bottler_variants"] = list(dict.fromkeys(variants))
                record["brand_ja"] = None
                record["brand_en"] = None
            return

        record["bottler_key"] = bottler["bottler_key"]
        record["bottler_ja"] = bottler["bottler_ja"]
        record["bottler_en"] = bottler["bottler_en"]
        for field in ("brand_ja", "brand_en"):
            record[field] = _remove_aliases(record.get(field), bottler["aliases"])


def sanitize_model_result(
    raw: Any,
    source_title: str,
    bottlers: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate one untrusted model result and discard unsupported fields."""
    if bottlers is None:
        bottlers = load_bottlers(DEFAULT_BOTTLERS_PATH)
    if not isinstance(raw, dict):
        raise ValueError("each model result must be an object")
    if not isinstance(raw.get("is_whiskey"), bool):
        raise ValueError("is_whiskey must be a boolean")
    if not isinstance(raw.get("is_multi_bottle_set"), bool):
        raise ValueError("is_multi_bottle_set must be a boolean")

    selected = {field: raw.get(field) for field in MODEL_RESULT_FIELDS}
    record: dict[str, Any] = {
        "source_title": source_title,
        "is_whiskey": selected["is_whiskey"],
        "is_multi_bottle_set": selected["is_multi_bottle_set"],
    }
    for field in TEXT_FIELDS:
        record[field] = _optional_string(selected[field])

    for field in TEXT_FIELDS:
        if field not in {"brand_ja", "brand_en"}:
            record[field] = _observed_in_title(record[field], source_title)
    if bottlers is not None:
        BottlerMatcher(bottlers).separate(record, source_title)
    for field in ("brand_ja", "brand_en"):
        record[field] = _observed_in_title(record[field], source_title)

    age = _optional_int(selected["age"])
    record["age"] = _observed_age(age, source_title)
    record["vintage"] = _observed_vintage(
        _optional_year(selected["vintage"]), source_title
    )
    record["abv"] = _observed_abv(_optional_abv(selected["abv"]), source_title)
    volume_ml = _optional_int(selected["volume_ml"])
    record["volume_ml"] = _observed_volume(volume_ml, source_title)
    record["confidence"] = _confidence(selected["confidence"])
    return record


class BrandMatcher:
    """Match extracted brand labels against the human-curated brand catalog."""

    def __init__(self, brands: dict[str, dict[str, Any]]):
        self.brands = brands
        self.lookup: dict[str, set[str]] = defaultdict(set)
        for brand_key, brand in brands.items():
            values = [brand["brand_ja"], brand["brand_en"], *brand["aliases"]]
            for value in values:
                for comparison_key in comparison_keys(value):
                    self.lookup[comparison_key].add(brand_key)

    def match(self, brand_ja: str | None, brand_en: str | None) -> str | None:
        """Return one unambiguous known brand key, otherwise None."""
        matches: set[str] = set()
        for value in (brand_ja, brand_en):
            if value:
                for key in comparison_keys(value):
                    matches.update(self.lookup.get(key, set()))
        return next(iter(matches)) if len(matches) == 1 else None

    def find_in_title(self, source_title: str) -> tuple[str, int] | None:
        """Find one known brand in a title and return its earliest position."""
        normalized_title = unicodedata.normalize("NFKC", source_title).casefold()
        matches: dict[str, int] = {}
        for brand_key, brand in self.brands.items():
            values = [brand["brand_ja"], brand["brand_en"], *brand["aliases"]]
            positions = []
            for value in values:
                position = normalized_title.find(
                    unicodedata.normalize("NFKC", value).casefold()
                )
                if position >= 0:
                    positions.append(position)
            if positions:
                matches[brand_key] = min(positions)
        if len(matches) != 1:
            return None
        brand_key = next(iter(matches))
        return brand_key, matches[brand_key]


def _infer_leading_unknown_bottler(
    record: dict[str, Any], brand_matcher: BrandMatcher
) -> str | None:
    """Conservatively flag an unrecognized title prefix for human review."""
    if (
        record.get("bottler_key")
        or not record.get("age")
        or not record.get("vintage")
        or not record.get("cask")
    ):
        return None

    normalized_title = unicodedata.normalize("NFKC", record["source_title"])
    brand_match = brand_matcher.find_in_title(normalized_title)
    if brand_match is None:
        return None
    _, brand_position = brand_match
    if brand_position == 0:
        return None

    prefix = normalized_title[:brand_position]
    prefix = prefix.strip(" \t\r\n・･,，、/／_-()（）[]【】")
    if not prefix or len(prefix) > 80 or re.fullmatch(r"[\d\W_]+", prefix):
        return None
    return prefix


def _aggregate_unknown_brand_proposals(
    observations: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[int, str]]:
    """Join unknown observations only when their normalized labels exactly overlap."""
    if not observations:
        return [], {}

    parents = list(range(len(observations)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[max(left_root, right_root)] = min(left_root, right_root)

    owners: dict[str, int] = {}
    for index, observation in enumerate(observations):
        keys = {
            comparison_key
            for _, value in observation["variants"]
            for comparison_key in comparison_keys(value)
        }
        for key in keys:
            owner = owners.setdefault(key, index)
            union(index, owner)

    components: dict[int, list[int]] = defaultdict(list)
    for index in range(len(observations)):
        components[find(index)].append(index)

    component_details: list[dict[str, Any]] = []
    for indexes in components.values():
        observed_variants = {
            value
            for index in indexes
            for _, value in observations[index]["variants"]
        }
        english_variants = {
            value
            for index in indexes
            for field, value in observations[index]["variants"]
            if field == "brand_en"
        }
        sorted_variants = sorted(
            observed_variants,
            key=lambda value: (
                value in english_variants,
                normalize_label(value),
                value,
            ),
        )
        titles: list[str] = []
        for index in indexes:
            title = observations[index]["source_title"]
            if title not in titles and len(titles) < 3:
                titles.append(title)
        component_details.append(
            {
                "candidate_key": proposed_brand_key(
                    sorted_variants, sorted(english_variants)
                ),
                "signature": tuple(
                    sorted(
                        (
                            field,
                            normalize_label(value),
                            value,
                        )
                        for index in indexes
                        for field, value in observations[index]["variants"]
                    )
                ),
                "observation_indexes": indexes,
                "observed_variants": sorted_variants,
                "occurrence_count": len(indexes),
                "sample_source_titles": titles,
            }
        )

    key_collisions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for details in component_details:
        key_collisions[details["candidate_key"]].append(details)

    proposals: list[dict[str, Any]] = []
    brand_keys_by_record: dict[int, str] = {}
    for candidate_key, colliding_components in key_collisions.items():
        colliding_components.sort(key=lambda details: details["signature"])
        for collision_index, details in enumerate(colliding_components):
            brand_key = candidate_key
            if collision_index:
                signature_json = json.dumps(
                    details["signature"], ensure_ascii=False, separators=(",", ":")
                )
                suffix = hashlib.sha256(signature_json.encode("utf-8")).hexdigest()[:8]
                brand_key = f"{candidate_key}_{suffix}"
            proposal = {
                "brand_key": brand_key,
                "observed_variants": details["observed_variants"],
                "occurrence_count": details["occurrence_count"],
                "sample_source_titles": details["sample_source_titles"],
                "suggested_aliases": list(details["observed_variants"]),
            }
            proposals.append(proposal)
            for observation_index in details["observation_indexes"]:
                record_index = observations[observation_index]["record_index"]
                brand_keys_by_record[record_index] = brand_key

    proposals.sort(
        key=lambda proposal: (-proposal["occurrence_count"], proposal["brand_key"])
    )
    return proposals, brand_keys_by_record


def build_catalog_outputs(
    raw_results: list[dict[str, Any]],
    brands: dict[str, dict[str, Any]],
    model_id: str,
    extracted_at: str,
    bottlers: dict[str, dict[str, Any]] | None = None,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, int],
]:
    """Filter, match, deduplicate, and aggregate model results."""
    matcher = BrandMatcher(brands)
    deduplicated: dict[str, dict[str, Any]] = {}
    bottler_proposals: dict[str, dict[str, Any]] = {}
    prepared_records: list[dict[str, Any]] = []
    unknown_brand_observations: list[dict[str, Any]] = []

    whiskey_count = sum(bool(record["is_whiskey"]) for record in raw_results)
    set_excluded_count = sum(
        bool(record["is_whiskey"] and record["is_multi_bottle_set"])
        for record in raw_results
    )
    known_brand_count = 0
    unknown_brand_count = 0
    unknown_bottler_count = 0
    bottler_matcher = BottlerMatcher(bottlers) if bottlers is not None else None

    for source_record in raw_results:
        raw = dict(source_record)
        if not raw["is_whiskey"] or raw["is_multi_bottle_set"]:
            continue

        if bottler_matcher is not None:
            bottler_matcher.separate(raw, raw["source_title"])
        unknown_bottler_variants = list(raw.get("_unknown_bottler_variants", []))
        if not unknown_bottler_variants:
            inferred = _infer_leading_unknown_bottler(raw, matcher)
            if inferred:
                unknown_bottler_variants.append(inferred)
                raw["brand_ja"] = None
                raw["brand_en"] = None
        if unknown_bottler_variants:
            unknown_bottler_count += 1
            bottler_key = proposed_bottler_key(unknown_bottler_variants)
            proposal = bottler_proposals.setdefault(
                bottler_key,
                {
                    "bottler_key": bottler_key,
                    "observed_variants": [],
                    "occurrence_count": 0,
                    "sample_source_titles": [],
                },
            )
            proposal["occurrence_count"] += 1
            for value in unknown_bottler_variants:
                if value not in proposal["observed_variants"]:
                    proposal["observed_variants"].append(value)
            if (
                raw["source_title"] not in proposal["sample_source_titles"]
                and len(proposal["sample_source_titles"]) < 3
            ):
                proposal["sample_source_titles"].append(raw["source_title"])

        brand_key = matcher.match(raw.get("brand_ja"), raw.get("brand_en"))
        if brand_key:
            known_brand_count += 1
        else:
            unknown_brand_count += 1
            brand_key = None

        record_index = len(prepared_records)
        raw["_resolved_brand_key"] = brand_key
        observed_variants = [
            (field, value)
            for field in ("brand_ja", "brand_en")
            if (value := raw.get(field))
        ]
        if brand_key is None and observed_variants:
            unknown_brand_observations.append(
                {
                    "record_index": record_index,
                    "variants": observed_variants,
                    "source_title": raw["source_title"],
                }
            )
        prepared_records.append(raw)

    proposed_brands, proposed_keys_by_record = (
        _aggregate_unknown_brand_proposals(unknown_brand_observations)
    )
    for record_index, brand_key in proposed_keys_by_record.items():
        prepared_records[record_index]["_resolved_brand_key"] = brand_key

    for raw in prepared_records:
        brand_key = raw["_resolved_brand_key"]

        identity = {
            "brand_key": brand_key,
            "expression_code": expression_code(raw.get("expression")),
            "age": raw.get("age"),
            "edition": raw.get("edition"),
            "cask": raw.get("cask"),
            "vintage": raw.get("vintage"),
            "bottler": raw.get("bottler_key")
            or raw.get("bottler_en")
            or raw.get("bottler_ja"),
        }
        key = catalog_key(identity)
        if key in deduplicated:
            existing = deduplicated[key]
            if raw["source_title"] not in existing["source_titles"]:
                existing["source_titles"].append(raw["source_title"])
            source_item = {
                "source_title": raw["source_title"],
                **raw.get("source_fields", {}),
            }
            if source_item not in existing["source_items"]:
                existing["source_items"].append(source_item)
            existing["confidence"] = max(existing["confidence"], raw["confidence"])
            continue

        record = {
            "catalog_key": key,
            "is_whiskey": True,
            "is_multi_bottle_set": False,
            "brand_key": brand_key,
            "brand_ja": raw.get("brand_ja"),
            "brand_en": raw.get("brand_en"),
            "distillery_ja": raw.get("distillery_ja"),
            "bottler_key": raw.get("bottler_key"),
            "bottler_ja": raw.get("bottler_ja"),
            "bottler_en": raw.get("bottler_en"),
            "bottler": raw.get("bottler_en") or raw.get("bottler_ja"),
            "expression": raw.get("expression"),
            "expression_code": identity["expression_code"],
            "edition": raw.get("edition"),
            "age": raw.get("age"),
            "vintage": raw.get("vintage"),
            "cask": raw.get("cask"),
            "abv": raw.get("abv"),
            "volume_ml": raw.get("volume_ml"),
            "confidence": raw["confidence"],
            "source_title": raw["source_title"],
            "source_titles": [raw["source_title"]],
            "source_items": [
                {
                    "source_title": raw["source_title"],
                    **raw.get("source_fields", {}),
                }
            ],
            "source": "rakuten_bedrock",
            "extraction_model": model_id,
            "extracted_at": extracted_at,
        }
        deduplicated[key] = record

    expressions = list(deduplicated.values())
    proposed_bottlers = sorted(
        bottler_proposals.values(),
        key=lambda proposal: (-proposal["occurrence_count"], proposal["bottler_key"]),
    )
    summary = {
        "total": len(raw_results),
        "whiskey": whiskey_count,
        "set_excluded": set_excluded_count,
        "deduplicated": len(expressions),
        "known_brand": known_brand_count,
        "unknown_brand": unknown_brand_count,
        "unknown_bottler": unknown_bottler_count,
    }
    return expressions, proposed_brands, proposed_bottlers, summary


def parse_response_json(response_text: str) -> dict[str, Any]:
    """Extract the first valid results object from fences or surrounding prose."""
    decoder = json.JSONDecoder()
    decode_errors: list[json.JSONDecodeError] = []
    for match in re.finditer(r"\{", response_text):
        start = match.start()
        try:
            parsed, _ = decoder.raw_decode(response_text[start:])
        except json.JSONDecodeError as error:
            decode_errors.append(
                json.JSONDecodeError(error.msg, response_text, start + error.pos)
            )
            continue
        if isinstance(parsed, dict) and isinstance(parsed.get("results"), list):
            return parsed

    if decode_errors:
        raise max(decode_errors, key=lambda error: error.pos)
    raise ValueError("model response must contain a results array")


def map_batch_results(
    product_titles: list[str],
    parsed_results: list[Any],
    bottlers: dict[str, dict[str, Any]] | None = None,
    logger: logging.Logger | None = None,
) -> list[dict[str, Any]]:
    """Map valid zero-based indexes to immutable inputs without guessing."""
    result_logger = logger or logging.getLogger(__name__)
    candidates: dict[int, list[Any]] = defaultdict(list)
    for raw in parsed_results:
        if not isinstance(raw, dict):
            result_logger.warning("Discarding non-object model result")
            continue
        if "input_index" not in raw:
            result_logger.warning("Discarding model result with missing input_index")
            continue
        input_index = raw["input_index"]
        if (
            isinstance(input_index, bool)
            or not isinstance(input_index, int)
            or input_index < 0
            or input_index >= len(product_titles)
        ):
            result_logger.warning(
                "Discarding model result with out-of-range input_index: %r",
                input_index,
            )
            continue
        candidates[input_index].append(raw)

    duplicate_indexes = {
        input_index
        for input_index, records in candidates.items()
        if len(records) > 1
    }
    for input_index in sorted(duplicate_indexes):
        result_logger.warning(
            "Discarding duplicate model results for input_index: %d",
            input_index,
        )
        del candidates[input_index]

    mapped: list[dict[str, Any]] = []
    for input_index in range(len(product_titles)):
        records = candidates.get(input_index)
        if not records:
            result_logger.warning(
                "No valid model result for input_index: %d", input_index
            )
            continue
        record = sanitize_model_result(
            records[0], product_titles[input_index], bottlers=bottlers
        )
        record["_input_index"] = input_index
        mapped.append(record)
    return mapped


def load_product_titles(
    input_path: Path, limit: int | None
) -> tuple[list[str], list[dict[str, Any]], dict[str, Any]]:
    """Load current string titles while accepting future object-shaped sources."""
    with input_path.open(encoding="utf-8") as input_file:
        document = json.load(input_file)
    products = document.get("product_names")
    if not isinstance(products, list):
        raise ValueError("input file must contain a product_names array")

    titles: list[str] = []
    source_fields: list[dict[str, Any]] = []
    title_keys = {"source_title", "product_name", "title", "name"}
    for position, product in enumerate(products):
        if isinstance(product, str):
            title = product
            item_source_fields = {}
        elif isinstance(product, dict):
            title = next(
                (
                    product[key]
                    for key in ("source_title", "product_name", "title", "name")
                    if isinstance(product.get(key), str)
                ),
                None,
            )
            item_source_fields = {
                key: value for key, value in product.items() if key not in title_keys
            }
        else:
            title = None
            item_source_fields = {}
        if not title or not title.strip():
            raise ValueError(f"product_names[{position}] has no usable title")
        titles.append(title)
        source_fields.append(item_source_fields)

    selected = titles if limit is None else titles[:limit]
    selected_source_fields = source_fields if limit is None else source_fields[:limit]
    metadata = document.get("metadata")
    return (
        selected,
        selected_source_fields,
        metadata if isinstance(metadata, dict) else {},
    )


def titles_fingerprint(titles: list[str]) -> str:
    """Identify the exact selected input used by a checkpoint."""
    payload = json.dumps(titles, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ClaudeSonnetWhiskeyExtractor:
    """Batch extractor with lazy Bedrock initialization and resumable checkpoints."""

    def __init__(
        self,
        *,
        model_id: str | None = None,
        region: str = DEFAULT_REGION,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_retries: int = DEFAULT_MAX_RETRIES,
        bedrock_client: Any = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        now_fn: Callable[[], str] = utc_now,
        bottlers_path: Path | str = DEFAULT_BOTTLERS_PATH,
        failed_batches_dir: Path | str = DEFAULT_FAILED_BATCHES_DIR,
    ):
        self.model_id = model_id or os.getenv("EXTRACT_MODEL_ID", DEFAULT_MODEL_ID)
        self.region = region
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.bedrock = bedrock_client
        self.sleep_fn = sleep_fn
        self.now_fn = now_fn
        self.bottlers_path = Path(bottlers_path)
        self.failed_batches_dir = Path(failed_batches_dir)
        self.bottlers = load_bottlers(self.bottlers_path)
        self.logger = logging.getLogger(__name__)

    def _get_bedrock_client(self) -> Any:
        if self.bedrock is None:
            self.bedrock = boto3.client(
                "bedrock-runtime",
                region_name=self.region,
                config=Config(
                    retries={"total_max_attempts": 5, "mode": "adaptive"},
                    connect_timeout=10,
                    read_timeout=180,
                ),
            )
        return self.bedrock

    def create_extraction_prompt(self, product_titles: list[str]) -> str:
        """Build an extraction-only prompt without any alias-generation field."""
        indexed_products = [
            {"input_index": index, "source_title": title}
            for index, title in enumerate(product_titles)
        ]
        products_json = json.dumps(indexed_products, ensure_ascii=False)
        bottlers_json = json.dumps(
            [
                {
                    "bottler_key": bottler["bottler_key"],
                    "bottler_ja": bottler["bottler_ja"],
                    "bottler_en": bottler["bottler_en"],
                    "aliases": bottler["aliases"],
                }
                for bottler in self.bottlers.values()
            ],
            ensure_ascii=False,
        )
        return f"""You extract structured whiskey facts from Japanese ecommerce titles.

Rules:
- Return exactly one result for every input, with the same zero-based input_index and order.
- Extract only text or numbers present in source_title. Never translate, infer, or add facts.
- Use null when a field is not explicitly readable from the title.
- Never output aliases or alternate names.
- Set is_whiskey=false for glasses, snacks, empty bottles, and other non-whiskey items.
- Set is_multi_bottle_set=true when one title contains multiple distinct bottles/products.
- Used/unopened status, parallel import, box status, delivery restrictions, and gift words
  are listing attributes. Ignore them for product identity, but do not reject the whiskey.
- Ignore date codes such as 20250827 and unrelated model/product codes.
- Use the curated known-bottler reference below. When a title contains any known
  bottler or series alias, put that bottler in bottler_ja/bottler_en and put only
  the distillery/whiskey name in brand_ja/brand_en.
- Never include a bottler name or its series alias in a brand field.
- If wording looks like an independent bottler but is absent from the reference,
  copy only the observed bottler-like wording to bottler_ja/bottler_en, do not mix it
  into brand_ja/brand_en, and use null for the brand rather than guessing.
- expression is the named product expression excluding brand, age, vintage, cask, ABV,
  volume, and listing attributes. edition is a distinct edition descriptor when written.
- age and volume_ml are integers. vintage is a four-digit year when written.
- abv is a numeric string without the percent sign. confidence is from 0.0 to 1.0.

Return JSON only in this shape:
{{
  "results": [
    {{
      "input_index": 0,
      "is_whiskey": true,
      "is_multi_bottle_set": false,
      "brand_ja": null,
      "brand_en": null,
      "distillery_ja": null,
      "bottler_ja": null,
      "bottler_en": null,
      "expression": null,
      "edition": null,
      "age": null,
      "vintage": null,
      "cask": null,
      "abv": null,
      "volume_ml": null,
      "confidence": 0.0
    }}
  ]
}}

Known bottlers (human-curated reference; do not invent aliases):
{bottlers_json}

Inputs:
{products_json}"""

    def call_bedrock_api(self, prompt: str) -> str:
        """Call Bedrock Converse with a bounded output reservation."""
        response = self._get_bedrock_client().converse(
            modelId=self.model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={
                "maxTokens": DEFAULT_MAX_TOKENS,
                "temperature": 0,
            },
        )
        content = response["output"]["message"]["content"]
        response_text = "".join(
            block["text"]
            for block in content
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        )
        if not response_text:
            raise ValueError("Bedrock response contained no text")
        return response_text

    def _save_failed_response(
        self,
        response_text: str,
        batch_start_index: int,
        error: Exception,
    ) -> Path:
        """Persist and log a model response that could not be parsed or validated."""
        self.failed_batches_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        failed_path = (
            self.failed_batches_dir / f"{timestamp}_{batch_start_index}.txt"
        )
        failed_path.write_text(response_text, encoding="utf-8")

        preview = response_text[:200]
        error_position = (
            error.pos if isinstance(error, json.JSONDecodeError) else None
        )
        if error_position is None:
            context = response_text[:200]
            position_label = "unknown"
        else:
            context = response_text[
                max(0, error_position - 100) : error_position + 100
            ]
            position_label = str(error_position)
        self.logger.warning(
            "Model response parse/validation failed at position %s; "
            "first 200 chars=%r; context (+/-100 chars)=%r; saved=%s",
            position_label,
            preview,
            context,
            failed_path,
        )
        return failed_path

    def _attempt_batch(
        self,
        product_titles: list[str],
        *,
        result_offset: int,
        batch_start_index: int,
    ) -> list[dict[str, Any]]:
        """Make one model call and map its local indexes into the original batch."""
        prompt = self.create_extraction_prompt(product_titles)
        response_text = self.call_bedrock_api(prompt)
        try:
            parsed = parse_response_json(response_text)
            mapped = map_batch_results(
                product_titles,
                parsed["results"],
                bottlers=self.bottlers,
                logger=self.logger,
            )
        except (KeyError, TypeError, ValueError) as error:
            self._save_failed_response(response_text, batch_start_index, error)
            raise
        for record in mapped:
            record["_input_index"] += result_offset
        return mapped

    @staticmethod
    def _is_retryable_client_error(error: ClientError) -> bool:
        code = error.response.get("Error", {}).get("Code", "")
        return code in {
            "ThrottlingException",
            "ModelTimeoutException",
            "ServiceUnavailableException",
            "InternalServerException",
        }

    def _run_stage_attempt(
        self,
        product_titles: list[str],
        *,
        result_offset: int,
        batch_start_index: int,
        stage: str,
    ) -> list[dict[str, Any]]:
        try:
            return self._attempt_batch(
                product_titles,
                result_offset=result_offset,
                batch_start_index=batch_start_index,
            )
        except ClientError as error:
            if not self._is_retryable_client_error(error):
                raise
            self.logger.warning("%s failed: %s", stage, error)
            raise RuntimeError(f"{stage} failed") from error
        except (BotoCoreError, KeyError, TypeError, ValueError) as error:
            self.logger.warning("%s failed: %s", stage, error)
            raise RuntimeError(f"{stage} failed") from error

    def process_batch(
        self,
        product_titles: list[str],
        *,
        batch_start_index: int = 0,
    ) -> list[dict[str, Any]]:
        """Extract a batch, then shrink only failed work to halves and singletons."""
        if not product_titles:
            return []
        try:
            return self._run_stage_attempt(
                product_titles,
                result_offset=0,
                batch_start_index=batch_start_index,
                stage="Full batch attempt",
            )
        except RuntimeError:
            if len(product_titles) == 1:
                self.logger.error(
                    "Discarding failed input index %d", batch_start_index
                )
                return []

        midpoint = len(product_titles) // 2
        chunks = [
            (0, product_titles[:midpoint]),
            (midpoint, product_titles[midpoint:]),
        ]
        recovered: list[dict[str, Any]] = []
        failed_chunks: list[tuple[int, list[str]]] = []
        for offset, chunk in chunks:
            try:
                recovered.extend(
                    self._run_stage_attempt(
                        chunk,
                        result_offset=offset,
                        batch_start_index=batch_start_index + offset,
                        stage=f"Half-batch attempt at index {batch_start_index + offset}",
                    )
                )
            except RuntimeError:
                failed_chunks.append((offset, chunk))

        for chunk_offset, chunk in failed_chunks:
            for item_offset, title in enumerate(chunk):
                result_offset = chunk_offset + item_offset
                absolute_index = batch_start_index + result_offset
                try:
                    recovered.extend(
                        self._run_stage_attempt(
                            [title],
                            result_offset=result_offset,
                            batch_start_index=absolute_index,
                            stage=f"Single-item attempt at index {absolute_index}",
                        )
                    )
                except RuntimeError:
                    self.logger.error(
                        "Discarding failed input index %d", absolute_index
                    )

        return sorted(recovered, key=lambda record: record["_input_index"])

    def _load_checkpoint(
        self,
        checkpoint_path: Path,
        fingerprint: str,
        input_path: Path,
    ) -> tuple[int, list[dict[str, Any]], str, list[dict[str, Any]]]:
        if not checkpoint_path.exists():
            return 0, [], self.now_fn(), []
        with checkpoint_path.open(encoding="utf-8") as checkpoint_file:
            checkpoint = json.load(checkpoint_file)
        expected = {
            "input_file": str(input_path.resolve()),
            "input_fingerprint": fingerprint,
            "model_id": self.model_id,
            "batch_size": self.batch_size,
        }
        actual = {key: checkpoint.get(key) for key in expected}
        if actual != expected:
            raise ValueError(
                f"checkpoint {checkpoint_path} belongs to a different extraction; "
                "move or remove it before starting"
            )
        results = checkpoint.get("raw_results")
        next_index = checkpoint.get("next_index")
        extracted_at = checkpoint.get("extracted_at")
        failed_batches = checkpoint.get("failed_batches", [])
        if (
            not isinstance(results, list)
            or isinstance(next_index, bool)
            or not isinstance(next_index, int)
            or not isinstance(extracted_at, str)
            or not isinstance(failed_batches, list)
        ):
            raise ValueError(f"checkpoint {checkpoint_path} is malformed")
        return next_index, results, extracted_at, failed_batches

    def _save_checkpoint(
        self,
        checkpoint_path: Path,
        input_path: Path,
        fingerprint: str,
        next_index: int,
        raw_results: list[dict[str, Any]],
        extracted_at: str,
        failed_batches: list[dict[str, Any]],
    ) -> None:
        write_json(
            checkpoint_path,
            {
                "version": 2,
                "input_file": str(input_path.resolve()),
                "input_fingerprint": fingerprint,
                "model_id": self.model_id,
                "batch_size": self.batch_size,
                "next_index": next_index,
                "extracted_at": extracted_at,
                "raw_results": raw_results,
                "failed_batches": failed_batches,
            },
        )

    def process_file(
        self,
        input_path: Path | str,
        *,
        brands_path: Path | str = DEFAULT_BRANDS_PATH,
        bottlers_path: Path | str = DEFAULT_BOTTLERS_PATH,
        output_path: Path | str = DEFAULT_OUTPUT_PATH,
        proposals_path: Path | str = DEFAULT_PROPOSALS_PATH,
        bottler_proposals_path: Path | str = DEFAULT_BOTTLER_PROPOSALS_PATH,
        checkpoint_path: Path | str = DEFAULT_CHECKPOINT_PATH,
        limit: int | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any] | None:
        """Process a source file, saving each completed batch for safe resume."""
        input_path = Path(input_path)
        brands_path = Path(brands_path)
        bottlers_path = Path(bottlers_path)
        output_path = Path(output_path)
        proposals_path = Path(proposals_path)
        bottler_proposals_path = Path(bottler_proposals_path)
        checkpoint_path = Path(checkpoint_path)
        if bottlers_path != self.bottlers_path:
            self.bottlers_path = bottlers_path
            self.bottlers = load_bottlers(bottlers_path)
        product_titles, source_fields, source_metadata = load_product_titles(
            input_path, limit
        )
        total_batches = (
            (len(product_titles) + self.batch_size - 1) // self.batch_size
            if product_titles
            else 0
        )
        maximum_calls = 0
        for start in range(0, len(product_titles), self.batch_size):
            batch_length = len(product_titles[start : start + self.batch_size])
            maximum_calls += 1
            if batch_length > 1:
                maximum_calls += 2 + batch_length
        print(f"処理対象: {len(product_titles)}件")
        print(f"バッチ数: {total_batches}")
        print(
            f"Bedrock予定コール数: {total_batches}"
            f"（リトライ込み最大 {maximum_calls} コール）"
        )
        print(f"モデル: {self.model_id}")
        if dry_run:
            print("DRY RUN: Bedrock は呼び出していません。")
            return None

        fingerprint = titles_fingerprint(product_titles)
        next_index, raw_results, extracted_at, failed_batches = (
            self._load_checkpoint(checkpoint_path, fingerprint, input_path)
        )
        if next_index > len(product_titles) or len(raw_results) > next_index:
            raise ValueError(f"checkpoint {checkpoint_path} has inconsistent progress")
        if next_index:
            print(f"再開: {next_index}/{len(product_titles)}件を復元")

        for start in range(next_index, len(product_titles), self.batch_size):
            batch = product_titles[start : start + self.batch_size]
            batch_source_fields = source_fields[start : start + self.batch_size]
            batch_number = start // self.batch_size + 1
            print(f"バッチ {batch_number}/{total_batches}: {len(batch)}件")
            batch_results = self.process_batch(
                batch, batch_start_index=start
            )
            successful_local_indexes: set[int] = set()
            for record in batch_results:
                local_index = record.pop("_input_index")
                successful_local_indexes.add(local_index)
                item_source_fields = batch_source_fields[local_index]
                if item_source_fields:
                    record["source_fields"] = item_source_fields
            failed_local_indexes = sorted(
                set(range(len(batch))) - successful_local_indexes
            )
            if failed_local_indexes:
                failed_batches.append(
                    {
                        "batch_number": batch_number,
                        "start_index": start,
                        "end_index": start + len(batch) - 1,
                        "failed_indexes": [
                            start + index for index in failed_local_indexes
                        ],
                    }
                )
            raw_results.extend(batch_results)
            next_index = start + len(batch)
            self._save_checkpoint(
                checkpoint_path,
                input_path,
                fingerprint,
                next_index,
                raw_results,
                extracted_at,
                failed_batches,
            )

        brands = load_brands(brands_path)
        expressions, proposals, bottler_proposals, summary = build_catalog_outputs(
            raw_results,
            brands,
            self.model_id,
            extracted_at,
            bottlers=self.bottlers,
        )
        summary.update(
            {
                "input_total": len(product_titles),
                "successful_item_count": len(raw_results),
                "failed_batch_count": len(failed_batches),
                "failed_item_count": sum(
                    len(batch["failed_indexes"]) for batch in failed_batches
                ),
                "failed_batches": failed_batches,
            }
        )
        write_json(
            output_path,
            {
                "version": 1,
                "metadata": {
                    "input_file": str(input_path),
                    "source_metadata": source_metadata,
                    "extraction_model": self.model_id,
                    "extracted_at": extracted_at,
                    "failed_batch_count": len(failed_batches),
                    "failed_batches": failed_batches,
                },
                "expressions": expressions,
            },
        )
        write_json(
            proposals_path,
            {
                "version": 1,
                "generated_at": self.now_fn(),
                "source": "rakuten_bedrock",
                "proposed_brands": proposals,
            },
        )
        write_json(
            bottler_proposals_path,
            {
                "version": 1,
                "generated_at": self.now_fn(),
                "source": "rakuten_bedrock",
                "proposed_bottlers": bottler_proposals,
            },
        )
        checkpoint_path.unlink(missing_ok=True)
        print_summary(summary)
        return summary


def print_summary(summary: dict[str, Any]) -> None:
    """Print the required extraction summary."""
    print("=== サマリ ===")
    print(f"総件数: {summary.get('input_total', summary['total'])}")
    print(f"抽出成功件数: {summary.get('successful_item_count', summary['total'])}")
    print(f"ウイスキー判定件数: {summary['whiskey']}")
    print(f"セット除外件数: {summary['set_excluded']}")
    print(f"重複排除後の件数: {summary['deduplicated']}")
    print(f"既知ブランド一致件数: {summary['known_brand']}")
    print(f"未知ブランド件数: {summary['unknown_brand']}")
    print(f"未知ボトラー候補件数: {summary['unknown_bottler']}")
    print(f"失敗バッチ数: {summary.get('failed_batch_count', 0)}")
    for failed_batch in summary.get("failed_batches", []):
        print(
            "失敗バッチ "
            f"{failed_batch['batch_number']}: "
            f"対象インデックス {failed_batch['start_index']}"
            f"-{failed_batch['end_index']} "
            f"(破棄: {failed_batch['failed_indexes']})"
        )


def non_negative_int(value: str) -> int:
    """Argparse converter for a non-negative processing limit."""
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="楽天商品名からレビュー用の構造化ウイスキーカタログ候補を抽出"
    )
    parser.add_argument("--input-file", required=True, type=Path)
    parser.add_argument("--limit", type=non_negative_int, default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Bedrockを呼ばず、対象件数・バッチ数・予定コール数だけを表示",
    )
    parser.add_argument("--brands-file", type=Path, default=DEFAULT_BRANDS_PATH)
    parser.add_argument("--bottlers-file", type=Path, default=DEFAULT_BOTTLERS_PATH)
    parser.add_argument("--output-file", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument(
        "--proposed-brands-file", type=Path, default=DEFAULT_PROPOSALS_PATH
    )
    parser.add_argument(
        "--proposed-bottlers-file",
        type=Path,
        default=DEFAULT_BOTTLER_PROPOSALS_PATH,
    )
    parser.add_argument("--checkpoint-file", type=Path, default=DEFAULT_CHECKPOINT_PATH)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and present top-level AWS/validation errors."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = parse_args(argv)
    if not args.input_file.is_file():
        print(f"ERROR: ファイルが見つかりません: {args.input_file}", file=sys.stderr)
        return 1

    extractor = ClaudeSonnetWhiskeyExtractor()
    try:
        summary = extractor.process_file(
            args.input_file,
            brands_path=args.brands_file,
            bottlers_path=args.bottlers_file,
            output_path=args.output_file,
            proposals_path=args.proposed_brands_file,
            bottler_proposals_path=args.proposed_bottlers_file,
            checkpoint_path=args.checkpoint_file,
            limit=args.limit,
            dry_run=args.dry_run,
        )
        return 1 if summary and summary.get("failed_batch_count", 0) else 0
    except KeyboardInterrupt:
        print("中断しました。完了済みバッチはチェックポイントに保存されています。")
        return 130
    except (BotoCoreError, ClientError, OSError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
