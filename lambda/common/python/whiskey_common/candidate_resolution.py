"""Turn validated model readings into safe, catalog-aware Whiskey Candidates."""

from __future__ import annotations

import functools
import json
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from whiskey_common.normalize import normalize_text


_BRAND_PREFIX_RE = re.compile(r"^the\s+", re.IGNORECASE)
_BRAND_SUFFIX_RE = re.compile(
    r"(?:蒸溜所|蒸留所|蒸溜|蒸留|\s+(?:distillery|distillers))$",
    re.IGNORECASE,
)
UNMATCHED_BRAND_CONFIDENCE_CAP = Decimal("0.6")
_AGE_SUFFIX_RE = re.compile(
    r"\b(\d+)\s*(?:[- ]?years?(?:[- ]?old)?|[- ]?yo)\b", re.IGNORECASE
)
_LEADING_THE_RE = re.compile(r"^the\s+", re.IGNORECASE)
_LEADING_JA_ARTICLE_RE = re.compile(r"(?:ザ・|ザ\s)$")


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

    def matches_brand_name(
        self, record_or_key: Mapping[str, Any] | str, whiskey: Mapping[str, Any]
    ) -> bool:
        """Whether a match was made through a brand name, never a distillery name."""
        brand_key = (
            record_or_key
            if isinstance(record_or_key, str)
            else record_or_key.get("brand_key")
        )
        entry = next(
            (
                entry
                for entry in self._entries
                if entry.record["brand_key"] == brand_key
            ),
            None,
        )
        if entry is None:
            return False
        own_names = [entry.record.get("brand_ja"), entry.record.get("brand_en")]
        aliases = entry.record.get("aliases")
        if isinstance(aliases, list):
            own_names.extend(aliases)
        normalized_own_names = {
            normalized
            for name in own_names
            if isinstance(name, str)
            for normalized in normalized_brand_variants(name)
        }
        normalized_whiskey_names = {
            normalized
            for field in ("brand_ja", "brand_en")
            if isinstance(name := whiskey.get(field), str)
            for normalized in normalized_brand_variants(name)
        }
        return bool(normalized_own_names.intersection(normalized_whiskey_names))

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

    @staticmethod
    def _english_age_suffix(whiskey: Mapping[str, Any]) -> str:
        model_name_en = whiskey.get("name_en")
        model_brand_en = whiskey.get("brand_en")
        if isinstance(model_name_en, str) and isinstance(model_brand_en, str):
            name = _LEADING_THE_RE.sub("", model_name_en.strip())
            brand = _LEADING_THE_RE.sub("", model_brand_en.strip())
            if brand and name.casefold().startswith(brand.casefold()):
                match = _AGE_SUFFIX_RE.search(name[len(brand):])
                if match:
                    return f"{match.group(1)}年"
        return ""

    @classmethod
    def _rebuilt_name(
        cls, whiskey: Mapping[str, Any], catalog_brand_ja: str
    ) -> str | None:
        """Correct only the model's brand span; never discard an expression."""
        model_name = whiskey.get("name_ja")
        model_brand = whiskey.get("brand_ja")
        if not isinstance(model_name, str) or not isinstance(model_brand, str):
            return None
        name = model_name.strip()
        brand = model_brand.strip()
        if not name or not brand:
            return None
        # A name consisting only of the model's brand needs the English age fallback.
        if name == brand or unicodedata.normalize("NFKC", name) == unicodedata.normalize("NFKC", brand):
            suffix = cls._english_age_suffix(whiskey)
            return f"{catalog_brand_ja} {suffix}" if suffix else catalog_brand_ja
        # The official brand already appears outside the model's brand_ja, which therefore
        # names something else (a company or expression); replacing it would duplicate the brand.
        nfkc = functools.partial(unicodedata.normalize, "NFKC")
        if nfkc(catalog_brand_ja) in nfkc(name) and nfkc(catalog_brand_ja) not in nfkc(brand):
            return None
        for candidate_name, candidate_brand in (
            (name, brand),
            (unicodedata.normalize("NFKC", name), unicodedata.normalize("NFKC", brand)),
        ):
            start = candidate_name.find(candidate_brand)
            if start < 0:
                continue
            prefix = candidate_name[:start]
            if _LEADING_JA_ARTICLE_RE.search(prefix):
                prefix = _LEADING_JA_ARTICLE_RE.sub("", prefix)
            rebuilt = f"{prefix}{catalog_brand_ja}{candidate_name[start + len(candidate_brand):]}"
            return re.sub(r"\s{2,}", " ", rebuilt).strip()
        return None

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
                catalog_brand_ja = brand_matched.get("brand_ja")
                if (
                    isinstance(catalog_brand_ja, str)
                    and catalog_brand_ja.strip()
                    and self._brand_catalog.matches_brand_name(brand_matched, whiskey)
                ):
                    canonical_brand = catalog_brand_ja.strip()
                    if rebuilt_name := self._rebuilt_name(whiskey, canonical_brand):
                        if whiskey["name_ja"] != rebuilt_name:
                            candidate["ai_name_ja"] = whiskey["name_ja"]
                        candidate["brand_text"] = rebuilt_name
                        candidate["name_ja"] = rebuilt_name
                    candidate["brand_ja"] = canonical_brand
                distillery = brand_matched.get("distillery_ja")
                if distillery:
                    candidate["distillery_ja"] = distillery
            if "brand_key" not in candidate and "whiskey_id" not in candidate:
                candidate["confidence"] = min(
                    candidate["confidence"], UNMATCHED_BRAND_CONFIDENCE_CAP
                )
            candidates.append(candidate)
        return candidates
