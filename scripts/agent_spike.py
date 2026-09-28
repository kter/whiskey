import boto3

client = boto3.client("bedrock-runtime", region_name="ap-northeast-1")


def get_app_name():
    return {"name": "Whiskey Log"}


messages = [
    {"role": "user", "content": [{"text": "こんにちは、あなたは何ができますか？"}]}
]
res = client.converse(modelId="jp.amazon.nova-2-lite-v1:0", messages=messages)

# print(res)

assistant_message = res["output"]["message"]
messages.append(assistant_message)
messages.append(
    {
        "role": "user",
        "content": [{"text": "今の回答を一言でまとめてください"}],
    }
)
res2 = client.converse(modelId="jp.amazon.nova-2-lite-v1:0", messages=messages)

# print(res2)

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
messages = []
messages.append(
    {
        "role": "user",
        "content": [{"text": "このアプリの名前を教えて"}],
    }
)
res3 = client.converse(
    modelId="jp.amazon.nova-2-lite-v1:0",
    messages=messages,
    toolConfig={
        "tools": tools,
    },
)
print(res3)

assistant_message = res3["output"]["message"]
messages.append(assistant_message)
for block in assistant_message["content"]:
    if "toolUse" in block:
        tool_use = block["toolUse"]
        print("name:", tool_use["name"])
        print("input:", tool_use["input"])
        print("toolUseId:", tool_use["toolUseId"])

        if tool_use["name"] == "get_app_name":
            result = get_app_name()
            print("tool result:", result)
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "toolResult": {
                                "toolUseId": tool_use["toolUseId"],
                                "content": [{"json": result}],
                            }
                        }
                    ],
                }
            )
if res3["stopReason"] == "tool_use":
    res4 = client.converse(
        modelId="jp.amazon.nova-2-lite-v1:0",
        messages=messages,
        toolConfig={
            "tools": tools,
        },
    )
    print("res4:", res4["output"]["message"]["content"])
