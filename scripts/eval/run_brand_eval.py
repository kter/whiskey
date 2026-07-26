#!/usr/bin/env python3
"""Evaluate current brand recognition against a versioned image manifest.

Dry-run mode performs local validation only. The dev target verifies the AWS
account before uploading images and invoking the existing analyze Lambda.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, ProfileNotFound


DEV_ACCOUNT_ID = "031921999648"
REGION = "ap-northeast-1"
BUCKET_PREFIX = "whiskey-images-dev"
FUNCTION_NAME = "drink-log-analyze-dev"
DEFAULT_MAX_CASES = 20
MIN_COUNTER_INCREMENTS_PER_CASE = 3
MAX_COUNTER_INCREMENTS_PER_CASE = 5
MIN_GLOBAL_DAILY_INCREMENTS_PER_CASE = 1
MAX_GLOBAL_DAILY_INCREMENTS_PER_CASE = 2
ANALYZE_GLOBAL_DAILY_LIMIT = 50
APP_STATE_TABLE_NAME = "AppState-dev"
UPLOAD_MAX_BYTES = 3_670_016
RESULT_VERSION = 1
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
EXPECTED_IMAGE_FORMATS = {
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".png": "png",
    ".webp": "webp",
}
CONDITIONS = (
    "bottle_front",
    "bottle_angle",
    "reflection_or_condensation",
    "partially_occluded",
    "box_only",
    "miniature",
    "glass_only",
    "multiple_bottles",
    "low_resolution",
    "back_label_only",
)
CASE_REQUIRED_FIELDS = {
    "image",
    "condition",
    "expected_whiskey_id",
    "expected_canonical_name",
}
CASE_ALLOWED_FIELDS = CASE_REQUIRED_FIELDS | {"notes"}
EVAL_USER_RE = re.compile(r"^[A-Za-z0-9._:@+-]+$")
CLIENT_CONFIG = Config(
    connect_timeout=5,
    read_timeout=40,
    retries={"mode": "standard", "total_max_attempts": 2},
)


class ManifestError(ValueError):
    """Raised when an evaluation manifest does not satisfy version 1."""


class ResultFileError(ValueError):
    """Raised when a resume result is incompatible with the manifest."""


class CleanupError(RuntimeError):
    """Raised when a temporary evaluation upload cannot be deleted."""

    def __init__(
        self,
        message: str,
        *,
        original_error: BaseException | None = None,
        cleanup_error: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.original_error = original_error
        self.cleanup_error = cleanup_error


class ImageValidationError(ValueError):
    """Raised after collecting every invalid evaluation image."""


def utc_now_text() -> str:
    """Return the current UTC timestamp in RFC 3339 form."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_manifest_data(data: Any) -> dict[str, Any]:
    """Validate and return a version 1 manifest without calling AWS."""
    if not isinstance(data, dict):
        raise ManifestError("manifest must be a JSON object")
    unknown_root = set(data) - {"version", "cases"}
    if unknown_root:
        raise ManifestError(f"manifest has unknown fields: {', '.join(sorted(unknown_root))}")
    if data.get("version") != 1:
        raise ManifestError("manifest version must be 1")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ManifestError("manifest cases must be a non-empty array")

    for index, case in enumerate(cases):
        location = f"cases[{index}]"
        if not isinstance(case, dict):
            raise ManifestError(f"{location} must be an object")
        missing = CASE_REQUIRED_FIELDS - set(case)
        if missing:
            raise ManifestError(
                f"{location} is missing required fields: {', '.join(sorted(missing))}"
            )
        unknown = set(case) - CASE_ALLOWED_FIELDS
        if unknown:
            raise ManifestError(f"{location} has unknown fields: {', '.join(sorted(unknown))}")

        image = case["image"]
        if not isinstance(image, str) or not image.strip():
            raise ManifestError(f"{location}.image must be a non-empty relative path")
        image_path = Path(image)
        if image_path.is_absolute() or ".." in image_path.parts:
            raise ManifestError(f"{location}.image must stay within the manifest directory")
        if image_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ManifestError(
                f"{location}.image must end in jpg, jpeg, png, or webp"
            )

        condition = case["condition"]
        if condition not in CONDITIONS:
            raise ManifestError(f"{location}.condition is unknown: {condition!r}")

        whiskey_id = case["expected_whiskey_id"]
        if whiskey_id is not None and (
            not isinstance(whiskey_id, str) or not whiskey_id.strip()
        ):
            raise ManifestError(
                f"{location}.expected_whiskey_id must be a non-empty string or null"
            )
        canonical_name = case["expected_canonical_name"]
        if canonical_name is not None and (
            not isinstance(canonical_name, str) or not canonical_name.strip()
        ):
            raise ManifestError(
                f"{location}.expected_canonical_name must be a non-empty string or null"
            )
        if whiskey_id is not None and canonical_name is None:
            raise ManifestError(
                f"{location}.expected_canonical_name is required for a catalog whiskey"
            )
        if "notes" in case and not isinstance(case["notes"], str):
            raise ManifestError(f"{location}.notes must be a string")
    return data


def load_manifest(path: Path) -> dict[str, Any]:
    """Load and validate a manifest from disk."""
    try:
        with path.open(encoding="utf-8") as manifest_file:
            data = json.load(manifest_file)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"manifest is not valid JSON: {exc}") from exc
    return validate_manifest_data(data)


def _sniff_image_format(prefix: bytes) -> str | None:
    if prefix.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(prefix) >= 12 and prefix[:4] == b"RIFF" and prefix[8:12] == b"WEBP":
        return "webp"
    return None


def validate_image_files(
    manifest: Mapping[str, Any],
    manifest_path: Path,
    case_indices: Iterable[int] | None = None,
) -> None:
    """Validate all selected images and report every problem together."""
    indices = (
        list(range(len(manifest["cases"])))
        if case_indices is None
        else list(case_indices)
    )
    problems: list[str] = []
    for case_index in indices:
        case = manifest["cases"][case_index]
        image_path = manifest_path.parent / case["image"]
        label = f"cases[{case_index}].image ({case['image']})"
        try:
            if not image_path.is_file():
                problems.append(f"{label}: file does not exist or is not a regular file")
                continue
            size = image_path.stat().st_size
            if size == 0:
                problems.append(f"{label}: file is empty")
                continue
            if size > UPLOAD_MAX_BYTES:
                problems.append(
                    f"{label}: {size} bytes exceeds the {UPLOAD_MAX_BYTES}-byte upload limit"
                )
            with image_path.open("rb") as image_file:
                actual_format = _sniff_image_format(image_file.read(16))
            expected_format = EXPECTED_IMAGE_FORMATS[image_path.suffix.lower()]
            if actual_format is None:
                problems.append(f"{label}: magic bytes are not JPEG, PNG, or WebP")
            elif actual_format != expected_format:
                problems.append(
                    f"{label}: extension expects {expected_format}, "
                    f"but magic bytes identify {actual_format}"
                )
        except OSError as exc:
            problems.append(f"{label}: cannot read file: {exc}")
    if problems:
        details = "\n".join(f"  - {problem}" for problem in problems)
        raise ImageValidationError(
            f"evaluation image validation failed ({len(problems)} problem(s)):\n{details}"
        )


def manifest_digest(manifest: Mapping[str, Any]) -> str:
    """Return a stable hash used to reject mismatched resume files."""
    encoded = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _candidate_id(candidate: Any) -> str | None:
    if not isinstance(candidate, Mapping):
        return None
    value = candidate.get("whiskey_id")
    return value if isinstance(value, str) and value else None


def score_evaluation(record: Mapping[str, Any]) -> dict[str, Any]:
    """Score one response using a top-candidate confirmation partition."""
    case = record["case"]
    response = record.get("response")
    candidates = response.get("candidates", []) if isinstance(response, Mapping) else []
    if not isinstance(candidates, list):
        candidates = []
    expected_id = case["expected_whiskey_id"]
    top_id = _candidate_id(candidates[0]) if candidates else None
    confirmed = top_id is not None
    confirmed_correct = confirmed and top_id == expected_id
    confirmed_wrong = confirmed and top_id != expected_id
    not_confirmed = not confirmed
    top3_correct = any(
        candidate_id == expected_id
        for candidate_id in (_candidate_id(candidate) for candidate in candidates[:3])
        if candidate_id is not None
    )
    rejected = not any(_candidate_id(candidate) is not None for candidate in candidates)
    no_candidates = not candidates
    top = candidates[0] if candidates and isinstance(candidates[0], Mapping) else {}
    return {
        "confirmed_correct": confirmed_correct,
        "confirmed_wrong": confirmed_wrong,
        "not_confirmed": not_confirmed,
        "top1_correct": confirmed_correct,
        "top3_correct": top3_correct,
        "false_confirmation": confirmed_wrong,
        "rejected": rejected,
        "no_candidates": no_candidates,
        "actual_whiskey_id": top_id,
        "actual_brand_text": top.get("brand_text"),
        "match_source": top.get("match_source"),
    }


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _aggregate_records(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    scored_records = [
        record
        for record in records
        if record.get("status_code", 200) == 200 and isinstance(record.get("response"), Mapping)
    ]
    scores = [score_evaluation(record) for record in scored_records]
    total = len(scores)

    # Cases with expected_whiskey_id = null have no retrievable answer -- the
    # correct behaviour is to abstain. Counting them in the top-1/top-3
    # denominators scores correct abstention as a miss: a system that is right
    # on every bottle and correctly abstains on every glass-only photo would
    # report 50% top-1. Retrieval metrics therefore only cover cases that have
    # an answer to retrieve; abstention is measured on its own denominator.
    retrievable = [
        score
        for score, record in zip(scores, scored_records)
        if record["case"]["expected_whiskey_id"] is not None
    ]
    unanswerable = [
        score
        for score, record in zip(scores, scored_records)
        if record["case"]["expected_whiskey_id"] is None
    ]
    retrievable_total = len(retrievable)
    unanswerable_total = len(unanswerable)
    top1 = sum(score["top1_correct"] for score in retrievable)
    top3 = sum(score["top3_correct"] for score in retrievable)
    confirmed_correct = sum(score["confirmed_correct"] for score in scores)
    confirmed_wrong = sum(score["confirmed_wrong"] for score in scores)
    not_confirmed = sum(score["not_confirmed"] for score in scores)
    # False confirmation spans every case: confirming the wrong product and
    # confirming anything at all on an unanswerable photo are both failures.
    false_confirmations = confirmed_wrong
    rejections = sum(score["rejected"] for score in scores)
    no_candidates = sum(score["no_candidates"] for score in scores)
    misses = sum(score["not_confirmed"] for score in retrievable)
    correct_abstentions = sum(score["not_confirmed"] for score in unanswerable)
    return {
        "cases": total,
        "retrievable_cases": retrievable_total,
        "unanswerable_cases": unanswerable_total,
        "confirmed_correct": confirmed_correct,
        "confirmed_correct_rate": _rate(confirmed_correct, total),
        "confirmed_wrong": confirmed_wrong,
        "confirmed_wrong_rate": _rate(confirmed_wrong, total),
        "not_confirmed": not_confirmed,
        "not_confirmed_rate": _rate(not_confirmed, total),
        "top1_correct": top1,
        "top1_accuracy": _rate(top1, retrievable_total),
        "top3_correct": top3,
        "top3_accuracy": _rate(top3, retrievable_total),
        "false_confirmations": false_confirmations,
        "false_confirmation_rate": _rate(false_confirmations, total),
        "rejections": rejections,
        "rejection_rate": _rate(rejections, total),
        "no_candidates": no_candidates,
        "no_candidates_rate": _rate(no_candidates, total),
        "misses": misses,
        "miss_rate": _rate(misses, retrievable_total),
        "correct_abstentions": correct_abstentions,
        "correct_abstention_rate": _rate(correct_abstentions, unanswerable_total),
    }


def calculate_metrics(
    records: Sequence[Mapping[str, Any]],
    conditions: Sequence[str] = CONDITIONS,
) -> dict[str, Any]:
    """Calculate overall and per-condition metrics as a pure function."""
    overall = _aggregate_records(records)
    by_condition = {
        condition: _aggregate_records(
            [record for record in records if record["case"]["condition"] == condition]
        )
        for condition in conditions
    }
    false_confirmation_cases = []
    for record in records:
        if record.get("status_code", 200) != 200 or not isinstance(
            record.get("response"), Mapping
        ):
            continue
        score = score_evaluation(record)
        if score["false_confirmation"]:
            false_confirmation_cases.append(
                {
                    "case_index": record.get("case_index"),
                    "image": record["case"]["image"],
                    "condition": record["case"]["condition"],
                    "expected_whiskey_id": record["case"]["expected_whiskey_id"],
                    "expected_canonical_name": record["case"]["expected_canonical_name"],
                    "actual_whiskey_id": score["actual_whiskey_id"],
                    "actual_brand_text": score["actual_brand_text"],
                    "match_source": score["match_source"],
                }
            )
    return {
        "attempted_cases": len(records),
        "scored_cases": overall["cases"],
        "error_cases": len(records) - overall["cases"],
        "overall": overall,
        "by_condition": by_condition,
        "false_confirmation_cases": false_confirmation_cases,
    }


def format_rate(count: int, total: int, rate: float | None) -> str:
    """Format a metric without presenting an empty denominator as zero percent."""
    if rate is None:
        return "該当なし"
    return f"{count}/{total} ({rate * 100:.1f}%)"


def _format_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    widths = [
        max((len(row[index]) for row in rows), default=len(headers[index]))
        for index in range(len(headers))
    ]
    header = " | ".join(value.ljust(widths[index]) for index, value in enumerate(headers))
    separator = "-+-".join("-" * width for width in widths)
    body = [
        " | ".join(value.ljust(widths[index]) for index, value in enumerate(row))
        for row in rows
    ]
    return "\n".join((header, separator, *body))


def _metric_row(label: str, aggregate: Mapping[str, Any]) -> list[str]:
    total = aggregate["cases"]
    # Top-1/Top-3 are rated over cases that have an answer to retrieve;
    # correct abstention is rated over the cases that have none.
    retrievable = aggregate["retrievable_cases"]
    unanswerable = aggregate["unanswerable_cases"]
    return [
        label,
        str(total),
        format_rate(
            aggregate["confirmed_correct"],
            total,
            aggregate["confirmed_correct_rate"],
        ),
        format_rate(
            aggregate["confirmed_wrong"],
            total,
            aggregate["confirmed_wrong_rate"],
        ),
        format_rate(
            aggregate["not_confirmed"],
            total,
            aggregate["not_confirmed_rate"],
        ),
        format_rate(aggregate["top1_correct"], retrievable, aggregate["top1_accuracy"]),
        format_rate(aggregate["top3_correct"], retrievable, aggregate["top3_accuracy"]),
        format_rate(
            aggregate["false_confirmations"],
            total,
            aggregate["false_confirmation_rate"],
        ),
        format_rate(aggregate["misses"], retrievable, aggregate["miss_rate"]),
        format_rate(
            aggregate["correct_abstentions"],
            unanswerable,
            aggregate["correct_abstention_rate"],
        ),
        format_rate(aggregate["rejections"], total, aggregate["rejection_rate"]),
        format_rate(
            aggregate["no_candidates"],
            total,
            aggregate["no_candidates_rate"],
        ),
    ]


def print_metrics_report(metrics: Mapping[str, Any]) -> None:
    """Print overall metrics, condition metrics, and false confirmations."""
    headers = (
        "Scope",
        "Cases",
        "Confirmed correct",
        "Confirmed wrong",
        "Not confirmed",
        "Top-1",
        "Top-3",
        "False confirmation",
        "Miss",
        "Correct abstention",
        "Rejection (diagnostic)",
        "No candidates (diagnostic)",
    )
    print("\nOverall")
    print(_format_table(headers, [_metric_row("ALL", metrics["overall"])]))
    print("\nBy condition")
    condition_rows = [
        _metric_row(condition, aggregate)
        for condition, aggregate in metrics["by_condition"].items()
    ]
    print(_format_table(headers, condition_rows))
    print("\nFalse confirmations")
    false_cases = metrics["false_confirmation_cases"]
    if not false_cases:
        print("None")
        return
    false_headers = ("Case", "Image", "Expected", "Actual brand_text", "match_source")
    false_rows = [
        [
            str(case["case_index"]),
            str(case["image"]),
            str(case["expected_canonical_name"] or case["expected_whiskey_id"]),
            str(case["actual_brand_text"] or "-"),
            str(case["match_source"] or "-"),
        ]
        for case in false_cases
    ]
    print(_format_table(false_headers, false_rows))


def print_manifest_report(manifest: Mapping[str, Any]) -> None:
    """Print dry-run case totals and a complete condition breakdown."""
    counts = Counter(case["condition"] for case in manifest["cases"])
    print(f"Manifest version: {manifest['version']}")
    print(f"Cases: {len(manifest['cases'])}")
    print("Conditions:")
    for condition in CONDITIONS:
        print(f"  {condition}: {counts[condition]}")


def select_case_indices(
    case_count: int,
    successful_indices: Iterable[int],
    max_cases: int | None,
) -> list[int]:
    """Select pending cases and enforce the default 20-case protection."""
    completed = set(successful_indices)
    pending = [index for index in range(case_count) if index not in completed]
    if max_cases is None:
        if len(pending) > DEFAULT_MAX_CASES:
            raise ValueError(
                f"{len(pending)} pending cases exceeds the default maximum "
                f"of {DEFAULT_MAX_CASES}; specify --max-cases explicitly"
            )
        return pending
    if max_cases <= 0:
        raise ValueError("--max-cases must be greater than zero")
    return pending[:max_cases]


def estimate_counter_increments(case_count: int) -> int:
    """Estimate the minimum counter increments consumed by analyze."""
    return case_count * MIN_COUNTER_INCREMENTS_PER_CASE


def estimate_counter_increment_range(case_count: int) -> tuple[int, int]:
    """Return minimum and maximum total counter increments."""
    return (
        case_count * MIN_COUNTER_INCREMENTS_PER_CASE,
        case_count * MAX_COUNTER_INCREMENTS_PER_CASE,
    )


def load_resume_results(path: Path, expected_digest: str) -> list[dict[str, Any]]:
    """Load successful and failed prior records after checking manifest identity."""
    try:
        with path.open(encoding="utf-8") as result_file:
            document = json.load(result_file)
    except json.JSONDecodeError as exc:
        raise ResultFileError(f"resume file is not valid JSON: {exc}") from exc
    if not isinstance(document, dict) or document.get("result_version") != RESULT_VERSION:
        raise ResultFileError("resume file has an unsupported result version")
    if document.get("manifest_sha256") != expected_digest:
        raise ResultFileError("resume file was produced from a different manifest")
    results = document.get("results")
    if not isinstance(results, list) or any(not isinstance(item, dict) for item in results):
        raise ResultFileError("resume file results must be an array of objects")
    for index, item in enumerate(results):
        if not isinstance(item.get("case"), Mapping):
            raise ResultFileError(f"resume file results[{index}] is missing a case object")
    return results


def successful_case_indices(records: Sequence[Mapping[str, Any]]) -> set[int]:
    """Return indices with an existing successful Lambda response."""
    return {
        record["case_index"]
        for record in records
        if isinstance(record.get("case_index"), int)
        and record.get("status_code") == 200
        and isinstance(record.get("response"), Mapping)
    }


def _replace_record(
    records: Sequence[Mapping[str, Any]],
    replacement: Mapping[str, Any],
) -> list[dict[str, Any]]:
    by_index = {
        record["case_index"]: dict(record)
        for record in records
        if isinstance(record.get("case_index"), int)
    }
    by_index[replacement["case_index"]] = dict(replacement)
    return [by_index[index] for index in sorted(by_index)]


def _json_default(value: Any) -> Any:
    if hasattr(value, "to_eng_string"):
        return value.to_eng_string()
    raise TypeError(f"cannot serialize {type(value).__name__}")


def save_json_atomic(path: Path, document: Mapping[str, Any]) -> None:
    """Atomically replace a JSON result file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(
            document,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_json_default,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def build_result_document(
    *,
    manifest_path: Path,
    digest: str,
    eval_user: str,
    records: Sequence[Mapping[str, Any]],
    selected_case_count: int,
    total_case_count: int,
    interrupted: bool,
    interruption_reason: str | None,
    started_at: str,
) -> dict[str, Any]:
    """Build the machine-readable result and resume document."""
    successful = successful_case_indices(records)
    return {
        "result_version": RESULT_VERSION,
        "manifest": str(manifest_path.resolve()),
        "manifest_sha256": digest,
        "target": "dev",
        "eval_user": eval_user,
        "started_at": started_at,
        "updated_at": utc_now_text(),
        "selected_case_count": selected_case_count,
        "total_case_count": total_case_count,
        "successful_case_count": len(successful),
        "remaining_case_count": total_case_count - len(successful),
        "interrupted": interrupted,
        "interruption_reason": interruption_reason,
        "results": list(records),
        "metrics": calculate_metrics(records),
    }


def create_dev_clients(profile: str | None) -> tuple[Any, Any, Any, str]:
    """Create verified dev S3/Lambda clients and the AppState table."""
    forbidden = sorted(
        name
        for name, value in os.environ.items()
        if value and (name == "AWS_ENDPOINT_URL" or name.startswith("AWS_ENDPOINT_URL_"))
    )
    if forbidden:
        raise ValueError(f"dev target forbids endpoint variables: {', '.join(forbidden)}")
    if not profile:
        raise ValueError("--target dev requires an explicit --profile")
    session = boto3.Session(profile_name=profile, region_name=REGION)
    identity = session.client("sts", config=CLIENT_CONFIG).get_caller_identity()
    account = identity.get("Account")
    if account != DEV_ACCOUNT_ID:
        raise ValueError(f"dev target requires AWS account {DEV_ACCOUNT_ID}; got {account}")
    print(f"Verified dev account: {account} ({identity['Arn']})")
    app_state_table = session.resource(
        "dynamodb",
        config=CLIENT_CONFIG,
    ).Table(APP_STATE_TABLE_NAME)
    return (
        session.client("s3", config=CLIENT_CONFIG),
        session.client("lambda", config=CLIENT_CONFIG),
        app_state_table,
        f"{BUCKET_PREFIX}-{account}",
    )


def resolve_cognito_audience(lambda_client: Any, override: str | None = None) -> str:
    """Resolve the analyze Lambda Cognito client ID or use an explicit override."""
    if override is not None:
        audience = override.strip()
        if not audience:
            raise ValueError("--aud must be a non-empty Cognito client ID")
        return audience
    try:
        configuration = lambda_client.get_function_configuration(
            FunctionName=FUNCTION_NAME
        )
        audience = (
            configuration.get("Environment", {})
            .get("Variables", {})
            .get("COGNITO_CLIENT_ID")
        )
    except (BotoCoreError, ClientError, AttributeError) as exc:
        raise ValueError(
            f"unable to resolve COGNITO_CLIENT_ID from {FUNCTION_NAME}; "
            "provide --aud to override it"
        ) from exc
    if not isinstance(audience, str) or not audience.strip():
        raise ValueError(
            f"{FUNCTION_NAME} has no non-empty COGNITO_CLIENT_ID; "
            "provide --aud to override it"
        )
    return audience.strip()


def read_global_daily_usage(
    app_state_table: Any,
    now: datetime | None = None,
) -> int:
    """Read today's analyze global counter without modifying it."""
    current = now or datetime.now(timezone.utc)
    key = f"drinklog-counter#analyze#global#{current.strftime('%Y-%m-%d')}"
    response = app_state_table.get_item(
        Key={"pk": key},
        ConsistentRead=True,
        ProjectionExpression="#count",
        ExpressionAttributeNames={"#count": "count"},
    )
    item = response.get("Item", {})
    count = item.get("count", 0) if isinstance(item, Mapping) else 0
    if isinstance(count, bool):
        raise ValueError("global daily counter has an invalid boolean count")
    try:
        usage = int(count)
    except (TypeError, ValueError) as exc:
        raise ValueError("global daily counter has a non-numeric count") from exc
    if usage < 0:
        raise ValueError("global daily counter has a negative count")
    return usage


def build_analyze_event(
    s3_key: str,
    eval_user: str,
    audience: str,
) -> dict[str, Any]:
    """Build the API Gateway event accepted by the analyze Lambda."""
    return {
        "httpMethod": "POST",
        "path": "/api/drink-logs/analyze",
        "body": json.dumps({"s3_key": s3_key}),
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": eval_user,
                    "token_use": "id",
                    "aud": audience,
                }
            }
        },
    }


def _read_payload(payload: Any) -> bytes:
    try:
        return payload.read()
    finally:
        close = getattr(payload, "close", None)
        if close:
            close()


def invoke_analyze(lambda_client: Any, event: Mapping[str, Any]) -> tuple[int, dict[str, Any]]:
    """Invoke the analyze Lambda and unpack its API Gateway response."""
    invocation = lambda_client.invoke(
        FunctionName=FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps(event).encode("utf-8"),
    )
    payload = json.loads(_read_payload(invocation["Payload"]))
    if invocation.get("FunctionError"):
        return 500, {
            "error": "Lambda function error",
            "function_error": invocation["FunctionError"],
            "payload": payload,
        }
    if not isinstance(payload, dict) or "statusCode" not in payload:
        raise ValueError("Lambda response is not an API Gateway response")
    status_code = int(payload["statusCode"])
    raw_body = payload.get("body", "{}")
    if not isinstance(raw_body, str):
        raise ValueError("Lambda API Gateway body must be a JSON string")
    body = json.loads(raw_body)
    if not isinstance(body, dict):
        raise ValueError("Lambda response body must be a JSON object")
    return status_code, body


def execute_case(
    *,
    case: Mapping[str, Any],
    manifest_path: Path,
    eval_user: str,
    bucket: str,
    s3_client: Any,
    lambda_client: Any,
    audience: str,
) -> tuple[int, dict[str, Any], str]:
    """Upload, invoke, and always request deletion of one temporary image."""
    image_path = manifest_path.parent / case["image"]
    extension = image_path.suffix.lower()
    s3_key = f"tmp/{eval_user}/{uuid.uuid4()}{extension}"
    content_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    try:
        s3_client.upload_file(
            str(image_path),
            bucket,
            s3_key,
            ExtraArgs={"ContentType": content_type},
        )
        status_code, response = invoke_analyze(
            lambda_client,
            build_analyze_event(s3_key, eval_user, audience),
        )
        return status_code, response, s3_key
    finally:
        original_error = sys.exc_info()[1]
        try:
            s3_client.delete_object(Bucket=bucket, Key=s3_key)
        except (BotoCoreError, ClientError) as cleanup_error:
            message = (
                f"failed to delete temporary evaluation image s3://{bucket}/{s3_key}: "
                f"{type(cleanup_error).__name__}: {cleanup_error}"
            )
            if original_error is not None:
                message += (
                    f"; original error was {type(original_error).__name__}: "
                    f"{original_error}"
                )
            error = CleanupError(
                message,
                original_error=original_error,
                cleanup_error=cleanup_error,
            )
            raise error from (original_error or cleanup_error)


def execute_evaluation(
    *,
    manifest: Mapping[str, Any],
    manifest_path: Path,
    selected_indices: Sequence[int],
    eval_user: str,
    bucket: str,
    s3_client: Any,
    lambda_client: Any,
    audience: str,
    output_path: Path,
    previous_records: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Execute selected cases, checkpoint each result, and stop on non-200."""
    validate_image_files(manifest, manifest_path, selected_indices)
    digest = manifest_digest(manifest)
    started_at = utc_now_text()
    records = [dict(record) for record in previous_records]
    interrupted = False
    interruption_reason: str | None = None

    for position, case_index in enumerate(selected_indices, start=1):
        case = manifest["cases"][case_index]
        print(f"[{position}/{len(selected_indices)}] {case['image']}")
        record: dict[str, Any] = {
            "case_index": case_index,
            "case": dict(case),
            "attempted_at": utc_now_text(),
        }
        try:
            status_code, response, s3_key = execute_case(
                case=case,
                manifest_path=manifest_path,
                eval_user=eval_user,
                bucket=bucket,
                s3_client=s3_client,
                lambda_client=lambda_client,
                audience=audience,
            )
            record.update(
                {
                    "status_code": status_code,
                    "response": response,
                    "temporary_s3_key": s3_key,
                }
            )
            if status_code != 200:
                interrupted = True
                response_text = json.dumps(
                    response,
                    ensure_ascii=False,
                    sort_keys=True,
                    default=_json_default,
                )
                interruption_reason = (
                    f"analyze returned HTTP {status_code}; response body: {response_text}"
                )
        except CleanupError as exc:
            record["error"] = str(exc)
            if exc.original_error is not None:
                record["original_error"] = (
                    f"{type(exc.original_error).__name__}: {exc.original_error}"
                )
            if exc.cleanup_error is not None:
                record["cleanup_error"] = (
                    f"{type(exc.cleanup_error).__name__}: {exc.cleanup_error}"
                )
            interrupted = True
            interruption_reason = "temporary S3 object cleanup failed"
        except (BotoCoreError, ClientError, OSError, ValueError, json.JSONDecodeError) as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"

        records = _replace_record(records, record)
        document = build_result_document(
            manifest_path=manifest_path,
            digest=digest,
            eval_user=eval_user,
            records=records,
            selected_case_count=len(selected_indices),
            total_case_count=len(manifest["cases"]),
            interrupted=interrupted,
            interruption_reason=interruption_reason,
            started_at=started_at,
        )
        save_json_atomic(output_path, document)
        if interrupted:
            break

    document = build_result_document(
        manifest_path=manifest_path,
        digest=digest,
        eval_user=eval_user,
        records=records,
        selected_case_count=len(selected_indices),
        total_case_count=len(manifest["cases"]),
        interrupted=interrupted,
        interruption_reason=interruption_reason,
        started_at=started_at,
    )
    save_json_atomic(output_path, document)
    return document


def default_result_path() -> Path:
    """Return a non-overwriting default result filename in the current directory."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path(f"brand-eval-results-{stamp}.json")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Evaluate whiskey brand recognition")
    parser.add_argument("manifest", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--target", choices=("dev",))
    mode.add_argument("--dry-run", action="store_true")
    parser.add_argument("--profile", help="explicit AWS profile required for --target dev")
    parser.add_argument(
        "--aud",
        help="override the analyze Lambda COGNITO_CLIENT_ID audience",
    )
    parser.add_argument("--eval-user", default="brand-eval")
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--yes", action="store_true", help="skip the cost confirmation prompt")
    parser.add_argument("--json", dest="json_path", type=Path)
    parser.add_argument("--resume", type=Path, help="resume from a prior JSON result")
    return parser.parse_args(argv)


def _print_cost_estimate(case_count: int, global_daily_usage: int | None) -> None:
    minimum, maximum = estimate_counter_increment_range(case_count)
    global_minimum = case_count * MIN_GLOBAL_DAILY_INCREMENTS_PER_CASE
    global_maximum = case_count * MAX_GLOBAL_DAILY_INCREMENTS_PER_CASE
    print(
        f"Will run {case_count} cases and consume {minimum}-{maximum} counter increments "
        f"({case_count} user daily, {global_minimum}-{global_maximum} global daily, "
        f"{global_minimum}-{global_maximum} global monthly)."
    )
    if global_maximum > ANALYZE_GLOBAL_DAILY_LIMIT / 2:
        print(
            f"WARNING: maximum global daily consumption ({global_maximum}) exceeds "
            f"half of the {ANALYZE_GLOBAL_DAILY_LIMIT}-request daily limit."
        )
    if global_daily_usage is not None:
        remaining = max(0, ANALYZE_GLOBAL_DAILY_LIMIT - global_daily_usage)
        print(
            f"Current global daily usage: {global_daily_usage}/"
            f"{ANALYZE_GLOBAL_DAILY_LIMIT}; remaining: {remaining}."
        )
        if global_maximum > remaining:
            print(
                f"WARNING: maximum projected global daily consumption "
                f"({global_maximum}) exceeds the remaining {remaining} slots."
            )


def _confirm_execution(case_count: int, global_daily_usage: int | None = None) -> bool:
    _print_cost_estimate(case_count, global_daily_usage)
    try:
        answer = input("Continue with billable dev evaluation? [y/N] ")
    except EOFError:
        print("Confirmation input unavailable; evaluation aborted.", file=sys.stderr)
        return False
    return answer.strip().lower() in {"y", "yes"}


def main(argv: list[str] | None = None) -> int:
    """Run local validation or the guarded dev evaluation."""
    args = parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
        if args.dry_run:
            if args.resume:
                raise ValueError("--resume is only valid with --target dev")
            if args.aud is not None:
                raise ValueError("--aud is only valid with --target dev")
            validate_image_files(manifest, args.manifest)
            print_manifest_report(manifest)
            if args.json_path:
                save_json_atomic(
                    args.json_path,
                    {
                        "manifest_version": manifest["version"],
                        "manifest_sha256": manifest_digest(manifest),
                        "cases": len(manifest["cases"]),
                        "conditions": dict(
                            Counter(case["condition"] for case in manifest["cases"])
                        ),
                    },
                )
            return 0

        if not EVAL_USER_RE.fullmatch(args.eval_user):
            raise ValueError("--eval-user may not contain slashes or whitespace")
        digest = manifest_digest(manifest)
        previous_records: list[dict[str, Any]] = []
        if args.resume:
            previous_records = load_resume_results(args.resume, digest)
        selected_indices = select_case_indices(
            len(manifest["cases"]),
            successful_case_indices(previous_records),
            args.max_cases,
        )
        if not selected_indices:
            print("All cases already have successful results.")
            print_metrics_report(calculate_metrics(previous_records))
            return 0
        validate_image_files(manifest, args.manifest, selected_indices)
        s3_client, lambda_client, app_state_table, bucket = create_dev_clients(args.profile)
        audience = resolve_cognito_audience(lambda_client, args.aud)
        global_daily_usage: int | None = None
        try:
            global_daily_usage = read_global_daily_usage(app_state_table)
        except (BotoCoreError, ClientError, ValueError) as exc:
            print(f"Global daily counter unavailable: {exc}", file=sys.stderr)

        if not args.yes and not _confirm_execution(
            len(selected_indices),
            global_daily_usage,
        ):
            print("Evaluation cancelled.")
            return 1
        if args.yes:
            _print_cost_estimate(len(selected_indices), global_daily_usage)

        validate_image_files(manifest, args.manifest, selected_indices)
        output_path = args.json_path or args.resume or default_result_path()
        document = execute_evaluation(
            manifest=manifest,
            manifest_path=args.manifest,
            selected_indices=selected_indices,
            eval_user=args.eval_user,
            bucket=bucket,
            s3_client=s3_client,
            lambda_client=lambda_client,
            audience=audience,
            output_path=output_path,
            previous_records=previous_records,
        )
        print_metrics_report(document["metrics"])
        print(f"\nJSON result: {output_path}")
        if document["interrupted"]:
            print(f"Stopped: {document['interruption_reason']}", file=sys.stderr)
            return 2
        return 0
    except (
        BotoCoreError,
        ClientError,
        ImageValidationError,
        ManifestError,
        OSError,
        ProfileNotFound,
        ResultFileError,
        ValueError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
