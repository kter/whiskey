import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_UPLOAD_MAX_BYTES = 3_670_016
EXPECTED_IMAGE_MAX_BYTES = 1_572_864


def _environment_default(name: str) -> str:
    return (
        rf"os\s*\.\s*environ\s*\.\s*get\s*\(\s*['\"]{name}['\"]\s*,\s*"
        rf"(?P<value>['\"]?[\d_]+['\"]?)\s*\)"
    )


def _assignment(name: str) -> str:
    return rf"\b{name}\s*(?::[^=\n]+)?=\s*(?P<value>['\"]?[\d_]+['\"]?)"


def _object_property(name: str) -> str:
    return rf"\b{name}\s*:\s*(?P<value>['\"]?[\d_]+['\"]?)"


def _extract_numbers(relative_path: str, pattern: str, count: int) -> list[int]:
    source = (ROOT / relative_path).read_text(encoding="utf-8")
    matches = list(re.finditer(pattern, source, flags=re.MULTILINE))

    assert matches, f"{relative_path}: constant was not found"
    assert len(matches) == count, (
        f"{relative_path}: expected {count} matching constant(s), found {len(matches)}"
    )
    return [
        int(match.group("value").strip("'\"").replace("_", ""))
        for match in matches
    ]


@pytest.mark.parametrize(
    ("relative_path", "pattern", "count"),
    [
        ("lambda/drink-logs/index.py", _environment_default("UPLOAD_MAX_BYTES"), 2),
        (
            "lambda/drink-log-analyze/index.py",
            _environment_default("UPLOAD_MAX_BYTES"),
            1,
        ),
        (
            "infra/lib/whiskey-infra-stack.ts",
            _object_property("UPLOAD_MAX_BYTES"),
            2,
        ),
        ("frontend/utils/imageResize.ts", _assignment("MAX_OUTPUT_SIZE"), 1),
        ("scripts/eval/run_brand_eval.py", _assignment("UPLOAD_MAX_BYTES"), 1),
        (
            "scripts/eval/import_real_photos.py",
            _assignment("OUTPUT_MAX_BYTES"),
            1,
        ),
    ],
)
def test_upload_size_limits_match(
    relative_path: str, pattern: str, count: int
) -> None:
    assert _extract_numbers(relative_path, pattern, count) == [
        EXPECTED_UPLOAD_MAX_BYTES
    ] * count


@pytest.mark.parametrize(
    ("relative_path", "pattern", "count"),
    [
        ("lambda/drink-logs/index.py", _environment_default("IMAGE_MAX_BYTES"), 1),
        (
            "lambda/drink-log-analyze/index.py",
            _environment_default("IMAGE_MAX_BYTES"),
            1,
        ),
        (
            "infra/lib/whiskey-infra-stack.ts",
            _object_property("IMAGE_MAX_BYTES"),
            2,
        ),
    ],
)
def test_normalized_image_size_limits_match(
    relative_path: str, pattern: str, count: int
) -> None:
    assert _extract_numbers(relative_path, pattern, count) == [
        EXPECTED_IMAGE_MAX_BYTES
    ] * count


def test_backend_store_name_placeholder_is_known_to_frontend() -> None:
    backend_path = "lambda/drink-log-analyze/places.py"
    backend_source = (ROOT / backend_path).read_text(encoding="utf-8")
    placeholder_match = re.search(
        r"^\s*PLACEHOLDER_NAME\s*=\s*(?P<quote>['\"])(?P<value>.*?)\1",
        backend_source,
        flags=re.MULTILINE,
    )
    assert placeholder_match, f"{backend_path}: PLACEHOLDER_NAME was not found"

    frontend_path = "frontend/utils/drinkLogs.ts"
    frontend_source = (ROOT / frontend_path).read_text(encoding="utf-8")
    placeholders_match = re.search(
        r"\bSTORE_NAME_PLACEHOLDERS\s*=\s*\[(?P<values>.*?)\]",
        frontend_source,
        flags=re.DOTALL,
    )
    assert placeholders_match, f"{frontend_path}: STORE_NAME_PLACEHOLDERS was not found"
    frontend_placeholders = {
        match.group("value")
        for match in re.finditer(
            r"(?P<quote>['\"])(?P<value>.*?)\1",
            placeholders_match.group("values"),
        )
    }

    assert placeholder_match.group("value") in frontend_placeholders
