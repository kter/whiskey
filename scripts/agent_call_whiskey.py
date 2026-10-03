import boto3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lambda" / "whiskeys-search" / "python"))
from whiskey_search_service import WhiskeySearchService
from dataclasses import dataclass

from whiskey_common.clients import get_dynamodb_resource, get_s3_client

sys.path.insert(0, str(ROOT / "lambda" / "drink-logs"))
import drink_log_store


@dataclass(frozen=True)
class Principal:
    user_id: str


MAX_STEPS = 5
client = boto3.client("bedrock-runtime", region_name="ap-northeast-1")
tools = [
    {
        "toolSpec": {
            "name": "search_whiskeys",
            "description": "ウイスキーを名前で検索する",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "検索するウイスキー名",
                        }
                    },
                    "required": ["query"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "get_drink_logs",
            "description": "飲酒記録を取得する",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {"query": {}},
                    "required": ["query"],
                }
            },
        }
    },
]
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


def run_agent(message: str, principal: Principal):
    messages = [{"role": "user", "content": [{"text": message}]}]
    for step in range(MAX_STEPS):
        response = client.converse(
            modelId="jp.amazon.nova-2-lite-v1:0",
            system=system,
            messages=messages,
            toolConfig={
                "tools": tools,
            },
        )
        assistant_message = response["output"]["message"]
        messages.append(assistant_message)

        print("step:", step)
        print("stopReason:", response["stopReason"])

        if response["stopReason"] == "end_turn":
            print(assistant_message["content"])
            break

        elif response["stopReason"] == "tool_use":
            tool_results = []
            for block in assistant_message["content"]:
                if "toolUse" in block:
                    tool_use = block["toolUse"]
                    print("tool:", tool_use["name"])
                    print("input:", tool_use["input"])
                    if tool_use["name"] == "search_whiskeys":
                        query = tool_use["input"]["query"]
                        result = search_whiskeys(query)
                        tool_results.append(
                            {
                                "toolResult": {
                                    "toolUseId": tool_use["toolUseId"],
                                    "content": [{"json": {"results": result}}],
                                }
                            }
                        )
                    elif tool_use["name"] == "get_drink_logs":
                        principal = Principal(
                            user_id="67f45ae8-9091-70df-7d98-237f59f7df1a"
                        )
                        result = get_drink_logs(principal)
                        tool_results.append(
                            {
                                "toolResult": {
                                    "toolUseId": tool_use["toolUseId"],
                                    "content": [{"json": {"results": result}}],
                                }
                            }
                        )
                    else:
                        tool_results.append(
                            {
                                "toolResult": {
                                    "toolUseId": tool_use["toolUseId"],
                                    "content": [{"json": {"results": []}}],
                                }
                            }
                        )
        else:
            print("unknown stop reason")
            break
        messages.append({"role": "user", "content": tool_results})
    else:
        print("Exceed MAX_STEP count")


def get_drink_logs(principal: Principal, limit: int = 10):
    dynamodb = get_dynamodb_resource()
    s3 = get_s3_client()
    store = drink_log_store.DrinkLogStore.from_environment(dynamodb, s3)
    records, _ = store.get_timeline(
        principal.user_id,
        limit,
        None,
        {},
    )
    return [
        {
            "id": record.get("id"),
            "brand_text": record.get("brand_text"),
            "serving_style": record.get("serving_style"),
            "store": record.get("store", {}).get("name"),
            "datetime": record.get("datetime"),
            "notes": record.get("notes"),
            "rating": record.get("rating"),
        }
        for record in records
    ]


def search_drink_logs(principal: Principal, brand: str | None = None, limit: int = 10):
    dynamodb = get_dynamodb_resource()
    s3 = get_s3_client()
    filters = {}
    if brand:
        filters["brand"] = brand

    store = drink_log_store.DrinkLogStore.from_environment(dynamodb, s3)
    records, _ = store.get_timeline(
        principal.user_id,
        limit,
        None,
        filters,
    )
    return [
        {
            "id": record.get("id"),
            "brand_text": record.get("brand_text"),
            "serving_style": record.get("serving_style"),
            "store": record.get("store", {}).get("name"),
            "datetime": record.get("datetime"),
            "notes": record.get("notes"),
            "rating": record.get("rating"),
        }
        for record in records
    ]


def search_whiskeys(query):
    service = WhiskeySearchService()

    items, _ = service.search_whiskeys(
        query,
        limit=5,
        max_pages=1,
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


# principal = Principal(user_id="dumy-user")
# run_agent("タリスカーを探して", principal)

# principal2 = Principal(user_id="67f45ae8-9091-70df-7d98-237f59f7df1a")
# print(get_drink_logs(principal2))

principal3 = Principal(user_id="67f45ae8-9091-70df-7d98-237f59f7df1a")
run_agent("最近飲んだアランを教えて", principal3)
