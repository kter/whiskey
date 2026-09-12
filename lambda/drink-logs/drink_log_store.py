"""Bound persistence operations for the authenticated Drink Log request path."""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from botocore.exceptions import ClientError

from whiskey_common.cost_guard import UsageBudget, UsageBudgetExceeded
from whiskey_common.images import ImageNormalizationError, normalize_image, sniff_format
from whiskey_common.scan_utils import encode_next_token

import lifecycle as lifecycle_module
from lifecycle import CreateConflict, DrinkLogLifecycle, derive_drink_log_id


SERVING_STYLES = {"NEAT", "ROCKS", "WATER", "SODA", "COCKTAIL"}
CONTENT_TYPES = {
    "image/jpeg": ("jpeg", "jpg"),
    "image/png": ("png", "png"),
    "image/webp": ("webp", "webp"),
}
INTERNAL_FIELDS = {
    "_completion",
    "content_type",
    "tmp_etag",
    "s3_image_key",
    "tmp_s3_key",
    "quota_allocated",
    "delete_started_at",
}
MAX_TIMELINE_PAGE_QUERIES = 10
PRESIGNED_POST_SECONDS = 120
PRESIGNED_GET_SECONDS = 900
UUID_TEXT = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}"
ANALYSIS_ID_RE = re.compile(rf"^(?:ai-result:([^:]+):)?({UUID_TEXT})$")


class ValidationError(ValueError):
    def __init__(self, fields: Mapping[str, str]):
        super().__init__("Validation failed")
        self.fields = dict(fields)


class AnalysisConflict(Exception):
    pass


def _analysis_identity(user_id: str, analysis_id: str) -> tuple[str, str]:
    match = ANALYSIS_ID_RE.fullmatch(analysis_id)
    if not match:
        raise ValidationError({"analysis_id": "Must be a valid analysis result token"})
    token_user, upload_uuid = match.groups()
    if token_user is not None and token_user != user_id:
        raise AnalysisConflict("Analysis result does not belong to caller")
    upload_uuid = str(uuid.UUID(upload_uuid))
    return f"ai-result:{user_id}:{upload_uuid}", upload_uuid


def _extract_upload_uuid(s3_key: str, user_id: str) -> str:
    pattern = re.compile(
        rf"^tmp/{re.escape(user_id)}/({UUID_TEXT})\.(?:jpg|jpeg|png|webp)$"
    )
    match = pattern.fullmatch(s3_key)
    if not match:
        raise AnalysisConflict("Analysis result has an invalid upload key")
    return str(uuid.UUID(match.group(1)))


def _candidate_brand(candidate: Any) -> str:
    if isinstance(candidate, str):
        brand = candidate
    elif isinstance(candidate, Mapping):
        brand = next(
            (
                candidate.get(key)
                for key in ("brand_text", "name", "label")
                if isinstance(candidate.get(key), str)
            ),
            "",
        )
    else:
        brand = ""
    if not brand or len(brand) > 200:
        raise AnalysisConflict("Selected analysis candidate is invalid")
    return brand


def _completion_from_analysis(
    result: Mapping[str, Any],
    candidate: Any,
    overrides: Mapping[str, Any],
    *,
    candidate_selected: bool,
) -> dict[str, Any]:
    brand_text = _candidate_brand(candidate) if candidate_selected else ""
    whiskey_id = None
    if isinstance(candidate, Mapping):
        # The selected candidate is authoritative -- including when it has no
        # match. analyze writes a top-level whiskey_id taken from candidates[0],
        # so falling back to it makes picking the 2nd bottle in a multi-bottle
        # photo inherit the 1st bottle's master ID and report brand_source
        # "matched": the exact class of confidently-wrong record this design
        # exists to prevent.
        whiskey_id = candidate.get("whiskey_id") or candidate.get("matched_whiskey_id")
    elif candidate_selected:
        # Legacy analysis items whose candidate is not a Mapping (e.g. a bare
        # string) still rely on the analysis-level value. Those sit in AppState
        # under a 30-minute TTL, so the path has to keep working.
        whiskey_id = result.get("whiskey_id") or result.get("matched_whiskey_id")
    if whiskey_id is not None and (not isinstance(whiskey_id, str) or not whiskey_id):
        raise AnalysisConflict("Matched whiskey ID is invalid")
    serving_style = result.get("serving_style", "NEAT")
    if serving_style not in SERVING_STYLES:
        raise AnalysisConflict("Analysis serving style is invalid")

    completion: dict[str, Any] = {
        "brand_text": brand_text,
        "brand_source": "manual" if not candidate_selected else ("matched" if whiskey_id else "ai"),
        "serving_style": serving_style,
        "store": {"name": ""},
    }
    if whiskey_id:
        completion["whiskey_id"] = whiskey_id
    model_id = result.get("model_id")
    confidence = result.get("confidence")
    if isinstance(candidate, Mapping) and candidate.get("confidence") is not None:
        confidence = candidate.get("confidence")
    if confidence is not None or (candidate_selected and model_id is not None):
        if not isinstance(model_id, str) or not model_id:
            raise AnalysisConflict("Analysis model ID is invalid")
        try:
            confidence_decimal = Decimal(str(confidence))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise AnalysisConflict("Analysis confidence is invalid") from exc
        if not confidence_decimal.is_finite() or not Decimal("0") <= confidence_decimal <= Decimal("1"):
            raise AnalysisConflict("Analysis confidence is invalid")
        completion["ai"] = {"model_id": model_id, "confidence": confidence_decimal}

    if "brand_text" in overrides:
        completion["brand_text"] = overrides["brand_text"]
        completion["brand_source"] = "manual"
        completion.pop("whiskey_id", None)
    if "serving_style" in overrides:
        completion["serving_style"] = overrides["serving_style"]
    if "store" in overrides:
        store = {"name": ""}
        if "name" in overrides["store"]:
            store["name"] = overrides["store"]["name"]
        place_id = overrides["store"].get("place_id")
        if place_id is not None:
            store["place_id"] = place_id
        completion["store"] = store
    for field in ("rating", "notes"):
        if field in overrides:
            completion[field] = overrides[field]
    return completion


def _safe_image_key(item: Mapping[str, Any], user_id: str) -> str | None:
    key = item.get("s3_image_key")
    if item.get("status") != "complete" or not isinstance(key, str):
        return None
    return key if key.startswith(f"logs/{user_id}/") else None


@dataclass(frozen=True)
class DrinkLogStore:
    """Expose Drink Log persistence operations with AWS wiring bound once."""

    lifecycle: DrinkLogLifecycle
    budget: UsageBudget
    dynamodb: Any
    app_state_table_name: str
    s3: Any
    bucket_name: str

    @classmethod
    def from_environment(cls, dynamodb: Any, s3: Any) -> "DrinkLogStore":
        drinklogs_table_name = os.environ["DRINKLOGS_TABLE"]
        app_state_table_name = os.environ["APP_STATE_TABLE"]
        bucket_name = os.environ["IMAGES_BUCKET"]
        lifecycle = DrinkLogLifecycle(
            dynamodb,
            s3,
            drinklogs_table_name,
            app_state_table_name,
            bucket_name,
        )
        return cls(
            lifecycle=lifecycle,
            budget=UsageBudget(dynamodb, app_state_table_name, lifecycle_module.rfc3339),
            dynamodb=dynamodb,
            app_state_table_name=app_state_table_name,
            s3=s3,
            bucket_name=bucket_name,
        )

    def create_upload_url(self, user_id: str, content_type: str) -> dict[str, Any]:
        """Return an upload form; raise UsageBudgetExceeded when the Usage Budget is exhausted."""
        now_dt = lifecycle_module.utc_now()
        self.budget.reserve_upload(user_id, now=now_dt)

        _format, extension = CONTENT_TYPES[content_type]
        key = f"tmp/{user_id}/{uuid.uuid4()}.{extension}"
        # Keep in sync with tests/test_drink_log_contract.py.
        max_bytes = int(os.environ.get("UPLOAD_MAX_BYTES", "3670016"))
        # A captured form is pinned to one exact key. Reuse can only overwrite that
        # object and cannot consume storage allocation or an expensive API. The
        # residual risk is low-cost PUT requests during the 120-second validity
        # window; request metrics and alarms monitor that unbounded request charge.
        post = self.s3.generate_presigned_post(
            Bucket=self.bucket_name,
            Key=key,
            Fields={"Content-Type": content_type},
            Conditions=[
                {"Content-Type": content_type},
                ["content-length-range", 0, max_bytes],
            ],
            ExpiresIn=PRESIGNED_POST_SECONDS,
        )
        return {"upload_url": post["url"], "fields": post["fields"], "s3_key": key}

    def _prepare_initial_record(
        self,
        user_id: str,
        analysis_pk: str,
        upload_uuid: str,
        candidate_index: int | None,
        overrides: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        result = self.dynamodb.Table(self.app_state_table_name).get_item(
            Key={"pk": analysis_pk},
            ConsistentRead=True,
        ).get("Item")
        now_epoch = int(lifecycle_module.utc_now().timestamp())
        if not result or result.get("user") != user_id:
            raise AnalysisConflict("Analysis result is missing or already consumed")
        try:
            expires_at = int(result["expires_at"])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise AnalysisConflict("Analysis result expiry is invalid") from exc
        if expires_at <= now_epoch:
            raise AnalysisConflict("Analysis result has expired; analyze the image again")
        s3_key = result.get("s3_key")
        if not isinstance(s3_key, str) or _extract_upload_uuid(s3_key, user_id) != upload_uuid:
            raise AnalysisConflict("Analysis result upload binding is invalid")
        etag_name = "ETag" if "ETag" in result else "etag"
        etag = result.get(etag_name)
        if not isinstance(etag, str) or not etag:
            raise AnalysisConflict("Analysis result ETag is invalid")
        candidate = None
        if candidate_index is not None:
            candidates = result.get("candidates")
            if not isinstance(candidates, list) or candidate_index >= len(candidates):
                raise AnalysisConflict("Selected analysis candidate is unavailable")
            candidate = candidates[candidate_index]
        completion = _completion_from_analysis(
            result,
            candidate,
            overrides or {},
            candidate_selected=candidate_index is not None,
        )

        try:
            head = self.s3.head_object(Bucket=self.bucket_name, Key=s3_key)
        except ClientError as exc:
            if lifecycle_module._is_missing_s3_error(exc):
                raise AnalysisConflict(
                    "Uploaded image is missing; upload and analyze it again"
                ) from exc
            raise
        if head.get("ETag") != etag:
            raise AnalysisConflict("Uploaded image changed after analysis")
        content_type = head.get("ContentType")
        if content_type not in CONTENT_TYPES:
            raise AnalysisConflict("Uploaded image content type is unsupported")
        # Keep in sync with tests/test_drink_log_contract.py.
        if int(head.get("ContentLength", 0)) > int(
            os.environ.get("UPLOAD_MAX_BYTES", "3670016")
        ):
            raise AnalysisConflict("Uploaded image exceeds the upload limit")

        now = lifecycle_module.rfc3339(lifecycle_module.utc_now())
        pending = {
            "id": derive_drink_log_id(user_id, upload_uuid),
            "user_id": user_id,
            "status": "pending",
            "datetime": (overrides or {}).get("datetime", now),
            "tmp_s3_key": s3_key,
            "tmp_etag": etag,
            "content_type": content_type,
            "quota_allocated": True,
            "_completion": completion,
            "created_at": now,
            "updated_at": now,
        }
        condition = "#user = :user AND s3_key = :s3_key AND #etag = :etag"
        names = {"#user": "user", "#etag": etag_name}
        values = {
            ":user": user_id,
            ":s3_key": s3_key,
            ":etag": etag,
            ":now_epoch": now_epoch,
        }
        if candidate_index is not None:
            condition += f" AND #candidates[{candidate_index}] = :candidate"
            names["#candidates"] = "candidates"
            values[":candidate"] = candidate
        condition += " AND expires_at > :now_epoch"
        consume = {
            "Delete": {
                "TableName": self.app_state_table_name,
                "Key": {"pk": analysis_pk},
                "ConditionExpression": condition,
                "ExpressionAttributeNames": names,
                "ExpressionAttributeValues": values,
            }
        }
        return pending, consume

    def _read_s3_body(self, *, key: str, etag: str) -> bytes:
        response = self.s3.get_object(
            Bucket=self.bucket_name,
            Key=key,
            IfMatch=etag,
        )
        body = response["Body"]
        try:
            return body.read()
        finally:
            body.close()

    def _finish_pending_create(self, record: Mapping[str, Any]) -> dict[str, Any]:
        tmp_key = record.get("tmp_s3_key")
        etag = record.get("tmp_etag")
        content_type = record.get("content_type")
        if not isinstance(tmp_key, str) or not isinstance(etag, str) or content_type not in CONTENT_TYPES:
            raise CreateConflict("Pending record is incomplete")

        try:
            raw = self._read_s3_body(key=tmp_key, etag=etag)
            actual_format = sniff_format(raw[:16])
            expected_format = CONTENT_TYPES[content_type][0]
            if actual_format != expected_format:
                raise ImageNormalizationError(
                    "Image bytes do not match the declared content type"
                )
            normalized = normalize_image(
                raw,
                # Keep in sync with tests/test_drink_log_contract.py.
                max_bytes=int(os.environ.get("IMAGE_MAX_BYTES", "1572864")),
            )
        except ImageNormalizationError as exc:
            compensated = self.lifecycle.compensate_create(
                record, now=lifecycle_module.utc_now()
            )
            winner = self.lifecycle.get(record["id"])
            if not compensated and winner and winner.get("status") == "complete":
                return winner
            if not compensated and winner:
                raise RuntimeError("Terminal image failure was not compensated") from exc
            if compensated:
                try:
                    self.s3.delete_object(Bucket=self.bucket_name, Key=tmp_key)
                except ClientError:
                    # The record no longer references this object. The explicit
                    # tmp/ reconciliation pass will retry this recoverable cleanup.
                    pass
            raise ValidationError({"image": str(exc)}) from exc
        except ClientError as exc:
            if lifecycle_module._is_missing_s3_error(exc) or exc.response.get(
                "Error", {}
            ).get("Code") in {
                "PreconditionFailed",
                "412",
            }:
                compensated = self.lifecycle.compensate_create(
                    record, now=lifecycle_module.utc_now()
                )
                winner = self.lifecycle.get(record["id"])
                if not compensated and winner and winner.get("status") == "complete":
                    return winner
                if not compensated and winner:
                    raise RuntimeError("Changed image failure was not compensated") from exc
                if compensated:
                    try:
                        self.s3.delete_object(Bucket=self.bucket_name, Key=tmp_key)
                    except ClientError:
                        # The tmp/ reconciler owns retry after record compensation.
                        pass
                raise ValidationError({"image": "Uploaded image is missing or changed"}) from exc
            raise

        upload_uuid = _extract_upload_uuid(tmp_key, record["user_id"])
        attempt = uuid.uuid4().hex
        final_key = f"logs/{record['user_id']}/{upload_uuid}-{attempt}.jpg"
        self.s3.put_object(
            Bucket=self.bucket_name,
            Key=final_key,
            Body=normalized,
            ContentType="image/jpeg",
            CacheControl="private, no-store",
        )
        completed = self.lifecycle.complete_create(
            record, final_key, now=lifecycle_module.utc_now()
        )
        if completed is None:
            winner = self.lifecycle.get(record["id"])
            if not winner or winner.get("user_id") != record["user_id"]:
                raise CreateConflict("Drink log disappeared during creation")
            if winner.get("status") != "complete":
                raise CreateConflict("Drink log is no longer creatable")
            completed = winner

        self.s3.delete_object(Bucket=self.bucket_name, Key=tmp_key)
        if not self.lifecycle.object_absent(tmp_key):
            raise RuntimeError("Temporary image deletion was not confirmed")
        cleaned = self.lifecycle.remove_tmp_reference(
            record["id"],
            record["user_id"],
            tmp_key,
        )
        return cleaned or self.lifecycle.get(record["id"]) or completed

    def create_drink_log(
        self,
        user_id: str,
        data: Mapping[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        """Return ``(public_record, created)``; raise UsageBudgetExceeded,
        AnalysisConflict, CreateConflict, or KeyError."""
        analysis_pk, upload_uuid = _analysis_identity(user_id, data["analysis_id"])
        record_id = derive_drink_log_id(user_id, upload_uuid)

        existing = self.lifecycle.get(record_id)
        if existing:
            if existing.get("user_id") != user_id:
                raise KeyError(record_id)
            if existing.get("status") == "complete":
                return self._public_record(existing, user_id), False
            if existing.get("status") == "pending":
                return self._public_record(
                    self._finish_pending_create(existing), user_id
                ), False
            raise CreateConflict("Drink log is being deleted")

        pending, consume = self._prepare_initial_record(
            user_id,
            analysis_pk,
            upload_uuid,
            data.get("candidate_index"),
            data,
        )
        client = self.lifecycle.client
        try:
            self.lifecycle.start_create(
                pending, consume, now=lifecycle_module.utc_now()
            )
            created = True
            current = pending
        except client.exceptions.TransactionCanceledException as exc:
            current = self.lifecycle.get(record_id)
            if current:
                if current.get("user_id") != user_id:
                    raise KeyError(record_id) from exc
                if current.get("status") == "complete":
                    return self._public_record(current, user_id), False
                if current.get("status") == "pending":
                    return self._public_record(
                        self._finish_pending_create(current), user_id
                    ), False
            reasons = exc.response.get("CancellationReasons", [])
            if not reasons:
                raise UsageBudgetExceeded("create", "daily") from exc
            if len(reasons) > 5 and reasons[5].get("Code") == "ConditionalCheckFailed":
                raise AnalysisConflict("Analysis result is stale or already consumed") from exc
            if reasons[0].get("Code") == "ConditionalCheckFailed":
                raise CreateConflict("Concurrent creation did not expose a winner") from exc
            raise

        return self._public_record(self._finish_pending_create(current), user_id), created

    def _public_record(
        self,
        item: Mapping[str, Any],
        user_id: str,
    ) -> dict[str, Any]:
        result = {key: value for key, value in item.items() if key not in INTERNAL_FIELDS}
        image_key = _safe_image_key(item, user_id)
        if image_key:
            result["image_url"] = self.s3.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self.bucket_name,
                    "Key": image_key,
                    "ResponseCacheControl": "private, no-store",
                },
                ExpiresIn=PRESIGNED_GET_SECONDS,
            )
        return result

    def get_timeline(
        self,
        user_id: str,
        limit: int,
        start_key: dict[str, Any] | None,
        filters: Mapping[str, str],
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Return public Drink Logs and an optional continuation token."""
        table = self.lifecycle.table
        items: list[dict[str, Any]] = []
        cursor = start_key
        next_token: str | None = None
        max_pages = max(
            1,
            int(
                os.environ.get(
                    "TIMELINE_MAX_PAGES",
                    str(MAX_TIMELINE_PAGE_QUERIES),
                )
            ),
        )
        for _ in range(max_pages):
            names = {"#status": "status"}
            values: dict[str, Any] = {":user_id": user_id, ":complete": "complete"}
            clauses = ["#status = :complete"]
            if "brand" in filters:
                names["#brand"] = "brand_text"
                values[":brand"] = filters["brand"]
                clauses.append("contains(#brand, :brand)")
            if "store" in filters:
                names.update({"#store": "store", "#name": "name"})
                values[":store"] = filters["store"]
                clauses.append("contains(#store.#name, :store)")
            if "place_id" in filters:
                names.update({"#store": "store", "#place_id": "place_id"})
                values[":place_id"] = filters["place_id"]
                clauses.append("#store.#place_id = :place_id")
            kwargs: dict[str, Any] = {
                "IndexName": "UserDatetimeIndex",
                "KeyConditionExpression": "user_id = :user_id",
                "FilterExpression": " AND ".join(clauses),
                "ExpressionAttributeNames": names,
                "ExpressionAttributeValues": values,
                "ScanIndexForward": False,
                "Limit": max(1, limit - len(items)),
            }
            if cursor:
                kwargs["ExclusiveStartKey"] = cursor
            response = table.query(**kwargs)
            for item in response.get("Items", []):
                if item.get("status") == "complete" and item.get("user_id") == user_id:
                    items.append(self._public_record(item, user_id))
                    if len(items) == limit:
                        break
            cursor = response.get("LastEvaluatedKey")
            if not cursor:
                next_token = None
                break
            next_token = encode_next_token(cursor)
            if len(items) == limit:
                break
        return items, next_token

    def get_owned(self, user_id: str, record_id: str) -> dict[str, Any] | None:
        """Return a public Drink Log, or None when missing, foreign, or not complete."""
        item = self.lifecycle.table.get_item(
            Key={"id": record_id},
            ConsistentRead=True,
        ).get("Item")
        if not item or item.get("user_id") != user_id or item.get("status") != "complete":
            return None
        return self._public_record(item, user_id)

    def update(
        self,
        user_id: str,
        record_id: str,
        data: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        """Return the updated public Drink Log, or None when the write is refused."""
        table = self.lifecycle.table
        names = {"#owner": "user_id", "#status": "status", "#updated_at": "updated_at"}
        values: dict[str, Any] = {
            ":caller": user_id,
            ":complete": "complete",
            ":updated_at": lifecycle_module.rfc3339(lifecycle_module.utc_now()),
        }
        sets = ["#updated_at = :updated_at"]
        removes: list[str] = []
        for field_name in ("brand_text", "notes", "rating", "serving_style"):
            if field_name in data:
                names[f"#{field_name}"] = field_name
                values[f":{field_name}"] = data[field_name]
                sets.append(f"#{field_name} = :{field_name}")
        if "brand_text" in data:
            names["#brand_source"] = "brand_source"
            values[":manual"] = "manual"
            sets.append("#brand_source = :manual")
            # 手入力で銘柄を直したなら、それ以前に照合された whiskey_id は別の商品を
            # 指している。作成時の _completion_from_analysis は破棄しているので、
            # 更新側も揃える。残すと訂正名と誤った ID が同居する。
            names["#whiskey_id"] = "whiskey_id"
            removes.append("#whiskey_id")
        if "store" in data:
            names.update({"#store": "store", "#name": "name", "#place_id": "place_id"})
            store = data["store"]
            if "name" in store:
                values[":store_name"] = store["name"]
                sets.append("#store.#name = :store_name")
            if "place_id" in store:
                if store["place_id"] is None:
                    removes.append("#store.#place_id")
                else:
                    values[":place_id"] = store["place_id"]
                    sets.append("#store.#place_id = :place_id")
        expression = f"SET {', '.join(sets)}"
        if removes:
            expression += f" REMOVE {', '.join(removes)}"
        try:
            response = table.update_item(
                Key={"id": record_id},
                UpdateExpression=expression,
                ConditionExpression="#owner = :caller AND #status = :complete",
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
                ReturnValues="ALL_NEW",
            )
            attributes = response.get("Attributes")
            return self._public_record(attributes, user_id) if attributes else None
        except table.meta.client.exceptions.ConditionalCheckFailedException:
            return None

    def delete(self, user_id: str, record_id: str) -> bool:
        """Return whether deletion completed; False means a conditional write was refused."""
        return self.lifecycle.delete(
            user_id, record_id, now=lifecycle_module.utc_now()
        )
