"""Read-only catalog and Drink Log tools for the trusted chat worker."""

import json
import logging
import sys
from pathlib import Path

# Deployment bundles these modules at the asset root. Local tests use the same sources.
SOURCE_ROOT = Path(__file__).resolve().parent.parent
for source in (SOURCE_ROOT / "drink-logs", SOURCE_ROOT / "whiskeys-search" / "python"):
    if source.is_dir():
        sys.path.insert(0, str(source))

from drink_log_store import DrinkLogStore
from whiskey_search_service import WhiskeySearchService
from whiskey_common.clients import get_dynamodb_resource, get_s3_client
from whiskey_common.decimal_utils import decimal_default


SCHEMAS = {tool["name"]: tool["config"]["inlineFunction"]["inputSchema"]
           for tool in json.loads(Path(__file__).with_name("tool_specs.json").read_text())}


def read_params(name, params):
    if name not in SCHEMAS or not isinstance(params, dict):
        raise ValueError("Unknown tool or invalid input")
    schema = SCHEMAS[name]
    if set(params) - set(schema["properties"]) or set(schema.get("required", [])) - set(params):
        raise ValueError("Invalid tool fields")
    result = dict(params)
    for key, value in result.items():
        prop = schema["properties"][key]
        if prop["type"] == "string":
            if not isinstance(value, str) or not value.strip() or len(value) > prop["maxLength"]:
                raise ValueError(f"Invalid {key}")
            result[key] = value.strip()
        elif isinstance(value, bool) or not isinstance(value, int) or not prop["minimum"] <= value <= prop["maximum"]:
            raise ValueError(f"Invalid {key}")
    return result


def public_fields(record, fields):
    result = {}
    truncated = False
    for field in fields:
        value = record.get(field)
        if isinstance(value, str) and len(value) > 200:
            value = value[:200]
            truncated = True
        result[field] = value
    if truncated:
        result["truncated"] = True
    return result


def bounded_result(records, partial):
    results = []
    for record in records:
        candidate = {"results": [*results, record], "partial": bool(partial)}
        # Python 3.11 Lambda escapes Unicode in response JSON. Bound that wire
        # representation so Japanese/emoji results also fit the worker's limit.
        if len(json.dumps(candidate, ensure_ascii=True, default=decimal_default).encode()) > 18000:
            partial = True
            break
        results.append(record)
    return {"results": results, "partial": bool(partial)}


class ChatTools:
    """Expose existing read services with a server-owned user principal."""

    def __init__(self, dynamodb, s3):
        self.search = WhiskeySearchService(dynamodb)
        self.logs = DrinkLogStore.from_environment(dynamodb, s3)

    def handle(self, event):
        try:
            user_id = (event.get("principal") or {}).get("user_id")
            if not isinstance(user_id, str) or not user_id:
                raise ValueError("Trusted principal required")
            name = event.get("name")
            params = read_params(name, event.get("params"))
            if name == "search_whiskeys":
                records, token = self.search.search_whiskeys(params["query"], limit=5, max_pages=4)
                records = [public_fields(record, ("id", "name", "region", "type", "age")) for record in records]
            else:
                filters = {"brand": params["brand"]} if name == "search_drink_logs" else {}
                records, token = self.logs.get_timeline(user_id, params.get("limit", 10), None, filters)
                records = [public_fields({**record, "store": (record.get("store") or {}).get("name")},
                    ("id", "brand_text", "serving_style", "store", "datetime", "notes", "rating")) for record in records]
            return bounded_result(records, token)
        except (ValueError, TypeError, AttributeError):
            return {"error": "Invalid tool input"}


def lambda_handler(event, context):
    """Execute one worker-supplied tool invocation; no public API integration."""
    try:
        return ChatTools(get_dynamodb_resource(), get_s3_client()).handle(event)
    except Exception as exc:
        logging.getLogger(__name__).error("Chat tool failed: %s", type(exc).__name__)
        raise RuntimeError("Chat tool execution failed") from None
