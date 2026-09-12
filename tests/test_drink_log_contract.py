import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCE_OF_TRUTH_PATH = "infra/lib/whiskey-infra-stack.ts"

_NUMERIC_VALUE = (
    r"(?P<value>(?:(?P<quote>['\"])[\d_]+(?P=quote)|[\d_]+))"
    r"(?!\s*(?:[\d_*/+\-%@&|^<>=!.?:~(\[]|"
    r"\b(?:and|as|else|for|if|in|instanceof|is|not|or|satisfies)\b))"
)


def _environment_default(name: str) -> str:
    return (
        rf"os\s*\.\s*environ\s*\.\s*get\s*\(\s*['\"]{name}['\"]\s*,\s*"
        rf"{_NUMERIC_VALUE}\s*\)"
    )


def _assignment(name: str) -> str:
    return rf"\b{name}\s*(?::[^=\n]+)?=\s*{_NUMERIC_VALUE}"


def _object_property(name: str) -> str:
    return rf"\b{name}\s*:\s*{_NUMERIC_VALUE}"


def _extract_numbers(relative_path: str, pattern: str) -> list[int]:
    source = (ROOT / relative_path).read_text(encoding="utf-8")
    matches = list(re.finditer(pattern, source, flags=re.MULTILINE))

    assert matches, f"{relative_path}: constant was not found"
    return [
        int(match.group("value").strip("'\"").replace("_", ""))
        for match in matches
    ]


def _source_of_truth_value(name: str) -> int:
    values = _extract_numbers(SOURCE_OF_TRUTH_PATH, _object_property(name))
    expected = values[0]
    assert all(value == expected for value in values), (
        f"{SOURCE_OF_TRUTH_PATH}: {name} values disagree: {values}"
    )
    return expected


@pytest.mark.parametrize(
    ("constant_name", "relative_path", "pattern"),
    [
        (
            "UPLOAD_MAX_BYTES",
            "lambda/drink-logs/drink_log_store.py",
            _environment_default("UPLOAD_MAX_BYTES"),
        ),
        (
            "UPLOAD_MAX_BYTES",
            "lambda/drink-log-analyze/index.py",
            _environment_default("UPLOAD_MAX_BYTES"),
        ),
        (
            "UPLOAD_MAX_BYTES",
            "frontend/utils/imageResize.ts",
            _assignment("MAX_OUTPUT_SIZE"),
        ),
        (
            "UPLOAD_MAX_BYTES",
            "scripts/eval/run_brand_eval.py",
            _assignment("UPLOAD_MAX_BYTES"),
        ),
        (
            "UPLOAD_MAX_BYTES",
            "scripts/eval/import_real_photos.py",
            _assignment("OUTPUT_MAX_BYTES"),
        ),
        (
            "IMAGE_MAX_BYTES",
            "lambda/drink-logs/drink_log_store.py",
            _environment_default("IMAGE_MAX_BYTES"),
        ),
        (
            "IMAGE_MAX_BYTES",
            "lambda/drink-log-analyze/index.py",
            _environment_default("IMAGE_MAX_BYTES"),
        ),
    ],
)
def test_size_limits_match(
    constant_name: str, relative_path: str, pattern: str
) -> None:
    expected = _source_of_truth_value(constant_name)
    values = _extract_numbers(relative_path, pattern)
    assert all(value == expected for value in values), (
        f"{relative_path}: {constant_name} expected {expected}, found {values}"
    )


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
