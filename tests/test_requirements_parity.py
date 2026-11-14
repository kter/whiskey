"""Test pins must match the Lambda runtime pins.

The Lambdas run with the versions in ``lambda/*/requirements.txt``; the tests
install ``requirements-dev.txt`` (and the local API ``local_api/requirements.txt``).
If a package appears on both sides, the versions must be identical, otherwise
the suite exercises a different library than production. Dependabot bumps each
directory's file, so this catches a bump that landed on only one side.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAMBDA_REQUIREMENTS = sorted(ROOT.glob("lambda/*/requirements.txt"))
TEST_REQUIREMENTS = [ROOT / "requirements-dev.txt", ROOT / "local_api" / "requirements.txt"]

_PIN = re.compile(r"^([A-Za-z0-9_.\-]+)(\[[^\]]*\])?==([^\s;#]+)")


def _pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in path.read_text().splitlines():
        match = _PIN.match(line.strip())
        if match:
            name = re.sub(r"[-_.]+", "-", match.group(1)).lower()
            pins[name] = match.group(3)
    return pins


def test_lambda_requirements_are_found():
    assert LAMBDA_REQUIREMENTS, "no lambda/*/requirements.txt found"


@pytest.mark.parametrize("lambda_req", LAMBDA_REQUIREMENTS, ids=lambda p: p.parent.name)
@pytest.mark.parametrize("test_req", TEST_REQUIREMENTS, ids=lambda p: str(p.relative_to(ROOT)))
def test_test_pins_match_lambda_runtime(lambda_req: Path, test_req: Path):
    runtime = _pins(lambda_req)
    tested = _pins(test_req)
    mismatches = {
        name: (version, tested[name])
        for name, version in runtime.items()
        if name in tested and tested[name] != version
    }
    assert not mismatches, (
        f"{test_req.relative_to(ROOT)} and {lambda_req.relative_to(ROOT)} pin different versions "
        f"(runtime, tested): {mismatches}. Bump both sides together."
    )
