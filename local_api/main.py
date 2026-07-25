"""Loopback-only FastAPI adapter for the API Gateway Lambda handlers."""

from __future__ import annotations

import argparse
import base64
import importlib.util
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool


ROOT = Path(__file__).resolve().parents[1]
COMMON_PYTHON = ROOT / "lambda" / "common" / "python"
LOCAL_USER_ID = "local-user"
LAMBDA_TIMEOUT_SECONDS = 30


def configure_local_environment() -> None:
    """Set an isolated local AWS environment before cold-importing handlers."""
    fixed = {
        "ENVIRONMENT": "local",
        "WHISKEYS_TABLE": "WhiskeySearch-local",
        "WHISKEY_SEARCH_TABLE": "WhiskeySearch-local",
        "REVIEWS_TABLE": "Reviews-local",
        "DRINKLOGS_TABLE": "DrinkLogs-local",
        "APP_STATE_TABLE": "AppState-local",
        "IMAGES_BUCKET": "whiskey-images-local",
        "PUBLIC_SCAN_MAX_PAGES": "5",
        "PUBLIC_SCAN_PAGE_SIZE": "250",
        "ALLOWED_ORIGINS": "http://localhost:3000",
        "AWS_ACCESS_KEY_ID": "minioadmin",
        "AWS_SECRET_ACCESS_KEY": "minioadmin",
        "AWS_REGION": "ap-northeast-1",
        "AWS_DEFAULT_REGION": "ap-northeast-1",
        "AWS_EC2_METADATA_DISABLED": "true",
        "AWS_ENDPOINT_URL_DYNAMODB": "http://127.0.0.1:8001",
        "AWS_ENDPOINT_URL_S3": "http://127.0.0.1:9000",
        "MOCK_AUTH": os.environ.get("MOCK_AUTH", "1"),
        "MOCK_AI": os.environ.get("MOCK_AI", "1"),
        "MOCK_PLACES": os.environ.get("MOCK_PLACES", "1"),
        "BEDROCK_MODEL_ID": "jp.amazon.nova-2-lite-v1:0",
        "BEDROCK_MODEL_ALLOWLIST": (
            "jp.amazon.nova-2-lite-v1:0,"
            "jp.anthropic.claude-haiku-4-5-20251001-v1:0"
        ),
        "PLACES_SECRET_NAME": "whiskey-places-local",
        "RECONCILE_AGE_HOURS": "48",
    }
    if os.environ.get("AWS_ENDPOINT_URL"):
        raise RuntimeError("AWS_ENDPOINT_URL must not be set; use service-specific endpoints")
    os.environ.update(fixed)
    for credential_source in (
        "AWS_PROFILE",
        "AWS_DEFAULT_PROFILE",
        "AWS_SESSION_TOKEN",
        "AWS_ROLE_ARN",
        "AWS_WEB_IDENTITY_TOKEN_FILE",
        "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
        "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    ):
        os.environ.pop(credential_source, None)
    if os.environ.get("MOCK_AUTH") == "1":
        os.environ["COGNITO_CLIENT_ID"] = "local-client"
        os.environ.setdefault("COGNITO_USER_POOL_ID", "ap-northeast-1_local")


def load_lambda_module(unique_name: str, relative_path: str) -> ModuleType:
    """Cold-import an index.py under a unique module name."""
    source_path = ROOT / relative_path
    import_paths = (COMMON_PYTHON, source_path.parent, source_path.parent / "python")
    for import_path in import_paths:
        path_text = str(import_path)
        if import_path.exists() and path_text not in sys.path:
            sys.path.insert(0, path_text)

    spec = importlib.util.spec_from_file_location(unique_name, source_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load Lambda handler from {source_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique_name] = module
    spec.loader.exec_module(module)
    return module


configure_local_environment()

WHISKEY_LIST = load_lambda_module(
    "local_lambda_whiskeys_list",
    "lambda/whiskeys-list/index.py",
)
WHISKEY_SEARCH = load_lambda_module(
    "local_lambda_whiskeys_search",
    "lambda/whiskeys-search/index.py",
)
REVIEWS = load_lambda_module(
    "local_lambda_reviews",
    "lambda/reviews/index.py",
)
DRINK_LOGS = load_lambda_module(
    "local_lambda_drink_logs",
    "lambda/drink-logs/index.py",
)
DRINK_LOG_ANALYZE = load_lambda_module(
    "local_lambda_drink_log_analyze",
    "lambda/drink-log-analyze/index.py",
)
DRINK_LOG_PLACES = load_lambda_module(
    "local_lambda_drink_log_places",
    "lambda/drink-log-analyze/places.py",
)


@dataclass
class LambdaContext:
    """Subset of the Lambda context used by this repository's handlers."""

    timeout_seconds: int = LAMBDA_TIMEOUT_SECONDS
    aws_request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    _deadline: float = field(init=False)

    def __post_init__(self) -> None:
        self._deadline = time.monotonic() + self.timeout_seconds

    def get_remaining_time_in_millis(self) -> int:
        return max(0, int((self._deadline - time.monotonic()) * 1000))


def _mock_claims() -> dict[str, str] | None:
    if os.environ.get("MOCK_AUTH") != "1":
        return None
    os.environ["COGNITO_CLIENT_ID"] = "local-client"
    return {
        "sub": LOCAL_USER_ID,
        "aud": "local-client",
        "token_use": "id",
    }


async def request_to_api_gateway_event(
    request: Request,
    path_parameters: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Convert an HTTP request to an API Gateway REST proxy event."""
    raw_body = await request.body()
    headers = dict(request.headers)
    request_id = headers.get("x-request-id", str(uuid.uuid4()))
    request_context: dict[str, Any] = {
        "requestId": request_id,
        "httpMethod": request.method,
        "resourcePath": request.scope.get("route").path,
        "identity": {"sourceIp": request.client.host if request.client else "127.0.0.1"},
    }
    claims = _mock_claims()
    if claims is not None:
        request_context["authorizer"] = {"claims": claims}

    query = dict(request.query_params)
    return {
        "resource": request.scope.get("route").path,
        "path": request.url.path,
        "httpMethod": request.method,
        "headers": headers,
        "multiValueHeaders": {
            key: request.headers.getlist(key) for key in request.headers.keys()
        },
        "queryStringParameters": query or None,
        "multiValueQueryStringParameters": {
            key: request.query_params.getlist(key) for key in request.query_params.keys()
        }
        or None,
        "pathParameters": path_parameters,
        "requestContext": request_context,
        "body": raw_body.decode("utf-8") if raw_body else None,
        "isBase64Encoded": False,
    }


def lambda_proxy_response(response: dict[str, Any]) -> Response:
    """Convert an API Gateway REST proxy response to a FastAPI response."""
    if not isinstance(response, dict) or "statusCode" not in response:
        raise RuntimeError("Lambda handler returned an invalid proxy response")
    body = response.get("body", "")
    if not isinstance(body, str):
        raise RuntimeError("Lambda proxy response body must be a string")
    content = base64.b64decode(body) if response.get("isBase64Encoded") else body.encode("utf-8")
    headers = {str(key): str(value) for key, value in (response.get("headers") or {}).items()}
    return Response(content=content, status_code=int(response["statusCode"]), headers=headers)


Handler = Callable[[dict[str, Any], LambdaContext], dict[str, Any]]


async def invoke(
    request: Request,
    handler: Handler,
    path_parameters: dict[str, str] | None = None,
) -> Response:
    event = await request_to_api_gateway_event(request, path_parameters)
    result = await run_in_threadpool(handler, event, LambdaContext())
    return lambda_proxy_response(result)


app = FastAPI(
    title="Whiskey Log Local API",
    version="2.2.0-local",
    redirect_slashes=False,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-Id"],
)


@app.get("/api/whiskeys")
async def list_whiskeys(request: Request) -> Response:
    return await invoke(request, WHISKEY_LIST.lambda_handler)


@app.get("/api/whiskeys/search")
@app.get("/api/whiskeys/suggest")
@app.get("/api/whiskeys/search/suggest")
@app.get("/api/whiskeys/ranking")
async def search_whiskeys(request: Request) -> Response:
    return await invoke(request, WHISKEY_SEARCH.lambda_handler)


@app.get("/api/reviews")
@app.post("/api/reviews")
async def reviews_collection(request: Request) -> Response:
    return await invoke(request, REVIEWS.lambda_handler)


@app.get("/api/reviews/public")
async def public_reviews(request: Request) -> Response:
    return await invoke(request, REVIEWS.lambda_handler)


@app.get("/api/reviews/{id}")
@app.put("/api/reviews/{id}")
@app.delete("/api/reviews/{id}")
async def review_item(id: str, request: Request) -> Response:
    return await invoke(request, REVIEWS.lambda_handler, {"id": id})


@app.post("/api/drink-logs/upload-url")
@app.post("/api/drink-logs")
@app.get("/api/drink-logs")
async def drink_logs_collection(request: Request) -> Response:
    return await invoke(request, DRINK_LOGS.lambda_handler)


@app.post("/api/drink-logs/analyze")
async def analyze_drink_log(request: Request) -> Response:
    return await invoke(request, DRINK_LOG_ANALYZE.lambda_handler)


@app.post("/api/drink-logs/places")
@app.post("/api/drink-logs/places/resolve")
async def drink_log_places(request: Request) -> Response:
    return await invoke(request, DRINK_LOG_PLACES.lambda_handler)


@app.get("/api/drink-logs/{id}")
@app.put("/api/drink-logs/{id}")
@app.delete("/api/drink-logs/{id}")
async def drink_log_item(id: str, request: Request) -> Response:
    return await invoke(request, DRINK_LOGS.lambda_handler, {"id": id})


def aggregate_local_rankings() -> dict[str, Any]:
    """Cold-import and directly invoke the ranking aggregator."""
    module = load_lambda_module(
        "local_lambda_ranking_aggregator",
        "lambda/ranking-aggregator/index.py",
    )
    return module.lambda_handler({"force": True}, LambdaContext(timeout_seconds=120))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local Lambda adapter utilities")
    parser.add_argument("--aggregate", action="store_true", help="Generate the local ranking cache")
    args = parser.parse_args(argv)
    if not args.aggregate:
        parser.error("specify --aggregate, or run the API with uvicorn")
    result = aggregate_local_rankings()
    print(result)
    return 0 if result.get("status") in {"published", "skipped"} else 1


if __name__ == "__main__":
    sys.exit(main())
