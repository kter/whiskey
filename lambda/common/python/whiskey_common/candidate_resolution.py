"""Turn validated model readings into safe, catalog-aware Whiskey Candidates."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from whiskey_common.normalize import normalize_text


_BRAND_PREFIX_RE = re.compile(r"^the\s+", re.IGNORECASE)
_BRAND_SUFFIX_RE = re.compile(
    r"(?:蒸溜所|蒸留所|蒸溜|蒸留|\s+(?:distillery|distillers))$",
    re.IGNORECASE,
)


def normalized_brand_variants(name: str) -> tuple[str, ...]:
    """Normalize a brand reading while removing only complete affixes."""
    variants = [name]
    without_prefix = _BRAND_PREFIX_RE.sub("", name)
    if without_prefix != name:
        variants.append(without_prefix)
    for variant in tuple(variants):
        without_suffix = _BRAND_SUFFIX_RE.sub("", variant)
        if without_suffix != variant:
            variants.append(without_suffix)
    return tuple(
        dict.fromkeys(
            normalized
            for variant in variants
            if (normalized := normalize_text(variant))
        )
    )


def normalize_proposal_label(value: str) -> str:
    """Normalize a human label for the eval-only partial-match policy."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


@dataclass(frozen=True)
class _BrandEntry:
    record: Mapping[str, Any]
    exact_names: tuple[str, ...]
    distillery_names: tuple[str, ...]
    proposal_names: tuple[str, ...]


class BrandCatalog:
    """Validate brand data and expose explicit runtime and eval match policies."""

    def __init__(self, entries: Sequence[_BrandEntry]):
        self._entries = tuple(entries)

    @classmethod
    def from_file(cls, path: Path) -> BrandCatalog:
        with path.open(encoding="utf-8") as source_file:
            document = json.load(source_file)
        if not isinstance(document, dict) or document.get("version") != 1:
            raise ValueError("brands catalog must be a version 1 JSON object")
        brands = document.get("brands")
        if not isinstance(brands, list):
            raise ValueError("brands catalog must contain a brands array")
        return cls.from_records(brands)

    @classmethod
    def from_records(cls, records: Iterable[Mapping[str, Any]]) -> BrandCatalog:
        entries: list[_BrandEntry] = []
        for index, source in enumerate(records):
            if not isinstance(source, Mapping):
                raise ValueError(f"brands[{index}] must be an object")
            record = dict(source)
            brand_key = record.get("brand_key")
            if not isinstance(brand_key, str) or not brand_key.strip():
                raise ValueError(f"brands[{index}].brand_key must be a non-empty string")
            brand_names = [record.get("brand_ja"), record.get("brand_en")]
            aliases = record.get("aliases")
            if isinstance(aliases, list):
                brand_names.extend(aliases)
            distillery_names = [
                record.get("distillery_ja"),
                record.get("distillery_en"),
            ]
            exact_names = tuple(
                dict.fromkeys(
                    normalized
                    for name in brand_names
                    if isinstance(name, str)
                    for normalized in normalized_brand_variants(name)
                )
            )
            exact_distilleries = tuple(
                dict.fromkeys(
                    normalized
                    for name in distillery_names
                    if isinstance(name, str)
                    for normalized in normalized_brand_variants(name)
                )
            )
            proposal_names = tuple(
                dict.fromkeys(
                    normalized
                    for name in (*brand_names, *distillery_names)
                    if isinstance(name, str)
                    if (normalized := normalize_proposal_label(name))
                )
            )
            if not exact_names:
                raise ValueError(f"brands[{index}] must contain a brand name")
            entries.append(
                _BrandEntry(record, exact_names, exact_distilleries, proposal_names)
            )

        brand_owners: dict[str, set[str]] = {}
        distillery_owners: dict[str, set[str]] = {}
        for entry in entries:
            brand_key = entry.record["brand_key"]
            for name in entry.exact_names:
                brand_owners.setdefault(name, set()).add(brand_key)
            for name in entry.distillery_names:
                distillery_owners.setdefault(name, set()).add(brand_key)

        resolved_entries = []
        for entry in entries:
            brand_key = entry.record["brand_key"]
            safe_distilleries = (
                name
                for name in entry.distillery_names
                if brand_owners.get(name) == {brand_key}
                or (name not in brand_owners and distillery_owners[name] == {brand_key})
            )
            resolved_entries.append(
                _BrandEntry(
                    entry.record,
                    tuple(dict.fromkeys((*entry.exact_names, *safe_distilleries))),
                    entry.distillery_names,
                    entry.proposal_names,
                )
            )
        return cls(resolved_entries)

    @property
    def records(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(entry.record for entry in self._entries)

    def exact_name_collisions(self) -> dict[str, tuple[str, ...]]:
        owners: dict[str, set[str]] = {}
        for entry in self._entries:
            for name in entry.exact_names:
                owners.setdefault(name, set()).add(entry.record["brand_key"])
        return {
            name: tuple(sorted(keys))
            for name, keys in owners.items()
            if len(keys) > 1
        }

    def exact_names_for(self, brand_key: str) -> tuple[str, ...]:
        return next(
            (entry.exact_names for entry in self._entries if entry.record["brand_key"] == brand_key),
            (),
        )

    def resolve_exact(self, whiskey: Mapping[str, Any]) -> Mapping[str, Any] | None:
        normalized_names = {
            normalized
            for field in ("brand_ja", "brand_en")
            if isinstance(name := whiskey.get(field), str)
            for normalized in normalized_brand_variants(name)
        }
        matches = [
            entry.record
            for entry in self._entries
            if normalized_names.intersection(entry.exact_names)
        ]
        return matches[0] if len(matches) == 1 else None

    def proposal_keys(self, canonical_name: Any) -> set[str]:
        """Return eval suggestions using partial matching, never runtime matching."""
        if not isinstance(canonical_name, str):
            return set()
        normalized = normalize_proposal_label(canonical_name)
        if not normalized:
            return set()
        return {
            entry.record["brand_key"]
            for entry in self._entries
            if any(name in normalized or normalized in name for name in entry.proposal_names)
        }


@dataclass(frozen=True)
class _WhiskeyEntry:
    record: Mapping[str, Any]
    normalized_names: tuple[str, ...]


class WhiskeyCatalog:
    """A bounded whiskey-master snapshot with fail-closed exact matching."""

    def __init__(self, entries: Sequence[_WhiskeyEntry], *, complete: bool):
        self._entries = tuple(entries)
        self.complete = complete

    @classmethod
    def from_records(
        cls,
        records: Iterable[Mapping[str, Any]],
        *,
        complete: bool,
    ) -> WhiskeyCatalog:
        entries = []
        for item in records:
            record = dict(item)
            names = [
                value
                for value in (
                    item.get("name_ja"),
                    item.get("name_en"),
                    item.get("name"),
                    item.get("normalized_name"),
                )
                if isinstance(value, str) and value
            ]
            normalized_names = tuple(
                dict.fromkeys(
                    normalized
                    for name in names
                    if (normalized := normalize_text(name))
                )
            )
            entries.append(_WhiskeyEntry(record, normalized_names))
        return cls(entries, complete=complete)

    @property
    def size(self) -> int:
        return len(self._entries)

    def resolve_exact(self, whiskey: Mapping[str, Any]) -> Mapping[str, Any] | None:
        if not self.complete:
            return None
        normalized_names = {
            normalized
            for field in ("name_ja", "name_en")
            if isinstance(name := whiskey.get(field), str) and name
            if (normalized := normalize_text(name))
        }
        matches: dict[str, Mapping[str, Any]] = {}
        for entry in self._entries:
            record_id = entry.record.get("id")
            if (
                isinstance(record_id, str)
                and record_id
                and normalized_names.intersection(entry.normalized_names)
            ):
                matches[record_id] = entry.record
        return next(iter(matches.values())) if len(matches) == 1 else None


class CandidateResolver:
    """Resolve validated model readings without exposing catalog internals."""

    def __init__(self, brand_catalog: BrandCatalog):
        self._brand_catalog = brand_catalog

    def resolve(
        self,
        whiskey_catalog: WhiskeyCatalog,
        analysis: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for whiskey in analysis.get("whiskeys", []):
            matched = whiskey_catalog.resolve_exact(whiskey)
            brand_matched = self._brand_catalog.resolve_exact(whiskey)
            candidate = {
                "brand_text": whiskey["name_ja"],
                "name_ja": whiskey["name_ja"],
                "name_en": whiskey["name_en"],
                "confidence": whiskey["confidence"],
                "match_source": "catalog" if matched is not None else "ai",
            }
            whiskey_id = matched.get("id") if matched is not None else None
            if isinstance(whiskey_id, str) and whiskey_id:
                candidate["whiskey_id"] = whiskey_id
            for brand_field in ("brand_ja", "brand_en"):
                if whiskey.get(brand_field):
                    candidate[brand_field] = whiskey[brand_field]
            if brand_matched is not None:
                candidate["brand_key"] = brand_matched["brand_key"]
                distillery = brand_matched.get("distillery_ja")
                if distillery:
                    candidate["distillery_ja"] = distillery
            candidates.append(candidate)
        return candidates
