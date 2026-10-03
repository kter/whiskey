import boto3
import sys
from pathlib import Path
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lambda" / "whiskeys-search" / "python"))
from whiskey_search_service import WhiskeySearchService
from dataclasses import dataclass
from typing import Any, Protocol

sys.path.insert(0, str(ROOT / "lambda" / "common" / "python"))
sys.path.insert(0, str(ROOT / "lambda" / "whiskeys-search" / "python"))
sys.path.insert(0, str(ROOT / "lambda" / "drink-logs"))

from whiskey_common.clients import get_dynamodb_resource, get_s3_client

sys.path.insert(0, str(ROOT / "lambda" / "drink-logs"))
import drink_log_store


@dataclass(frozen=True)
class Principal:
    user_id: str


MAX_STEPS = 5
DEFAULT_LIMIT = 10
MAX_LIMIT = 20
client = boto3.client("bedrock-runtime", region_name="ap-northeast-1")


class Tool(Protocol):
    name: str
    description: str
    input_schema: dict[str, Any]

    def run(
        self, principal: Principal, params: dict[str, Any]
    ) -> list[dict[str, Any]]: ...


def to_spec(tool: Tool) -> dict[str, Any]:
    """Tool から Converse API の toolSpec を組み立てる。

    Converse 特有の入れ子（toolSpec > inputSchema > json）はここに閉じ込める。
    各 Tool クラスは API の形を気にせず、名前・説明・JSON Schema だけを書けばよい。
    """
    return {
        "toolSpec": {
            "name": tool.name,
            "description": tool.description,
            "inputSchema": {"json": tool.input_schema},
        }
    }


class SearchWhiskeys:
    name = "search_whiskeys"
    description = "ウイスキーを名前で検索する"
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "検索するウイスキー名"},
        },
        "required": ["query"],
    }

    def run(self, principal: Principal, params: dict[str, Any]) -> list[dict[str, Any]]:
        items, next_token = WhiskeySearchService().search_whiskeys(
            read_text(params, "query"), limit=5, max_pages=1
        )
        return [
            {
                "name": item.get("name"),
                "distillery": item.get("distillery"),
                "region": item.get("region"),
                "type": item.get("type"),
                "age": item.get("age"),
            }
            for item in items
        ]


class GetDrinkLogs:
    name = "get_drink_logs"
    description = "現在のユーザーの最近の飲酒記録を取得する"
    input_schema = {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "取得する最大件数",
                "minimum": 1,
                "maximum": MAX_LIMIT,
            },
        },
    }

    def run(self, principal: Principal, params: dict[str, Any]) -> list[dict[str, Any]]:
        return fetch_drink_logs(principal, read_limit(params), filters={})


def fetch_drink_logs(
    principal: Principal, limit: int, filters: dict[str, str]
) -> list[dict[str, Any]]:
    store = drink_log_store.DrinkLogStore.from_environment(
        get_dynamodb_resource(), get_s3_client()
    )
    records, next_token = store.get_timeline(principal.user_id, limit, None, filters)
    return [to_public_drink_log(record) for record in records]


def to_public_drink_log(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record.get("id"),
        "brand_text": record.get("brand_text"),
        "serving_style": record.get("serving_style"),
        "store": (record.get("store") or {}).get("name"),
        "datetime": record.get("datetime"),
        "notes": record.get("notes"),
        "rating": record.get("rating"),
    }


class SearchDrinkLogs:
    name = "search_drink_logs"
    description = "現在のユーザーの飲酒履歴を銘柄名で検索する"
    input_schema = {
        "type": "object",
        "properties": {
            "brand": {"type": "string", "description": "検索するウイスキーの銘柄名"},
            "limit": {
                "type": "integer",
                "description": "取得する最大件数",
                "minimum": 1,
                "maximum": MAX_LIMIT,
            },
        },
        "required": ["brand"],
    }

    def run(self, principal: Principal, params: dict[str, Any]) -> list[dict[str, Any]]:
        return fetch_drink_logs(
            principal, read_limit(params), filters={"brand": read_text(params, "brand")}
        )


TOOLS: dict[str, Tool] = {
    tool.name: tool for tool in (SearchWhiskeys(), GetDrinkLogs(), SearchDrinkLogs())
}

TOOL_CONFIG = {"tools": [to_spec(tool) for tool in TOOLS.values()]}
system = [
    {
        "text": (
            "あなたはWhiskey Logのアシスタントです。"
            "検索結果について回答するときは、Tool Resultに明示的に存在する"
            "フィールドだけを根拠として回答してください。"
            "あなた自身の事前知識を検索結果の説明に使用してはいけません。"
            "Tool Resultにない情報を尋ねられた場合は、"
            "「検索結果にはその情報がありません」と回答してください。"
        )
    }
]


def run_agent(message: str, principal: Principal) -> None:
    messages: list[dict[str, Any]] = [{"role": "user", "content": [{"text": message}]}]

    for step in range(MAX_STEPS):
        response = client.converse(
            modelId="jp.amazon.nova-2-lite-v1:0",
            system=system,
            messages=messages,
            toolConfig=TOOL_CONFIG,
        )
        assistant_message = response["output"]["message"]
        messages.append(assistant_message)
        stop_reason = response["stopReason"]
        print("step:", step)
        print("stopReason:", stop_reason)

        if stop_reason == "end_turn":
            print(assistant_message["content"])
            return

        if stop_reason != "tool_use":
            print(assistant_message["content"])
            return

        tool_results = []
        for block in assistant_message["content"]:
            if "toolUse" in block:
                tool_use = block["toolUse"]
                print("tool:", tool_use["name"])
                print("input:", tool_use["input"])
                tool_results.append(execute_tool(principal, block["toolUse"]))
        messages.append({"role": "user", "content": tool_results})
    print("Exceed MAX_STEP count")


def error_result(tool_use_id: str, message: str) -> dict[str, Any]:
    return {
        "toolResult": {
            "toolUseId": tool_use_id,
            "content": [{"text": message}],
            "status": "error",
        }
    }


class ToolInputError(Exception):
    """ """


def read_text(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolInputError(f"{key} is required")
    return value.strip()


def read_limit(params: dict[str, Any]) -> int:
    value = params.get("limit", DEFAULT_LIMIT)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolInputError("limit must be an integer")
    return max(1, min(value, MAX_LIMIT))


def execute_tool(principal: Principal, tool_use: dict[str, Any]) -> dict[str, Any]:
    tool_use_id = tool_use["toolUseId"]
    tool = TOOLS.get(tool_use["name"])
    if tool is None:
        return error_result(tool_use_id, f"unknown tool: {tool_use['name']}")

    try:
        results = tool.run(principal, tool_use.get("input") or {})
    except ToolInputError as e:
        return error_result(tool_use_id, str(e))
    except Exception:
        traceback.print_exc()
        return error_result(tool_use_id, "tool execution failed")

    return success_result(tool_use_id, results)


def success_result(tool_use_id: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "toolResult": {
            "toolUseId": tool_use_id,
            "content": [{"json": {"results": results}}],
        }
    }


# principal = Principal(user_id="dumy-user")
# run_agent("タリスカーを探して", principal)

# principal2 = Principal(user_id="67f45ae8-9091-70df-7d98-237f59f7df1a")
# print(get_drink_logs(principal2))

# principal3 = Principal(user_id="67f45ae8-9091-70df-7d98-237f59f7df1a")
# run_agent("最近飲んだアランを教えて", principal3)

principal4 = Principal(user_id="67f45ae8-9091-70df-7d98-237f59f7df1a")
# print(search_drink_logs(principal4, brand="アラン", limit=10))
run_agent("最近飲んだアランを教えて", principal4)
run_agent("最近飲んだウイスキーを3件 を教えて", principal4)
run_agent("タリスカーを探して", principal4)
