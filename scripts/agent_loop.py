import boto3

MAX_STEPS = 5
client = boto3.client("bedrock-runtime", region_name="ap-northeast-1")
messages = [{"role": "user", "content": [{"text": "このアプリの名前を教えて"}]}]
tools = [
    {
        "toolSpec": {
            "name": "get_app_name",
            "description": "Whiskeyアプリの名前を取得する",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                }
            },
        }
    }
]


def get_app_name():
    return {"name": "Whiskey Log"}


for step in range(MAX_STEPS):
    response = client.converse(
        modelId="jp.amazon.nova-2-lite-v1:0",
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
                if tool_use["name"] == "get_app_name":
                    result = get_app_name()
                    tool_results.append(
                        {
                            "toolResult": {
                                "toolUseId": tool_use["toolUseId"],
                                "content": [{"json": result}],
                            }
                        }
                    )
                else:
                    tool_results.append(
                        {
                            "toolResult": {
                                "toolUseId": tool_use["toolUseId"],
                                "content": [{"text": "unknown tool"}],
                            }
                        }
                    )
    else:
        print("unknown stop reason")
        break
    messages.append({"role": "user", "content": tool_results})
else:
    print("Exceed MAX_STEP count")
