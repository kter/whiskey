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


def test_api_reference_uses_id_tokens_and_has_no_unimplemented_health_route():
    reference = (ROOT / "API_REFERENCE.md").read_text()
    assert "ID token" in reference
    assert "access_token" not in reference
    assert "/health" not in reference
    assert "/api/reviews" not in reference
    assert "/api/whiskeys/ranking" not in reference
