"""Whiskey list Lambda function."""

import os
import sys
from pathlib import Path
from typing import Any

try:
    from whiskey_common.clients import get_dynamodb_resource
    from whiskey_common.logger import extract_correlation_id, get_logger
    from whiskey_common.responses import create_response, get_cors_headers
except ModuleNotFoundError as exc:
    if exc.name != "whiskey_common":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common" / "python"))
    from whiskey_common.clients import get_dynamodb_resource
    from whiskey_common.logger import extract_correlation_id, get_logger
    from whiskey_common.responses import create_response, get_cors_headers


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_id = (
        getattr(context, "aws_request_id", None)
        or (event.get("requestContext") or {}).get("requestId")
        or "unknown"
    )
    logger = get_logger("whiskeys-list", correlation_id=extract_correlation_id(event) or request_id)
    headers = get_cors_headers(event)
    logger.log_api_request(
        method=event.get("httpMethod", "UNKNOWN"),
        path=event.get("path", "UNKNOWN"),
        query_params=event.get("queryStringParameters"),
    )
    try:
        table = get_dynamodb_resource().Table(os.environ["WHISKEYS_TABLE"])
        response = table.scan()
        whiskeys = [
            {
                "id": item["id"],
                "name": item.get("name_en", item.get("name", "")),
                "distillery": item.get("distillery_en", item.get("distillery", "")),
                "created_at": item.get("created_at", ""),
                "updated_at": item.get("updated_at", ""),
            }
            for item in response.get("Items", [])
        ]
        whiskeys.sort(key=lambda whiskey: whiskey["name"])
        return create_response(200, {"whiskeys": whiskeys, "count": len(whiskeys)}, headers)
    except Exception as exc:
        logger.error("Unhandled whiskey list error", error=str(exc), request_id=request_id)
        return create_response(
            500,
            {"error": "Internal server error", "request_id": request_id},
            headers,
        )
