from pathlib import Path

import yaml

from tests.lambda_module_loader import load_lambda_module


ROOT = Path(__file__).resolve().parents[2]
reviews = load_lambda_module("reviews_openapi_contract", "lambda/reviews/index.py")


def _schema(document, name):
    return document["components"]["schemas"][name]


def test_openapi_review_inputs_match_lambda_contract():
    document = yaml.safe_load((ROOT / "swagger.yml").read_text())
    create = _schema(document, "ReviewCreateInput")
    update = _schema(document, "ReviewUpdateInput")
    serving_style = _schema(document, "ServingStyle")

    assert set(serving_style["enum"]) == reviews.SERVING_STYLES
    assert set(create["required"]) == {"whiskey_id", "rating", "date"}
    assert set(create["properties"]) == reviews.CREATE_FIELDS
    assert set(update["properties"]) == reviews.UPDATE_FIELDS
    assert "whiskey_id" not in update["properties"]
    assert "image_url" not in create["properties"]
    assert create["additionalProperties"] is False
    assert update["additionalProperties"] is False


def test_openapi_has_separate_public_and_owned_review_routes():
    document = yaml.safe_load((ROOT / "swagger.yml").read_text())
    assert set(document["paths"]["/api/reviews/{id}"]) >= {"get", "put", "delete", "parameters"}
    assert document["paths"]["/api/reviews/public"]["get"]["security"] == []
    private_get = document["paths"]["/api/reviews"]["get"]
    assert private_get["security"] == [{"bearerAuth": []}]
    assert {parameter["$ref"] for parameter in private_get["parameters"]} == {
        "#/components/parameters/Limit",
        "#/components/parameters/NextToken",
    }


def test_api_reference_uses_id_tokens_and_has_no_unimplemented_health_route():
    reference = (ROOT / "API_REFERENCE.md").read_text()
    assert "ID token" in reference
    assert "access_token" not in reference
    assert "/health" not in reference
    assert "?public=true" in reference and "not supported" in reference
