"""Read-only name search service for the WhiskeySearch table."""

import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from boto3.dynamodb.conditions import Attr

try:
    from whiskey_common.clients import get_dynamodb_resource
    from whiskey_common.logger import get_logger
    from whiskey_common.normalize import normalize_text
    from whiskey_common.scan_utils import decode_next_token, scan_all_pages
except ModuleNotFoundError as exc:
    if exc.name != "whiskey_common":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "common" / "python"))
    from whiskey_common.clients import get_dynamodb_resource
    from whiskey_common.logger import get_logger
    from whiskey_common.normalize import normalize_text
    from whiskey_common.scan_utils import decode_next_token, scan_all_pages


class WhiskeySearchService:
    """Perform bounded, paginated name-only searches."""

    def __init__(self, dynamodb: Any | None = None):
        environment = os.getenv("ENVIRONMENT", "dev")
        self.whiskey_table_name = os.getenv("WHISKEY_SEARCH_TABLE", f"WhiskeySearch-{environment}")
        self.logger = get_logger(function_name="whiskey-search-service")
        self.dynamodb = dynamodb or get_dynamodb_resource()
        self._whiskey_table = None

    @property
    def whiskey_table(self):
        if self._whiskey_table is None:
            self._whiskey_table = self.dynamodb.Table(self.whiskey_table_name)
        return self._whiskey_table

    def _serialize_item(self, item: Any) -> Any:
        if isinstance(item, dict):
            return {key: self._serialize_item(value) for key, value in item.items()}
        if isinstance(item, list):
            return [self._serialize_item(value) for value in item]
        if isinstance(item, Decimal):
            return float(item) if item % 1 else int(item)
        return item

    def search_whiskeys(
        self,
        query: str,
        *,
        limit: int = 50,
        next_token: str | None = None,
        max_pages: int | None = None,
    ) -> tuple[list[dict], str | None]:
        """Search names by partial match and return a continuation token."""
        start_key = decode_next_token(next_token)
        scan_kwargs: dict[str, Any] = {"Limit": limit}
        if start_key:
            scan_kwargs["ExclusiveStartKey"] = start_key
        normalized_query = normalize_text(query)
        if query:
            scan_kwargs["FilterExpression"] = (
                Attr("name").contains(query) | Attr("normalized_name").contains(normalized_query)
            )
        items, continuation = scan_all_pages(
            self.whiskey_table,
            max_pages=max_pages or int(os.environ.get("PUBLIC_SCAN_MAX_PAGES", "1")),
            **scan_kwargs,
        )
        return [self._serialize_item(item) for item in items], continuation

    def get_whiskey_by_id(self, whiskey_id: str) -> dict | None:
        response = self.whiskey_table.get_item(Key={"id": whiskey_id})
        item = response.get("Item")
        return self._serialize_item(item) if item else None
