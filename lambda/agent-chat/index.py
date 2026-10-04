"""Authenticated, asynchronous chat HTTP API."""

import json
import logging
import os
from uuid import UUID

from chat_jobs import ChatJobConflict, ChatJobs
from whiskey_common.clients import get_boto3_client, get_dynamodb_resource
from whiskey_common.cost_guard import UsageBudgetExceeded
from whiskey_common.jwt_utils import extract_user_id_from_event
from whiskey_common.responses import create_response


def read_uuid(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("IDs must be canonical UUIDs")
    return value


def read_question(raw):
    if not isinstance(raw, str) or len(raw.encode()) > 64000:
        raise ValueError("Invalid request body")
    data = json.loads(raw)
    if not isinstance(data, dict) or set(data) != {"message", "history", "session_id", "request_id"}:
        raise ValueError("Invalid question fields")
    text = data["message"]
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        raise ValueError("message must contain 1–2000 characters")
    history = data["history"]
    if not isinstance(history, list) or len(history) > 10:
        raise ValueError("history must contain at most 10 messages")
    for index, item in enumerate(history):
        if not isinstance(item, dict) or set(item) != {"role", "text"}:
            raise ValueError("history must contain text messages only")
        expected = "user" if index % 2 == 0 else "assistant"
        if item["role"] != expected or not isinstance(item["text"], str) or not item["text"].strip() or len(item["text"]) > 8000:
            raise ValueError("Invalid history message")
    if len(history) % 2 or sum(len(item["text"]) for item in history) > 12000:
        raise ValueError("Invalid history length")
    return {"message": text.strip(), "history": history, "session_id": read_uuid(data["session_id"]), "request_id": read_uuid(data["request_id"])}


class ChatApi:
    """Accept questions and expose only the caller's job results."""

    def __init__(self, jobs, lambda_client, worker_name):
        self.jobs = jobs
        self.lambda_client = lambda_client
        self.worker_name = worker_name

    def handle(self, event):
        user_id = extract_user_id_from_event(event)
        if not user_id:
            return create_response(401, {"error": "Unauthorized"}, event=event, private=True)
        def respond(status, body):
            return create_response(status, body, event=event, private=True)
        try:
            method = event.get("httpMethod")
            if method == "GET":
                request_id = read_uuid((event.get("pathParameters") or {}).get("request_id"))
                result = self.jobs.public(user_id, request_id)
                return respond(200, result) if result else respond(404, {"error": "Not found"})
            if method != "POST":
                return respond(405, {"error": "Method not allowed"})
            if event.get("isBase64Encoded"):
                raise ValueError("Encoded bodies are unsupported")
            payload = read_question(event.get("body"))
            item, admitted = self.jobs.submit(user_id, payload)
            if admitted:
                try:
                    response = self.lambda_client.invoke(FunctionName=self.worker_name, InvocationType="Event",
                        Payload=json.dumps({"user_id": user_id, "request_id": payload["request_id"]}).encode())
                    if response.get("StatusCode") != 202:
                        raise RuntimeError("Worker rejected request")
                except Exception:
                    self.jobs.finish(user_id, payload["request_id"], error="質問の受付に失敗しました。")
                    raise
            return respond(202, {"request_id": payload["request_id"], "status": item["status"], **item.get("result", {})})
        except (ValueError, TypeError, AttributeError):
            return respond(400, {"error": "Invalid chat request"})
        except ChatJobConflict:
            return respond(409, {"error": "Request ID already used"})
        except UsageBudgetExceeded as exc:
            return respond(exc.status_code, {"error": str(exc)})


def lambda_handler(event, context):
    """Handle POST /api/chat and GET /api/chat/{request_id}."""
    try:
        return ChatApi(ChatJobs(get_dynamodb_resource(), os.environ["APP_STATE_TABLE"]),
                       get_boto3_client("lambda"), os.environ["CHAT_WORKER_FUNCTION"]).handle(event)
    except Exception as exc:
        logging.getLogger(__name__).error("Chat API failed: %s", type(exc).__name__)
        return create_response(503, {"error": "Chat unavailable"}, event=event, private=True)
