"""Managed harness interaction at streaming inference and Lambda boundaries."""

import io
import json
import pytest

from tests.lambda_module_loader import load_lambda_module


worker = load_lambda_module("agent_chat_worker_tests", "lambda/agent-chat/worker.py")


def text_stream(text):
    return [{"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": text}}}, {"messageStop": {"stopReason": "end_turn"}}]


class Harness:
    def __init__(self):
        self.requests = []

    def invoke_harness(self, **request):
        self.requests.append(request)
        if len(self.requests) == 1:
            return {"stream": [
                {"contentBlockStart": {"contentBlockIndex": 0, "start": {"toolUse": {"toolUseId": "call-1", "name": "get_drink_logs"}}}},
                {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"toolUse": {"input": '{"limit":'}}}},
                {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"toolUse": {"input": "3}"}}}},
                {"messageStop": {"stopReason": "tool_use"}},
            ]}
        result = json.loads(request["messages"][-1]["content"][0]["toolResult"]["content"][0]["text"])
        return {"stream": [
            {"messageStart": {"role": "user"}},
            {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"toolResult": [{"text": json.dumps(result)}]}}},
            {"messageStop": {"stopReason": "tool_result"}},
            {"messageStart": {"role": "assistant"}},
            *text_stream(f"{result['results'][0]['brand_text']}を飲みました。"),
        ]}


class ToolLambda:
    def __init__(self):
        self.requests = []

    def invoke(self, **request):
        payload = json.loads(request["Payload"])
        self.requests.append(payload)
        result = {"results": [{"brand_text": f"{payload['principal']['user_id']}のアラン"}], "partial": False}
        return {"Payload": io.BytesIO(json.dumps(result).encode())}


def test_inline_tools_use_the_trusted_principal_and_resume_with_results():
    harness, tools = Harness(), ToolLambda()
    agent = worker.HarnessAgent(harness, tools, "harness-arn", "tool-function")
    answer = agent.run({"user_id": "alice", "message": "最近の3件", "history": [], "session_id": "00000000-0000-4000-8000-000000000001"})
    assert answer == "aliceのアランを飲みました。"
    assert tools.requests == [{"principal": {"user_id": "alice"}, "name": "get_drink_logs", "params": {"limit": 3}}]
    assert all(r["allowedTools"] == ["@search_whiskeys", "@get_drink_logs", "@search_drink_logs"] for r in harness.requests)
    assert harness.requests[0]["runtimeSessionId"] == harness.requests[1]["runtimeSessionId"]
    assert harness.requests[0]["messages"] == [{"role": "user", "content": [{"text": "最近の3件"}]}]
    assert [m["role"] for m in harness.requests[1]["messages"]] == ["assistant", "user"]


def test_stream_keeps_only_the_last_assistant_message():
    stream = [
        {"messageStart": {"role": "assistant"}},
        *text_stream("検索します。"),
        {"messageStart": {"role": "user"}},
        *text_stream("内部ツール結果"),
        {"messageStart": {"role": "assistant"}},
        *text_stream("最終回答"),
    ]
    answer, reason = worker.read_stream(stream)
    assert answer == {"role": "assistant", "content": [{"text": "最終回答"}]}
    assert reason == "end_turn"


@pytest.mark.parametrize("fragment,reason", [("", "end_turn"), ("truncated", "max_tokens")])
def test_empty_or_truncated_harness_answers_fail(fragment, reason):
    class Broken:
        def invoke_harness(self, **request):
            return {"stream": [{"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": fragment}}}, {"messageStop": {"stopReason": reason}}]}
    agent = worker.HarnessAgent(Broken(), ToolLambda(), "arn", "tools")
    with pytest.raises(RuntimeError):
        agent.run({"user_id": "alice", "message": "test", "history": [], "session_id": "same-browser-session"})


def test_unknown_tools_are_not_executed_and_loop_is_bounded():
    class Loop:
        def __init__(self):
            self.requests = []
        def invoke_harness(self, **request):
            self.requests.append(request)
            return {"stream": [
                {"contentBlockStart": {"contentBlockIndex": 0, "start": {"toolUse": {"toolUseId": f"call-{len(self.requests)}", "name": "delete_drink_log"}}}},
                {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"toolUse": {"input": "{}"}}}},
                {"messageStop": {"stopReason": "tool_use"}},
            ]}
    harness, tools = Loop(), ToolLambda()
    with pytest.raises(RuntimeError):
        worker.HarnessAgent(harness, tools, "arn", "tools").run({"user_id": "alice", "message": "test", "history": [], "session_id": "same-browser-session"})
    assert len(harness.requests) == 5
    assert tools.requests == []


def test_each_question_has_a_fresh_runtime_session_even_in_the_same_browser():
    class Answers:
        def __init__(self):
            self.sessions = []
        def invoke_harness(self, **request):
            self.sessions.append(request["runtimeSessionId"])
            return {"stream": text_stream("回答")}
    harness = Answers()
    agent = worker.HarnessAgent(harness, ToolLambda(), "arn", "tools")
    for user in ("alice", "bob", "alice"):
        agent.run({"user_id": user, "message": "test", "history": [], "session_id": "same-browser-session"})
    assert len(set(harness.sessions)) == 3


def test_multi_tool_continuations_do_not_replay_bounded_browser_history():
    class MultiTool:
        def __init__(self):
            self.requests = []
        def invoke_harness(self, **request):
            self.requests.append(request)
            step = len(self.requests)
            if step == 3:
                return {"stream": text_stream("回答")}
            return {"stream": [
                {"contentBlockStart": {"contentBlockIndex": 0, "start": {"toolUse": {
                    "toolUseId": f"call-{step}", "name": "get_drink_logs"}}}},
                {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"toolUse": {"input": "{}"}}}},
                {"messageStop": {"stopReason": "tool_use"}},
            ]}
    harness = MultiTool()
    history = [{"role": "user", "text": "前の質問"}, {"role": "assistant", "text": "前の回答"}]
    answer = worker.HarnessAgent(harness, ToolLambda(), "arn", "tools").run({
        "user_id": "alice", "message": "続き", "history": history, "session_id": "same-browser-session"})
    assert answer == "回答"
    assert len(harness.requests[0]["messages"]) == 3
    assert len({r["runtimeSessionId"] for r in harness.requests}) == 1
    for step, request in enumerate(harness.requests[1:], 1):
        assert len(request["messages"]) == 2
        assistant, result = request["messages"]
        assert assistant["content"][0]["toolUse"]["toolUseId"] == f"call-{step}"
        assert result["content"][0]["toolResult"]["toolUseId"] == f"call-{step}"
