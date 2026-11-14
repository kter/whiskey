"""Tests must run against the same library versions the Lambda functions bundle.

Dependabot only bumps the test-side requirement files, so a bump that is not
mirrored into ``lambda/*/requirements.txt`` would silently test a different
version than production runs. This guard fails when the shared pins drift.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Packages that both the test environment and the bundled Lambda runtime install.
SHARED_PACKAGES = ("boto3", "botocore", "pillow", "pyjwt", "requests")

RUNTIME_FILES = (
    "lambda/drink-logs/requirements.txt",
    "lambda/drink-log-analyze/requirements.txt",
)
TEST_FILES = (
    "requirements-dev.txt",
    "local_api/requirements.txt",
)

_PIN = re.compile(r"^\s*([A-Za-z0-9_.-]+)(?:\[[^\]]*\])?\s*==\s*([^\s#;]+)")


def _pins(relative_path: str) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in (REPO_ROOT / relative_path).read_text(encoding="utf-8").splitlines():
        match = _PIN.match(line)
        if match:
            pins[match.group(1).lower().replace("_", "-")] = match.group(2)
    return pins


def test_runtime_files_pin_identical_versions():
    first, *rest = (_pins(path) for path in RUNTIME_FILES)
    for package in SHARED_PACKAGES:
        assert package in first, f"{RUNTIME_FILES[0]} must pin {package}"
        for path, pins in zip(RUNTIME_FILES[1:], rest):
            assert pins.get(package) == first[package], (
                f"{path} pins {package}=={pins.get(package)}, "
                f"{RUNTIME_FILES[0]} pins {first[package]}"
            )


@pytest.mark.parametrize("test_file", TEST_FILES)
def test_test_requirements_match_lambda_runtime(test_file):
    runtime = _pins(RUNTIME_FILES[0])
    pins = _pins(test_file)
    for package in SHARED_PACKAGES:
        assert pins.get(package) == runtime[package], (
            f"{test_file} pins {package}=={pins.get(package)}, "
            f"but the Lambda runtime bundles {runtime[package]}"
        )
