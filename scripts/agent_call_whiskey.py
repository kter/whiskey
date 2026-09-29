import boto3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lambda" / "whiskeys-search" / "python"))
from whiskey_search_service import WhiskeySearchService
from dataclasses import dataclass


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
    }
]
system = [
    {
        "text": (
            "あなたはWhiskey Logのアシスタントです。"
            "ウイスキー検索に関する回答では、Toolから取得した情報のみを事実として使用してください。"
            "Tool結果にない情報を推測または補完しないでください。"
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


def search_whiskeys(query):
    service = WhiskeySearchService()

    items, next_token = service.search_whiskeys(
        query,
        limit=5,
        max_pages=1,
    )
    print(items)
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


def get_app_name():
    return {"name": "Whiskey Log"}


principal = Principal(user_id="dumy-user")
run_agent("タリスカーを探して", principal)
