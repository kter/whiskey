"""Contract checks for the local FastAPI-to-Lambda adapter."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


pytest.importorskip("fastapi")


ROOT = Path(__file__).resolve().parents[2]


def test_adapter_cold_imports_all_handlers_from_repository_root():
    environment = os.environ.copy()
    environment.pop("AWS_PROFILE", None)
    environment.pop("AWS_DEFAULT_PROFILE", None)
    environment.pop("AWS_ENDPOINT_URL", None)
    environment["MOCK_AUTH"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import local_api.main as main; "
                "assert callable(main.WHISKEY_LIST.lambda_handler); "
                "assert callable(main.WHISKEY_SEARCH.lambda_handler); "
                "assert callable(main.DRINK_LOGS.lambda_handler); "
                "assert callable(main.DRINK_LOG_ANALYZE.lambda_handler); "
                "assert callable(main.DRINK_LOG_PLACES.lambda_handler)"
            ),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_fastapi_routes_mirror_swagger_contract():
    from local_api.main import app

    with (ROOT / "swagger.yml").open(encoding="utf-8") as swagger_file:
        document = yaml.safe_load(swagger_file)
    expected = {
        (path, method.upper())
        for path, operations in document["paths"].items()
        for method in operations
        if method.lower() in {"get", "post", "put", "delete", "patch"}
    }
    actual = {
        (route.path, method)
        for route in app.routes
        if route.path.startswith("/api/")
        for method in route.methods
        if method != "HEAD"
    }
    assert actual == expected


def test_lambda_context_uses_a_deadline():
    from local_api.main import LambdaContext

    context = LambdaContext(timeout_seconds=2)
    remaining = context.get_remaining_time_in_millis()
    assert 0 < remaining <= 2000
    assert context.aws_request_id
