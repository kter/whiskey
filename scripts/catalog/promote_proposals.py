#!/usr/bin/env python3
"""Regroup extracted brand observations and prepare reviewable promotions."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


CATALOG_DIR = Path(__file__).resolve().parent
DEFAULT_BRANDS_PATH = CATALOG_DIR / "brands.json"
DEFAULT_GENERIC_TERMS_PATH = CATALOG_DIR / "generic_terms.json"
DEFAULT_PENDING_PATH = CATALOG_DIR / "pending_brands.json"
ARTICLE_PREFIXES = ("the ", "ザ・", "ザ ")
WARNING_ORDER = (
    "contains_generic_term",
    "prefix_of_other_candidate",
    "single_variant_only",
    "very_short",
)
CJK_PATTERN = re.compile(
    "[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]"
)


def normalize_label(value: str) -> str:
    """Return the normalized display label used for exact comparisons."""
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return " ".join(normalized.split())


def _without_leading_article(value: str) -> str | None:
    """Remove one supported leading article when enough text remains."""
    candidate: str | None = None
    for prefix in ARTICLE_PREFIXES:
        if value.startswith(prefix):
            candidate = value[len(prefix) :].strip()
            break
    if candidate is None and value.startswith("ザ"):
        candidate = value[1:].strip()
    if candidate is None:
        return None
    return candidate if len(_without_whitespace(candidate)) >= 3 else None


def _without_whitespace(value: str) -> str:
    return "".join(value.split())


def _contains_cjk(value: str) -> bool:
    return CJK_PATTERN.search(value) is not None


def comparison_keys(value: str) -> set[str]:
    """Return article- and CJK-whitespace-independent exact comparison keys."""
    normalized = normalize_label(value)
    keys = {normalized}
    without_article = _without_leading_article(normalized)
    if without_article is not None:
        keys.add(without_article)
    keys.update(
        _without_whitespace(key) for key in tuple(keys) if _contains_cjk(key)
    )
    return {key for key in keys if key}


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as source_file:
        return json.load(source_file)


def _load_brands_document(path: Path) -> dict[str, Any]:
    document = _load_json(path)
    if not isinstance(document, dict) or document.get("version") != 1:
        raise ValueError(f"{path} must use catalog version 1")
    brands = document.get("brands")
    if not isinstance(brands, list):
        raise ValueError(f"{path} must contain a brands list")
    for position, brand in enumerate(brands):
        if not isinstance(brand, dict):
            raise ValueError(f"brand {position} in {path} must be an object")
        if not isinstance(brand.get("brand_key"), str):
            raise ValueError(f"brand {position} in {path} needs a brand_key")
        aliases = brand.get("aliases")
        if not isinstance(aliases, list) or any(
            not isinstance(alias, str) for alias in aliases
        ):
            raise ValueError(f"brand {position} in {path} needs string aliases")
    return document


def load_expressions(path: Path) -> list[dict[str, Any]]:
    """Load the versioned extraction output without invoking a model."""
    document = _load_json(path)
    if not isinstance(document, dict) or document.get("version") != 1:
        raise ValueError(f"{path} must use extraction version 1")
    expressions = document.get("expressions")
    if not isinstance(expressions, list):
        raise ValueError(f"{path} must contain an expressions list")
    if any(not isinstance(expression, dict) for expression in expressions):
        raise ValueError(f"every expression in {path} must be an object")
    return expressions


def load_generic_terms(path: Path) -> list[str]:
    """Load configurable generic terms used only to flag review candidates."""
    document = _load_json(path)
    if not isinstance(document, dict) or document.get("version") != 1:
        raise ValueError(f"{path} must use generic-term version 1")
    terms = document.get("terms")
    if not isinstance(terms, list) or any(
        not isinstance(term, str) or not term.strip() for term in terms
    ):
        raise ValueError(f"{path} must contain a list of non-empty terms")
    return list(dict.fromkeys(terms))


def _brand_lookup(brands: Sequence[dict[str, Any]]) -> dict[str, set[str]]:
    lookup: dict[str, set[str]] = defaultdict(set)
    for brand in brands:
        values = [
            brand.get("brand_ja"),
            brand.get("brand_en"),
            *brand.get("aliases", []),
        ]
        for value in values:
            if isinstance(value, str) and value.strip():
                for key in comparison_keys(value):
                    lookup[key].add(brand["brand_key"])
    return lookup


def _observed_variants(expression: dict[str, Any]) -> list[tuple[str, str]]:
    variants: list[tuple[str, str]] = []
    for field in ("brand_ja", "brand_en"):
        value = expression.get(field)
        if isinstance(value, str) and value.strip():
            variants.append((field, value.strip()))
    return variants


def _known_brand_match(
    variants: Sequence[tuple[str, str]], lookup: dict[str, set[str]]
) -> str | None:
    matches: set[str] = set()
    for _, value in variants:
        for key in comparison_keys(value):
            matches.update(lookup.get(key, set()))
    return next(iter(matches)) if len(matches) == 1 else None


def _preferred_variant(counts: Counter[str]) -> str:
    if not counts:
        return ""
    return min(
        counts,
        key=lambda value: (-counts[value], normalize_label(value), value),
    )


def _ascii_slug(value: str) -> str:
    normalized = normalize_label(value)
    canonical = _without_leading_article(normalized) or normalized
    ascii_value = (
        unicodedata.normalize("NFKD", canonical)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    return re.sub(r"[^a-z0-9]+", "_", ascii_value.casefold()).strip("_")


def brand_key_from_labels(
    brand_ja: str, brand_en: str, observed_variants: Iterable[str]
) -> str:
    """Build a deterministic English slug or stable normalized-label hash."""
    if brand_en:
        slug = _ascii_slug(brand_en)
        if slug:
            return slug
    keys = {
        key
        for variant in observed_variants
        for key in comparison_keys(variant)
    }
    if brand_ja:
        keys.update(comparison_keys(brand_ja))
    canonical = min(keys, key=lambda value: (len(value), value)) if keys else "unknown"
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:10]
    return f"proposed_{digest}"


def _group_observations(
    observations: Sequence[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
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

    key_owners: dict[str, int] = {}
    for index, observation in enumerate(observations):
        keys = {
            key
            for _, value in observation["variants"]
            for key in comparison_keys(value)
        }
        for key in keys:
            if key in key_owners:
                union(index, key_owners[key])
            else:
                key_owners[key] = index

    components: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for index, observation in enumerate(observations):
        components[find(index)].append(observation)
    return list(components.values())


def _candidate_from_component(
    component: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    field_counts: dict[str, Counter[str]] = {
        "brand_ja": Counter(),
        "brand_en": Counter(),
    }
    all_counts: Counter[str] = Counter()
    sample_titles: list[str] = []
    for observation in component:
        for field, value in observation["variants"]:
            field_counts[field][value] += 1
            all_counts[value] += 1
        title = observation["source_title"]
        if title and title not in sample_titles and len(sample_titles) < 3:
            sample_titles.append(title)

    brand_ja = _preferred_variant(field_counts["brand_ja"])
    brand_en = _preferred_variant(field_counts["brand_en"])
    aliases = sorted(
        all_counts,
        key=lambda value: (-all_counts[value], normalize_label(value), value),
    )
    return {
        "brand_key": brand_key_from_labels(brand_ja, brand_en, aliases),
        "brand_ja": brand_ja,
        "brand_en": brand_en,
        "aliases": aliases,
        "observed_variants": list(aliases),
        "occurrence_count": len(component),
        "sample_source_titles": sample_titles,
        "warnings": [],
    }


def _prefix_forms(candidate: dict[str, Any]) -> set[str]:
    forms: set[str] = set()
    for value in candidate["observed_variants"]:
        normalized = normalize_label(value)
        canonical = _without_leading_article(normalized) or normalized
        if _contains_cjk(canonical):
            canonical = _without_whitespace(canonical)
        if canonical:
            forms.add(canonical)
    return forms


def _contains_configured_term(value: str, terms: Sequence[str]) -> bool:
    normalized_value = normalize_label(value)
    for term in terms:
        normalized_term = normalize_label(term)
        if normalized_term in normalized_value:
            return True
        if _contains_cjk(normalized_term) and _without_whitespace(
            normalized_term
        ) in _without_whitespace(normalized_value):
            return True
    return False


def add_quality_warnings(
    candidates: list[dict[str, Any]], generic_terms: Sequence[str]
) -> None:
    """Attach structural review warnings without filtering any candidate."""
    prefix_forms = [_prefix_forms(candidate) for candidate in candidates]
    for index, candidate in enumerate(candidates):
        warnings: set[str] = set()
        variants = candidate["observed_variants"]
        if any(
            _contains_configured_term(value, generic_terms) for value in variants
        ):
            warnings.add("contains_generic_term")
        if len(variants) == 1:
            warnings.add("single_variant_only")
        if any(len(_without_whitespace(normalize_label(value))) <= 2 for value in variants):
            warnings.add("very_short")

        other_forms = {
            form
            for other_index, forms in enumerate(prefix_forms)
            if other_index != index
            for form in forms
        }
        if any(
            other.startswith(form) and other != form
            for form in prefix_forms[index]
            for other in other_forms
        ):
            warnings.add("prefix_of_other_candidate")
        candidate["warnings"] = [
            warning for warning in WARNING_ORDER if warning in warnings
        ]


def build_pending_brands(
    expressions: Sequence[dict[str, Any]],
    brands: Sequence[dict[str, Any]],
    generic_terms: Sequence[str],
    min_occurrences: int = 2,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Exclude known brands, regroup observations, and return review candidates."""
    if min_occurrences < 1:
        raise ValueError("min_occurrences must be at least 1")
    lookup = _brand_lookup(brands)
    observations: list[dict[str, Any]] = []
    known_count = 0
    missing_label_count = 0
    for expression in expressions:
        variants = _observed_variants(expression)
        if not variants:
            missing_label_count += 1
            continue
        if _known_brand_match(variants, lookup) is not None:
            known_count += 1
            continue
        observations.append(
            {
                "variants": variants,
                "source_title": str(expression.get("source_title") or ""),
            }
        )

    all_candidates = [
        _candidate_from_component(component)
        for component in _group_observations(observations)
    ]
    candidates = [
        candidate
        for candidate in all_candidates
        if candidate["occurrence_count"] >= min_occurrences
    ]
    add_quality_warnings(candidates, generic_terms)
    candidates.sort(
        key=lambda candidate: (
            -candidate["occurrence_count"],
            candidate["brand_key"],
        )
    )
    return candidates, {
        "extracted_total": len(expressions),
        "known_matches_excluded": known_count,
        "missing_labels_excluded": missing_label_count,
        "below_threshold_groups_excluded": len(all_candidates) - len(candidates),
        "promotion_candidates": len(candidates),
    }


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def apply_candidates(
    brands_path: Path,
    brands_document: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
) -> int:
    """Append candidates after validating every key collision."""
    existing_keys = {brand["brand_key"] for brand in brands_document["brands"]}
    candidate_keys = [candidate["brand_key"] for candidate in candidates]
    duplicate_candidate_keys = {
        key for key, count in Counter(candidate_keys).items() if count > 1
    }
    collisions = existing_keys.intersection(candidate_keys) | duplicate_candidate_keys
    if collisions:
        raise ValueError(
            "brand_key collision: " + ", ".join(sorted(collisions))
        )

    additions = [
        {
            "brand_key": candidate["brand_key"],
            "brand_ja": candidate["brand_ja"],
            "brand_en": candidate["brand_en"],
            "aliases": list(candidate["aliases"]),
            "distillery_ja": "",
            "distillery_en": "",
            "region": "",
            "country": "",
        }
        for candidate in candidates
    ]
    updated_document = {
        **brands_document,
        "brands": [*brands_document["brands"], *additions],
    }
    _write_json(brands_path, updated_document)
    return len(additions)


def _warning_counts(candidates: Sequence[dict[str, Any]]) -> dict[str, int]:
    return {
        warning: sum(warning in candidate["warnings"] for candidate in candidates)
        for warning in WARNING_ORDER
    }


def _print_summary(
    summary: dict[str, int],
    candidates: Sequence[dict[str, Any]],
    applied_count: int | None,
) -> None:
    print(f"Extracted total: {summary['extracted_total']}")
    print(f"Known matches excluded: {summary['known_matches_excluded']}")
    print(f"Missing labels excluded: {summary['missing_labels_excluded']}")
    print(
        "Below-threshold groups excluded: "
        f"{summary['below_threshold_groups_excluded']}"
    )
    print(f"Promotion candidates: {summary['promotion_candidates']}")
    for warning, count in _warning_counts(candidates).items():
        print(f"Warning {warning}: {count}")
    if applied_count is not None:
        print(f"Brands appended: {applied_count}")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Regroup extracted unknown brands for human review."
    )
    parser.add_argument("--extracted", required=True, type=Path)
    parser.add_argument("--min-occurrences", type=int, default=2)
    parser.add_argument("--brands", type=Path, default=DEFAULT_BRANDS_PATH)
    parser.add_argument(
        "--generic-terms", type=Path, default=DEFAULT_GENERIC_TERMS_PATH
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_PENDING_PATH)
    parser.add_argument(
        "--exclude-warned",
        action="store_true",
        help=(
            "promote only candidates with no quality warnings. The flagged "
            "cases are company names and product-name fragments; promoting a "
            "company as a brand would swallow every product under it and "
            "collapse them all to ambiguous."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="append the reviewed candidates to brands.json",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.min_occurrences < 1:
            raise ValueError("--min-occurrences must be at least 1")
        expressions = load_expressions(args.extracted)
        brands_document = _load_brands_document(args.brands)
        generic_terms = load_generic_terms(args.generic_terms)
        candidates, summary = build_pending_brands(
            expressions,
            brands_document["brands"],
            generic_terms,
            args.min_occurrences,
        )
        # The review file always keeps every candidate so the flagged ones stay
        # visible; only the promotion set is narrowed.
        promotable = (
            [candidate for candidate in candidates if not candidate["warnings"]]
            if args.exclude_warned
            else candidates
        )
        pending_document = {
            "version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": str(args.extracted),
            "min_occurrences": args.min_occurrences,
            "exclude_warned": args.exclude_warned,
            "pending_brands": candidates,
        }
        _write_json(args.output, pending_document)
        applied_count = (
            apply_candidates(args.brands, brands_document, promotable)
            if args.apply
            else None
        )
        _print_summary(summary, candidates, applied_count)
        if args.exclude_warned:
            print(f"Promotable (no warnings): {len(promotable)}")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
