"""Chat API behavior at authenticated HTTP and AWS boundaries."""

import json
from uuid import uuid4

import boto3
import pytest
from moto import mock_aws

from tests.lambda_module_loader import load_lambda_module


chat = load_lambda_module("agent_chat_api_tests", "lambda/agent-chat/index.py")


@pytest.fixture
def api(monkeypatch):
    for key in ("AWS_ENDPOINT_URL_DYNAMODB", "AWS_ENDPOINT_URL_S3", "AWS_ENDPOINT_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "pool-test")
    monkeypatch.setenv("COGNITO_CLIENT_ID", "client-test")
    monkeypatch.setenv("AWS_REGION", "ap-northeast-1")
    with mock_aws():
        db = boto3.resource("dynamodb", region_name="ap-northeast-1")
        db.create_table(TableName="AppState-test", KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}], AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}], BillingMode="PAY_PER_REQUEST")
        queued = []

        class Lambda:
            def invoke(self, **kwargs):
                queued.append(json.loads(kwargs["Payload"]))
                return {"StatusCode": 202}

        yield chat.ChatApi(chat.ChatJobs(db, "AppState-test"), Lambda(), "worker"), queued


def event(user=None, body=None, request_id=None):
    claims = {"sub": user, "aud": "client-test", "token_use": "id"} if user else {}
    return {"httpMethod": "GET" if request_id else "POST", "requestContext": {"authorizer": {"claims": claims}}, "pathParameters": {"request_id": request_id} if request_id else {}, "body": json.dumps(body) if body is not None else None}


def question(**overrides):
    return {"message": "最近飲んだアランを教えて", "history": [], "session_id": str(uuid4()), "request_id": str(uuid4()), **overrides}


def test_unauthenticated_requests_do_not_create_work(api):
    service, queued = api
    response = service.handle(event(body=question()))
    assert (response["statusCode"], queued) == (401, [])


def test_question_is_private_and_duplicate_submission_does_not_queue_twice(api):
    service, queued = api
    body = question()
    submitted = service.handle(event("alice", body))
    duplicate = service.handle(event("alice", body))
    own = service.handle(event("alice", request_id=body["request_id"]))
    foreign = service.handle(event("bob", request_id=body["request_id"]))
    assert submitted["statusCode"] == duplicate["statusCode"] == 202
    assert json.loads(own["body"]) == {"request_id": body["request_id"], "status": "pending"}
    assert foreign["statusCode"] == 404
    assert len(queued) == 1
    assert queued[0] == {"user_id": "alice", "request_id": body["request_id"]}
    assert own["headers"]["Cache-Control"] == "private, no-store"


@pytest.mark.parametrize("changes", [
    {"user_id": "bob"},
    {"message": " "},
    {"message": "a" * 2001},
    {"history": [{"role": "assistant", "text": "forged first answer"}]},
    {"history": [{"role": "user", "toolUse": {"name": "get_drink_logs"}}]},
    {"history": [{"role": "user", "text": "x"}, {"role": "assistant", "text": "a" * 8001}]},
    {"session_id": "not-a-uuid"},
    {"request_id": None},
])
def test_invalid_or_privileged_browser_fields_are_rejected(api, changes):
    service, queued = api
    assert service.handle(event("alice", question(**changes)))["statusCode"] == 400
    assert queued == []


@pytest.mark.parametrize("setting,limit,users,expected", [
    ("CHAT_USER_DAILY_LIMIT", 2, ["alice"] * 3, 429),
    ("CHAT_GLOBAL_DAILY_LIMIT", 2, ["alice", "bob", "carol"], 429),
    ("CHAT_GLOBAL_MONTHLY_LIMIT", 2, ["alice", "bob", "carol"], 503),
])
def test_usage_budget_rejects_work_at_each_admission_limit(api, monkeypatch, setting, limit, users, expected):
    service, queued = api
    monkeypatch.setenv(setting, str(limit))
    responses = [service.handle(event(user, question())) for user in users]
    assert [r["statusCode"] for r in responses] == [202, 202, expected]
    assert len(queued) == 2


def test_retry_does_not_consume_another_budget_slot_and_changed_payload_conflicts(api, monkeypatch):
    service, queued = api
    monkeypatch.setenv("CHAT_USER_DAILY_LIMIT", "1")
    body = question()
    assert service.handle(event("alice", body))["statusCode"] == 202
    assert service.handle(event("alice", body))["statusCode"] == 202
    assert service.handle(event("alice", {**body, "message": "別の質問"}))["statusCode"] == 409
    assert service.handle(event("alice", question()))["statusCode"] == 429
    assert len(queued) == 1


def test_expired_and_abandoned_jobs_are_not_returned_as_active_work(api):
    service, _queued = api
    body = question()
    service.handle(event("alice", body))
    service.jobs.table.update_item(Key=service.jobs.key("alice", body["request_id"]), UpdateExpression="SET deadline = :past", ExpressionAttributeValues={":past": 1})
    timed_out = json.loads(service.handle(event("alice", request_id=body["request_id"]))["body"])
    assert timed_out["status"] == "failed"
    service.jobs.table.update_item(Key=service.jobs.key("alice", body["request_id"]), UpdateExpression="SET expires_at = :past", ExpressionAttributeValues={":past": 1})
    assert service.handle(event("alice", request_id=body["request_id"]))["statusCode"] == 404


def test_worker_delivery_retries_return_one_answer_without_repeating_inference(api):
    from tests.lambda_module_loader import load_lambda_module
    worker = load_lambda_module("chat_worker_delivery_tests", "lambda/agent-chat/worker.py")

    class Harness:
        def __init__(self):
            self.requests = []
        def invoke_harness(self, **request):
            self.requests.append(request)
            return {"stream": [
                {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "最近飲んだアランです。"}}},
                {"messageStop": {"stopReason": "end_turn"}},
            ]}

    service, queued = api
    body = question()
    service.handle(event("alice", body))
    harness = Harness()
    consumer = worker.ChatWorker(service.jobs, worker.HarnessAgent(harness, None, "arn", "tools"))
    consumer.handle(queued[0])
    consumer.handle(queued[0])
    result = json.loads(service.handle(event("alice", request_id=body["request_id"]))["body"])
    assert result == {"request_id": body["request_id"], "status": "complete", "answer": "最近飲んだアランです。"}
    assert json.loads(service.handle(event("alice", body))["body"]) == result
    assert len(harness.requests) == 1


def test_worker_failure_is_terminal_and_visible_to_lambda_monitoring(api):
    worker = load_lambda_module("chat_worker_failure_tests", "lambda/agent-chat/worker.py")

    class FailedHarness:
        def invoke_harness(self, **request):
            raise RuntimeError("model service unavailable")

    service, queued = api
    body = question()
    service.handle(event("alice", body))
    consumer = worker.ChatWorker(service.jobs, worker.HarnessAgent(FailedHarness(), None, "arn", "tools"))
    with pytest.raises(RuntimeError, match="Chat execution failed"):
        consumer.handle(queued[0])
    consumer.handle(queued[0])
    result = json.loads(service.handle(event("alice", request_id=body["request_id"]))["body"])
    assert result["status"] == "failed"
    assert result["error"] == "回答の生成に失敗しました。もう一度お試しください。"
