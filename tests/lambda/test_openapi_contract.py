import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_openapi_excludes_removed_review_and_ranking_contracts():
    document = yaml.safe_load((ROOT / "swagger.yml").read_text())
    assert all("/reviews" not in path and "/ranking" not in path for path in document["paths"])
    assert all("Review" not in name for name in document["components"]["schemas"])


def test_openapi_keeps_search_and_drink_log_routes():
    document = yaml.safe_load((ROOT / "swagger.yml").read_text())
    expected = {
        "/api/whiskeys",
        "/api/whiskeys/search",
        "/api/whiskeys/suggest",
        "/api/whiskeys/search/suggest",
        "/api/drink-logs",
        "/api/drink-logs/upload-url",
        "/api/drink-logs/analyze",
        "/api/drink-logs/places",
        "/api/drink-logs/places/resolve",
        "/api/drink-logs/{id}",
    }
    assert expected <= set(document["paths"])
    assert document["paths"]["/api/whiskeys/search"]["get"]["security"] == []
    assert document["paths"]["/api/drink-logs"]["get"]["security"] == [{"bearerAuth": []}]


def test_openapi_has_no_unimplemented_drink_log_stubs():
    document = yaml.safe_load((ROOT / "swagger.yml").read_text())
    for path in document["paths"].values():
        for operation in path.values():
            if isinstance(operation, dict) and "responses" in operation:
                # YAML permits an unquoted 501 key, which PyYAML loads as int 501.
                assert all(str(status) != "501" for status in operation["responses"])
    assert "NotImplemented" not in document["components"].get("responses", {})


_UNDECLARED_HANDLER_STATUSES = {
    "drink-logs": {405},  # API Gateway accepts only methods configured by the CDK route.
    "places": {405, 404},  # API Gateway restricts routes to the two configured Places paths.
}


def _declared_statuses(document: dict, paths: set[str]) -> set[int]:
    return {
        int(status)
        for path in paths
        for operation in document["paths"][path].values()
        if isinstance(operation, dict)
        for status in operation.get("responses", {})
        if str(status).isdigit()
    }


def _literal_create_response_statuses(relative_path: str) -> set[int]:
    source = (ROOT / relative_path).read_text(encoding="utf-8")
    return {
        int(status)
        for status in re.findall(r"create_response\s*\(\s*(\d{3})\b", source)
    }


def _drink_log_route_statuses() -> set[int]:
    source = (ROOT / "lambda/drink-logs/index.py").read_text(encoding="utf-8")
    return {
        int(status)
        for status in re.findall(r"return\s+(\d{3})\s*,", source)
    }


def test_openapi_declares_handler_statuses() -> None:
    """Keep per-module OpenAPI responses aligned with handler status literals."""
    document = yaml.safe_load((ROOT / "swagger.yml").read_text())
    modules = {
        "drink-logs": {
            "source": "lambda/drink-logs/index.py",
            "paths": {"/api/drink-logs", "/api/drink-logs/upload-url", "/api/drink-logs/{id}"},
            "statuses": _drink_log_route_statuses,
        },
        "analyze": {
            "source": "lambda/drink-log-analyze/index.py",
            "paths": {"/api/drink-logs/analyze"},
            "statuses": lambda: _literal_create_response_statuses("lambda/drink-log-analyze/index.py"),
        },
        "places": {
            "source": "lambda/drink-log-analyze/places.py",
            "paths": {"/api/drink-logs/places", "/api/drink-logs/places/resolve"},
            "statuses": lambda: _literal_create_response_statuses("lambda/drink-log-analyze/places.py"),
        },
    }
    for name, module in modules.items():
        emitted = module["statuses"]() - _UNDECLARED_HANDLER_STATUSES.get(name, set())
        declared = _declared_statuses(document, module["paths"])
        assert emitted <= declared, (
            f"{module['source']}: emitted statuses {sorted(emitted)} are not all declared; "
            f"OpenAPI declares {sorted(declared)}"
        )


def test_timeline_page_limit_agrees_across_handler_openapi_and_reference():
    """The page limit is stated in three places; keep them from drifting apart."""
    handler = (ROOT / "lambda/drink-logs/index.py").read_text()
    handler_match = re.search(r"^MAX_PAGE_LIMIT\s*=\s*(\d+)", handler, flags=re.MULTILINE)
    assert handler_match, "lambda/drink-logs/index.py: MAX_PAGE_LIMIT was not found"
    expected = int(handler_match.group(1))

    document = yaml.safe_load((ROOT / "swagger.yml").read_text())
    assert document["components"]["parameters"]["Limit"]["schema"]["maximum"] == expected

    reference = (ROOT / "API_REFERENCE.md").read_text()
    reference_match = re.search(r"`limit`:\s*1[–-](\d+)", reference)
    assert reference_match, "API_REFERENCE.md: the limit range was not found"
    assert int(reference_match.group(1)) == expected


def test_api_reference_uses_id_tokens_and_has_no_unimplemented_health_route():
    reference = (ROOT / "API_REFERENCE.md").read_text()
    assert "ID token" in reference
    assert "access_token" not in reference
    assert "/health" not in reference
    assert "/api/reviews" not in reference
    assert "/api/whiskeys/ranking" not in reference
