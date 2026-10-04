"""Owner-bound transport state for asynchronous chat questions."""

import hashlib
import json
import time
from datetime import datetime, timezone

from whiskey_common.cost_guard import UsageBudget


class ChatJobConflict(Exception):
    """A request ID was reused for a different or expired question."""


class ChatJobs:
    """Admit, claim, finish, and read transient chat jobs."""

    def __init__(self, dynamodb, table_name):
        self.table = dynamodb.Table(table_name)
        self.budget = UsageBudget(dynamodb, table_name)

    @staticmethod
    def key(user_id, request_id):
        return {"pk": f"chat-job/{user_id}/{request_id}"}

    def get(self, user_id, request_id):
        item = self.table.get_item(Key=self.key(user_id, request_id), ConsistentRead=True).get("Item")
        if not item or item["expires_at"] <= int(time.time()):
            return None
        return item

    def submit(self, user_id, payload):
        now = datetime.now(timezone.utc)
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        item = {**self.key(user_id, payload["request_id"]), **payload, "user_id": user_id,
                "fingerprint": fingerprint, "status": "pending", "created_at": int(now.timestamp()),
                "deadline": int(now.timestamp()) + 150, "expires_at": int(now.timestamp()) + 900,
                "ttl": int(now.timestamp()) + 900}
        admitted = self.budget.start_chat(user_id, item, now=now)
        if admitted:
            return item, True
        existing = self.get(user_id, payload["request_id"])
        if not existing or existing["fingerprint"] != fingerprint:
            raise ChatJobConflict("Request ID already used")
        return existing, False

    def claim(self, user_id, request_id):
        now = int(time.time())
        try:
            response = self.table.update_item(Key=self.key(user_id, request_id),
                UpdateExpression="SET #status = :running",
                ConditionExpression="#status = :pending AND deadline > :now AND expires_at > :now",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={":pending": "pending", ":running": "running", ":now": now},
                ReturnValues="ALL_NEW")
            return response["Attributes"]
        except self.table.meta.client.exceptions.ConditionalCheckFailedException:
            return None

    def finish(self, user_id, request_id, *, answer=None, error=None):
        state = "complete" if answer is not None else "failed"
        result = {"answer": answer} if answer is not None else {"error": error or "回答の生成に失敗しました。"}
        try:
            self.table.update_item(Key=self.key(user_id, request_id),
                UpdateExpression="SET #status = :state, #result = :result REMOVE message, history, session_id",
                ConditionExpression="#status IN (:pending, :running)",
                ExpressionAttributeNames={"#status": "status", "#result": "result"},
                ExpressionAttributeValues={":state": state, ":result": result, ":pending": "pending", ":running": "running"})
        except self.table.meta.client.exceptions.ConditionalCheckFailedException:
            pass

    def public(self, user_id, request_id):
        item = self.get(user_id, request_id)
        if item and item["status"] in {"pending", "running"} and item["deadline"] <= int(time.time()):
            self.finish(user_id, request_id, error="回答の生成がタイムアウトしました。")
            item = self.get(user_id, request_id)
        if not item:
            return None
        return {"request_id": request_id, "status": item["status"], **item.get("result", {})}
