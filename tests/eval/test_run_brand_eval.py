import io
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from tests.lambda_module_loader import load_lambda_module


brand_eval = load_lambda_module(
    "run_brand_eval_script_tests",
    "scripts/eval/run_brand_eval.py",
)
jwt_utils = load_lambda_module(
    "brand_eval_jwt_utils_tests",
    "lambda/common/python/whiskey_common/jwt_utils.py",
)
analyze = load_lambda_module(
    "brand_eval_analyze_contract_tests",
    "lambda/drink-log-analyze/index.py",
)
synthetic_labels = load_lambda_module(
    "make_synthetic_labels_script_tests",
    "scripts/eval/make_synthetic_labels.py",
)


def _case(condition, expected_id, image="images/test.jpg"):
    return {
        "image": image,
        "condition": condition,
        "expected_whiskey_id": expected_id,
        "expected_canonical_name": expected_id,
    }


def _record(index, case, candidates, status_code=200):
    return {
        "case_index": index,
        "case": case,
        "status_code": status_code,
        "response": {"candidates": candidates},
    }


def _clear_endpoint_environment(monkeypatch):
    for name in tuple(brand_eval.os.environ):
        if name == "AWS_ENDPOINT_URL" or name.startswith("AWS_ENDPOINT_URL_"):
            monkeypatch.delenv(name, raising=False)


def test_calculate_metrics_uses_top_candidate_partition_and_separate_denominators():
    records = [
        _record(
            0,
            _case("bottle_front", "a"),
            [{"whiskey_id": "a", "brand_text": "A", "match_source": "exact"}],
        ),
        _record(
            1,
            _case("bottle_front", "b"),
            [
                {"whiskey_id": "wrong", "brand_text": "Wrong", "match_source": "fuzzy"},
                {"whiskey_id": "b"},
            ],
        ),
        _record(
            2,
            _case("bottle_angle", "c"),
            [{"brand_text": "unresolved", "match_source": "unresolved"}],
        ),
        _record(
            3,
            _case("bottle_angle", "d"),
            [{"brand_text": "unresolved"}, {"whiskey_id": "d"}],
        ),
        _record(
            4,
            _case("glass_only", None),
            [{"whiskey_id": "invented", "brand_text": "Invented", "match_source": "fuzzy"}],
        ),
    ]

    metrics = brand_eval.calculate_metrics(records)
    overall = metrics["overall"]

    assert overall == {
        "cases": 5,
        "retrievable_cases": 4,
        "unanswerable_cases": 1,
        "confirmed_correct": 1,
        "confirmed_correct_rate": pytest.approx(0.2),
        "confirmed_wrong": 2,
        "confirmed_wrong_rate": pytest.approx(0.4),
        "not_confirmed": 2,
        "not_confirmed_rate": pytest.approx(0.4),
        "top1_correct": 1,
        "top1_accuracy": pytest.approx(0.25),
        "top3_correct": 3,
        "top3_accuracy": pytest.approx(0.75),
        "false_confirmations": 2,
        "false_confirmation_rate": pytest.approx(0.4),
        "rejections": 1,
        "rejection_rate": pytest.approx(0.2),
        "no_candidates": 0,
        "no_candidates_rate": pytest.approx(0.0),
        "misses": 2,
        "miss_rate": pytest.approx(0.5),
        "correct_abstentions": 0,
        "correct_abstention_rate": pytest.approx(0.0),
    }
    assert metrics["by_condition"]["bottle_front"]["top3_correct"] == 2
    assert metrics["by_condition"]["bottle_angle"]["rejections"] == 1


def test_unresolved_top_candidate_with_resolved_second_candidate_is_not_confirmed():
    record = _record(
        0,
        _case("bottle_angle", "a"),
        [{"brand_text": "garbage"}, {"whiskey_id": "a", "brand_text": "A"}],
    )

    score = brand_eval.score_evaluation(record)
    overall = brand_eval.calculate_metrics([record])["overall"]

    assert score["not_confirmed"] is True
    assert score["rejected"] is False
    assert overall["not_confirmed"] == 1
    assert overall["misses"] == 1
    assert overall["miss_rate"] == pytest.approx(1.0)


def test_empty_candidates_are_counted_separately_from_unresolved_candidates():
    records = [
        _record(0, _case("bottle_front", "a"), []),
        _record(1, _case("bottle_front", "b"), [{"brand_text": "unresolved"}]),
    ]

    overall = brand_eval.calculate_metrics(records)["overall"]

    assert overall["not_confirmed"] == 2
    assert overall["rejections"] == 2
    assert overall["no_candidates"] == 1
    assert overall["no_candidates_rate"] == pytest.approx(0.5)


def test_confirmation_partition_sums_to_each_scope_denominator():
    records = [
        _record(0, _case("bottle_front", "a"), [{"whiskey_id": "a"}]),
        _record(1, _case("bottle_front", "b"), [{"whiskey_id": "wrong"}]),
        _record(2, _case("bottle_angle", "c"), [{"brand_text": "unresolved"}]),
        _record(3, _case("glass_only", None), []),
    ]

    metrics = brand_eval.calculate_metrics(records)

    for aggregate in [metrics["overall"], *metrics["by_condition"].values()]:
        assert (
            aggregate["confirmed_correct"]
            + aggregate["confirmed_wrong"]
            + aggregate["not_confirmed"]
            == aggregate["cases"]
        )


def test_null_expected_id_with_confirmation_is_false_confirmation():
    record = _record(
        0,
        _case("glass_only", None),
        [{"whiskey_id": "yamazaki-12", "brand_text": "山崎 12年"}],
    )

    score = brand_eval.score_evaluation(record)

    assert score["confirmed_wrong"] is True
    assert score["false_confirmation"] is True
    assert score["top1_correct"] is False
    assert score["not_confirmed"] is False
    assert score["rejected"] is False


def test_empty_condition_uses_none_rate_and_no_cases_label():
    metrics = brand_eval.calculate_metrics(
        [_record(0, _case("bottle_front", "a"), [{"whiskey_id": "a"}])]
    )

    empty = metrics["by_condition"]["back_label_only"]
    assert empty["cases"] == 0
    assert empty["top1_accuracy"] is None
    assert empty["false_confirmation_rate"] is None
    assert empty["not_confirmed_rate"] is None
    assert brand_eval.format_rate(0, 0, empty["top1_accuracy"]) == "該当なし"


def test_format_table_accepts_no_rows():
    assert brand_eval._format_table(("A", "Long"), []) == "A | Long\n--+-----"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda manifest: manifest["cases"][0].update({"condition": "studio"}),
            "condition is unknown",
        ),
        (
            lambda manifest: manifest["cases"][0].pop("image"),
            "missing required fields: image",
        ),
        (
            lambda manifest: manifest["cases"][0].pop("expected_whiskey_id"),
            "missing required fields: expected_whiskey_id",
        ),
        (
            lambda manifest: manifest["cases"][0].update(
                {"expected_canonical_name": None}
            ),
            "expected_canonical_name is required",
        ),
    ],
)
def test_manifest_validation_rejects_invalid_cases(mutate, message):
    manifest = {"version": 1, "cases": [_case("bottle_front", "a")]}
    mutate(manifest)

    with pytest.raises(brand_eval.ManifestError, match=message):
        brand_eval.validate_manifest_data(manifest)


def test_manifest_validation_accepts_uppercase_image_extension():
    manifest = {"version": 1, "cases": [_case("bottle_front", "a", "images/test.JPEG")]}

    assert brand_eval.validate_manifest_data(manifest) == manifest


def test_manifest_validation_rejects_non_boolean_needs_review():
    case = _case("bottle_front", "a")
    case["needs_review"] = "false"

    with pytest.raises(brand_eval.ManifestError, match="needs_review must be a boolean"):
        brand_eval.validate_manifest_data({"version": 1, "cases": [case]})


def test_draft_manifest_matches_schema_and_marks_every_case_for_review(tmp_path):
    image_directory = tmp_path / "images-real"
    image_directory.mkdir()
    for name in ("first.jpg", "second.jpg"):
        (image_directory / name).write_bytes(b"\xff\xd8\xffplaceholder")
    manifest_path = tmp_path / "manifest.real.json"
    seed = brand_eval.build_draft_seed_manifest(image_directory, manifest_path)
    records = [
        _record(
            0,
            seed["cases"][0],
            [{"name_ja": "山崎 12年", "whiskey_id": "yamazaki-12"}],
        ),
        _record(
            1,
            seed["cases"][1],
            [{"brand_text": "不明なボトル"}],
        ),
    ]

    draft = brand_eval.build_draft_manifest(seed, records)

    jsonschema = pytest.importorskip("jsonschema")
    schema_path = Path(brand_eval.__file__).with_name("manifest.schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(draft)
    assert all(case["needs_review"] is True for case in draft["cases"])
    assert all(case["condition"] == "bottle_front" for case in draft["cases"])
    assert all(case["notes"] == brand_eval.DRAFT_NOTES for case in draft["cases"])
    assert draft["cases"][0]["expected_whiskey_id"] == "yamazaki-12"
    assert draft["cases"][0]["expected_canonical_name"] == "山崎 12年"
    assert draft["cases"][1]["expected_whiskey_id"] is None
    assert draft["cases"][1]["expected_canonical_name"] == "不明なボトル"


def test_draft_manifest_rejects_case_without_successful_response():
    seed = {"version": 1, "cases": [_case("bottle_front", None, "photo.jpg")]}

    with pytest.raises(ValueError, match="case 0 has no successful response"):
        brand_eval.build_draft_manifest(seed, [])


def test_load_manifest_rejects_draft_until_all_cases_are_reviewed(tmp_path):
    case = _case("bottle_front", "a", "photo.jpg")
    case["needs_review"] = True
    manifest = {"version": 1, "cases": [case]}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(brand_eval.ManifestError, match="needs_review=true"):
        brand_eval.load_manifest(manifest_path)

    case["needs_review"] = False
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    loaded = brand_eval.load_manifest(manifest_path)
    score = brand_eval.score_evaluation(
        _record(0, loaded["cases"][0], [{"whiskey_id": "a"}])
    )
    assert score["confirmed_correct"] is True


def test_dry_run_exits_nonzero_when_manifest_still_needs_review(tmp_path, capsys):
    case = _case("bottle_front", "a", "photo.jpg")
    case["needs_review"] = True
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"version": 1, "cases": [case]}),
        encoding="utf-8",
    )

    assert brand_eval.main([str(manifest_path), "--dry-run"]) == 1
    assert "needs_review=true" in capsys.readouterr().err


def test_image_validation_reports_all_missing_empty_oversize_and_magic_errors(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    (images / "empty.png").write_bytes(b"")
    (images / "large.jpg").write_bytes(
        b"\xff\xd8\xff" + b"x" * brand_eval.UPLOAD_MAX_BYTES
    )
    (images / "invalid.webp").write_bytes(b"not-an-image")
    manifest = {
        "version": 1,
        "cases": [
            _case("bottle_front", "a", "images/missing.jpg"),
            _case("bottle_angle", "b", "images/empty.png"),
            _case("box_only", "c", "images/large.jpg"),
            _case("miniature", "d", "images/invalid.webp"),
        ],
    }

    with pytest.raises(brand_eval.ImageValidationError) as raised:
        brand_eval.validate_image_files(manifest, tmp_path / "manifest.json")

    message = str(raised.value)
    assert "4 problem(s)" in message
    assert "missing.jpg" in message
    assert "file is empty" in message
    assert "exceeds the 3670016-byte upload limit" in message
    assert "magic bytes are not JPEG, PNG, or WebP" in message


@pytest.mark.parametrize(
    ("name", "contents", "expected"),
    [
        ("missing.jpg", None, "does not exist"),
        (
            "large.jpg",
            b"\xff\xd8\xff" + b"x" * brand_eval.UPLOAD_MAX_BYTES,
            "exceeds the 3670016-byte upload limit",
        ),
    ],
)
def test_dry_run_returns_nonzero_for_invalid_images(
    tmp_path, monkeypatch, capsys, name, contents, expected
):
    image_path = tmp_path / name
    if contents is not None:
        image_path.write_bytes(contents)
    manifest = {"version": 1, "cases": [_case("bottle_front", "a", name)]}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(
        brand_eval,
        "create_dev_clients",
        lambda _profile: pytest.fail("dry-run must not create AWS clients"),
    )

    assert brand_eval.main(["--dry-run", str(manifest_path)]) == 1
    assert expected in capsys.readouterr().err


def test_default_case_limit_rejects_more_than_twenty_pending_cases():
    with pytest.raises(ValueError, match="--max-cases"):
        brand_eval.select_case_indices(21, set(), None)

    assert brand_eval.select_case_indices(21, set(), 21) == list(range(21))
    assert brand_eval.select_case_indices(21, set(), 5) == list(range(5))


@pytest.mark.parametrize(
    "variable",
    ["AWS_ENDPOINT_URL", "AWS_ENDPOINT_URL_S3", "AWS_ENDPOINT_URL_CUSTOM"],
)
def test_dev_clients_reject_endpoint_environment(monkeypatch, variable):
    _clear_endpoint_environment(monkeypatch)
    monkeypatch.setenv(variable, "http://localhost:4566")
    monkeypatch.setattr(
        brand_eval.boto3,
        "Session",
        lambda **_kwargs: pytest.fail("session must not be created"),
    )

    with pytest.raises(ValueError, match=variable):
        brand_eval.create_dev_clients("dev")


def test_dev_clients_reject_missing_profile(monkeypatch):
    _clear_endpoint_environment(monkeypatch)
    monkeypatch.setattr(
        brand_eval.boto3,
        "Session",
        lambda **_kwargs: pytest.fail("session must not be created"),
    )

    with pytest.raises(ValueError, match="explicit --profile"):
        brand_eval.create_dev_clients(None)


def test_dev_clients_reject_wrong_sts_account(monkeypatch):
    _clear_endpoint_environment(monkeypatch)
    session = Mock()
    session.client.return_value.get_caller_identity.return_value = {
        "Account": "000000000000",
        "Arn": "arn:aws:iam::000000000000:user/wrong",
    }
    monkeypatch.setattr(brand_eval.boto3, "Session", lambda **kwargs: session)

    with pytest.raises(ValueError, match=brand_eval.DEV_ACCOUNT_ID):
        brand_eval.create_dev_clients("dev")


def test_cognito_audience_is_resolved_from_lambda_configuration():
    lambda_client = Mock()
    lambda_client.get_function_configuration.return_value = {
        "Environment": {"Variables": {"COGNITO_CLIENT_ID": "resolved-client"}}
    }

    assert brand_eval.resolve_cognito_audience(lambda_client) == "resolved-client"
    lambda_client.get_function_configuration.assert_called_once_with(
        FunctionName=brand_eval.FUNCTION_NAME
    )


def test_cognito_audience_override_avoids_configuration_lookup():
    lambda_client = Mock()

    assert brand_eval.resolve_cognito_audience(lambda_client, "override-client") == (
        "override-client"
    )
    lambda_client.get_function_configuration.assert_not_called()


def test_missing_cognito_audience_has_clear_error():
    lambda_client = Mock()
    lambda_client.get_function_configuration.return_value = {
        "Environment": {"Variables": {}}
    }

    with pytest.raises(ValueError, match=r"COGNITO_CLIENT_ID.*--aud"):
        brand_eval.resolve_cognito_audience(lambda_client)


def test_build_analyze_event_passes_real_authorizer_validation(monkeypatch):
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "pool-123")
    monkeypatch.setenv("COGNITO_CLIENT_ID", "client-123")
    monkeypatch.setenv("AWS_REGION", "ap-northeast-1")
    event = brand_eval.build_analyze_event(
        "tmp/eval-user/00000000-0000-4000-8000-000000000000.jpg",
        "eval-user",
        "client-123",
    )

    assert jwt_utils.extract_user_id_from_event(event) == "eval-user"


def test_read_global_daily_usage_is_read_only():
    table = Mock()
    table.get_item.return_value = {"Item": {"count": 17}}
    now = datetime(2026, 7, 26, tzinfo=timezone.utc)

    assert brand_eval.read_global_daily_usage(table, now) == 17
    table.get_item.assert_called_once_with(
        Key={"pk": "drinklog-counter#analyze#global#2026-07-26"},
        ConsistentRead=True,
        ProjectionExpression="#count",
        ExpressionAttributeNames={"#count": "count"},
    )


def test_cost_estimate_shows_range_warning_and_remaining_slots(capsys):
    brand_eval._print_cost_estimate(20, 9)

    output = capsys.readouterr().out
    assert "60-100 counter increments" in output
    assert "20-40 global daily" in output
    assert "exceeds half" in output
    assert "remaining: 41" in output


def test_confirmation_handles_noninteractive_stdin(monkeypatch, capsys):
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt: (_ for _ in ()).throw(EOFError()),
    )

    assert brand_eval._confirm_execution(1) is False
    assert "evaluation aborted" in capsys.readouterr().err


class StubS3:
    def __init__(self, delete_error=None):
        self.uploads = []
        self.deletes = []
        self.delete_error = delete_error

    def upload_file(self, filename, bucket, key, ExtraArgs):
        self.uploads.append((filename, bucket, key, ExtraArgs))

    def delete_object(self, **kwargs):
        self.deletes.append(kwargs)
        if self.delete_error is not None:
            raise self.delete_error


class StubLambda:
    def __init__(self, statuses):
        self.statuses = iter(statuses)
        self.calls = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        status, body = next(self.statuses)
        proxy_response = {
            "statusCode": status,
            "body": json.dumps(body),
        }
        return {"Payload": io.BytesIO(json.dumps(proxy_response).encode("utf-8"))}


class FailingLambda:
    def invoke(self, **kwargs):
        raise brand_eval.ClientError(
            {"Error": {"Code": "ServiceException", "Message": "failed"}},
            "Invoke",
        )


def test_emit_manifest_cli_uses_image_directory_and_writes_review_draft(
    tmp_path, monkeypatch
):
    image_directory = tmp_path / "images-real"
    image_directory.mkdir()
    (image_directory / "photo.jpg").write_bytes(b"\xff\xd8\xffplaceholder")
    manifest_path = tmp_path / "manifest.json"
    result_path = tmp_path / "result.json"
    s3 = StubS3()
    lambda_client = StubLambda(
        [
            (
                200,
                {
                    "candidates": [
                        {
                            "name_ja": "カリラ 12年",
                            "whiskey_id": "caol-ila-12",
                        }
                    ]
                },
            )
        ]
    )
    app_state = Mock()
    app_state.get_item.return_value = {"Item": {"count": 0}}
    monkeypatch.setattr(
        brand_eval,
        "create_dev_clients",
        lambda _profile: (s3, lambda_client, app_state, "images-dev"),
    )

    exit_code = brand_eval.main(
        [
            str(image_directory),
            "--target",
            "dev",
            "--emit-manifest",
            str(manifest_path),
            "--profile",
            "dev",
            "--aud",
            "client-123",
            "--max-cases",
            "1",
            "--yes",
            "--json",
            str(result_path),
        ]
    )

    assert exit_code == 0
    draft = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert draft["cases"][0]["needs_review"] is True
    assert draft["cases"][0]["expected_whiskey_id"] == "caol-ila-12"
    assert draft["cases"][0]["expected_canonical_name"] == "カリラ 12年"
    assert result_path.is_file()
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["mode"] == "manifest_draft"
    assert result["manifest"] == manifest_path.name
    assert len(s3.uploads) == 1
    assert len(s3.deletes) == 1


def test_partial_emit_manifest_writes_no_manifest_and_reports_pending(
    tmp_path, monkeypatch, capsys
):
    image_directory = tmp_path / "images-real"
    image_directory.mkdir()
    for name in ("first.jpg", "second.jpg"):
        (image_directory / name).write_bytes(b"\xff\xd8\xffplaceholder")
    manifest_path = tmp_path / "manifest.json"
    result_path = tmp_path / "result.json"
    s3 = StubS3()
    lambda_client = StubLambda([(200, {"candidates": []})])
    app_state = Mock()
    app_state.get_item.return_value = {"Item": {"count": 0}}
    monkeypatch.setattr(
        brand_eval,
        "create_dev_clients",
        lambda _profile: (s3, lambda_client, app_state, "images-dev"),
    )

    exit_code = brand_eval.main(
        [
            str(image_directory),
            "--target",
            "dev",
            "--emit-manifest",
            str(manifest_path),
            "--profile",
            "dev",
            "--aud",
            "client-123",
            "--max-cases",
            "1",
            "--yes",
            "--json",
            str(result_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert not manifest_path.exists()
    assert "Manifest draft pending: 1 case(s) remain" in captured.out
    assert json.loads(result_path.read_text(encoding="utf-8"))["mode"] == (
        "manifest_draft"
    )


def test_emit_manifest_refuses_existing_file_unless_force(tmp_path, capsys):
    image_directory = tmp_path / "images-real"
    image_directory.mkdir()
    (image_directory / "photo.jpg").write_bytes(b"\xff\xd8\xffplaceholder")
    manifest_path = tmp_path / "manifest.json"
    original = b'{"reviewed_labels":"must survive"}\n'
    manifest_path.write_bytes(original)
    seed = brand_eval.build_draft_seed_manifest(image_directory, manifest_path)
    resume_path = tmp_path / "resume.json"
    brand_eval.save_json_atomic(
        resume_path,
        {
            "result_version": brand_eval.RESULT_VERSION,
            "manifest_sha256": brand_eval.manifest_digest(seed),
            "results": [_record(0, seed["cases"][0], [])],
        },
    )
    base_args = [
        str(image_directory),
        "--target",
        "dev",
        "--emit-manifest",
        str(manifest_path),
        "--resume",
        str(resume_path),
    ]

    assert brand_eval.main(base_args) == 1
    assert manifest_path.read_bytes() == original
    assert "may contain reviewed labels" in capsys.readouterr().err

    assert brand_eval.main([*base_args, "--force"]) == 0
    draft = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert draft["cases"][0]["needs_review"] is True


def test_result_manifest_path_is_repository_relative_or_basename(tmp_path, monkeypatch):
    repository_root = tmp_path / "repository"
    monkeypatch.setattr(brand_eval, "REPOSITORY_ROOT", repository_root)

    assert brand_eval.repository_relative_path(
        repository_root / "scripts/eval/manifest.real.json"
    ) == "scripts/eval/manifest.real.json"
    assert brand_eval.repository_relative_path(
        tmp_path / "private/manifest.real.json"
    ) == "manifest.real.json"


def test_execute_evaluation_validates_images_before_any_upload(tmp_path):
    case = _case("bottle_front", "a", "images/missing.jpg")
    s3 = StubS3()
    lambda_client = StubLambda([(200, {"candidates": []})])

    with pytest.raises(brand_eval.ImageValidationError, match="missing.jpg"):
        brand_eval.execute_evaluation(
            manifest={"version": 1, "cases": [case]},
            manifest_path=tmp_path / "manifest.json",
            selected_indices=[0],
            eval_user="brand-eval",
            bucket="images-dev",
            s3_client=s3,
            lambda_client=lambda_client,
            audience="client-123",
            output_path=tmp_path / "result.json",
        )

    assert s3.uploads == []
    assert lambda_client.calls == []


def test_generated_s3_key_matches_analyze_upload_contract(tmp_path):
    case = _case("bottle_front", "a", "images/0.jpg")
    images = tmp_path / "images"
    images.mkdir()
    (images / "0.jpg").write_bytes(b"\xff\xd8\xffplaceholder")
    s3 = StubS3()

    status, _response, s3_key = brand_eval.execute_case(
        case=case,
        manifest_path=tmp_path / "manifest.json",
        eval_user="brand-eval",
        bucket="images-dev",
        s3_client=s3,
        lambda_client=StubLambda([(200, {"candidates": []})]),
        audience="client-123",
    )

    assert status == 200
    assert analyze.UPLOAD_KEY_RE.fullmatch(s3_key)


def test_temporary_image_is_deleted_when_lambda_invoke_fails(tmp_path):
    case = _case("bottle_front", "a", "images/0.jpg")
    images = tmp_path / "images"
    images.mkdir()
    (images / "0.jpg").write_bytes(b"\xff\xd8\xffplaceholder")
    s3 = StubS3()

    with pytest.raises(brand_eval.ClientError):
        brand_eval.execute_case(
            case=case,
            manifest_path=tmp_path / "manifest.json",
            eval_user="brand-eval",
            bucket="images-dev",
            s3_client=s3,
            lambda_client=FailingLambda(),
            audience="client-123",
        )

    assert len(s3.uploads) == 1
    assert len(s3.deletes) == 1


def test_cleanup_error_preserves_original_error_and_interrupts(tmp_path):
    case = _case("bottle_front", "a", "images/0.jpg")
    images = tmp_path / "images"
    images.mkdir()
    (images / "0.jpg").write_bytes(b"\xff\xd8\xffplaceholder")
    cleanup_client_error = brand_eval.ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "delete denied"}},
        "DeleteObject",
    )
    output_path = tmp_path / "result.json"

    document = brand_eval.execute_evaluation(
        manifest={"version": 1, "cases": [case]},
        manifest_path=tmp_path / "manifest.json",
        selected_indices=[0],
        eval_user="brand-eval",
        bucket="images-dev",
        s3_client=StubS3(delete_error=cleanup_client_error),
        lambda_client=FailingLambda(),
        audience="client-123",
        output_path=output_path,
    )

    assert document["interrupted"] is True
    assert document["mode"] == "evaluation"
    assert document["manifest"] == "manifest.json"
    assert document["interruption_reason"] == "temporary S3 object cleanup failed"
    assert "ServiceException" in document["results"][0]["original_error"]
    assert "AccessDenied" in document["results"][0]["cleanup_error"]
    assert json.loads(output_path.read_text(encoding="utf-8"))["interrupted"] is True


@pytest.mark.parametrize("status_code", [401, 403, 400, 429, 503])
def test_non_200_response_stops_and_checkpoints_results(tmp_path, status_code):
    cases = [
        _case("bottle_front", "a", f"images/{index}.jpg")
        for index in range(3)
    ]
    manifest = {"version": 1, "cases": cases}
    images = tmp_path / "images"
    images.mkdir()
    for index in range(3):
        (images / f"{index}.jpg").write_bytes(b"\xff\xd8\xffplaceholder")
    s3 = StubS3()
    lambda_client = StubLambda(
        [
            (
                status_code,
                {"error": "Authentication required", "detail": "systematic failure"},
            ),
            (200, {"candidates": [{"whiskey_id": "a"}]}),
        ]
    )
    output_path = tmp_path / "result.json"

    document = brand_eval.execute_evaluation(
        manifest=manifest,
        manifest_path=tmp_path / "manifest.json",
        selected_indices=[0, 1, 2],
        eval_user="brand-eval",
        bucket="images-dev",
        s3_client=s3,
        lambda_client=lambda_client,
        audience="client-123",
        output_path=output_path,
    )

    assert document["interrupted"] is True
    assert f"HTTP {status_code}" in document["interruption_reason"]
    assert "Authentication required" in document["interruption_reason"]
    assert [result.get("status_code") for result in document["results"]] == [status_code]
    assert len(lambda_client.calls) == 1
    assert len(s3.uploads) == 1
    assert len(s3.deletes) == 1
    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved["interrupted"] is True
    assert saved["results"][0]["response"]["detail"] == "systematic failure"
    assert saved["metrics"]["scored_cases"] == 0


def test_invoke_analyze_function_error_branch():
    payload = {"errorMessage": "handler crashed"}
    lambda_client = Mock()
    lambda_client.invoke.return_value = {
        "FunctionError": "Unhandled",
        "Payload": io.BytesIO(json.dumps(payload).encode("utf-8")),
    }

    status, body = brand_eval.invoke_analyze(lambda_client, {"event": "value"})

    assert status == 500
    assert body == {
        "error": "Lambda function error",
        "function_error": "Unhandled",
        "payload": payload,
    }


def test_resume_round_trip_skips_success_and_retries_failure(tmp_path):
    cases = [
        _case("bottle_front", "a", "images/0.jpg"),
        _case("bottle_angle", "b", "images/1.jpg"),
    ]
    manifest = {"version": 1, "cases": cases}
    images = tmp_path / "images"
    images.mkdir()
    (images / "1.jpg").write_bytes(b"\xff\xd8\xffplaceholder")
    digest = brand_eval.manifest_digest(manifest)
    resume_path = tmp_path / "resume.json"
    prior_records = [
        _record(0, cases[0], [{"whiskey_id": "a"}]),
        {
            "case_index": 1,
            "case": cases[1],
            "status_code": 401,
            "response": {"error": "Authentication required"},
        },
    ]
    brand_eval.save_json_atomic(
        resume_path,
        {
            "result_version": brand_eval.RESULT_VERSION,
            "manifest_sha256": digest,
            "results": prior_records,
        },
    )

    loaded = brand_eval.load_resume_results(resume_path, digest)
    selected = brand_eval.select_case_indices(
        len(cases),
        brand_eval.successful_case_indices(loaded),
        None,
    )
    assert selected == [1]

    lambda_client = StubLambda([(200, {"candidates": [{"whiskey_id": "b"}]})])
    result = brand_eval.execute_evaluation(
        manifest=manifest,
        manifest_path=tmp_path / "manifest.json",
        selected_indices=selected,
        eval_user="brand-eval",
        bucket="images-dev",
        s3_client=StubS3(),
        lambda_client=lambda_client,
        audience="client-123",
        output_path=resume_path,
        previous_records=loaded,
    )

    assert len(lambda_client.calls) == 1
    assert [record["status_code"] for record in result["results"]] == [200, 200]
    assert result["successful_case_count"] == 2


def test_resume_rejects_manifest_digest_mismatch(tmp_path):
    path = tmp_path / "resume.json"
    path.write_text(
        json.dumps(
            {
                "result_version": brand_eval.RESULT_VERSION,
                "manifest_sha256": "old",
                "results": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(brand_eval.ResultFileError, match="different manifest"):
        brand_eval.load_resume_results(path, "new")


def test_resume_record_missing_case_raises_result_file_error(tmp_path):
    path = tmp_path / "resume.json"
    path.write_text(
        json.dumps(
            {
                "result_version": brand_eval.RESULT_VERSION,
                "manifest_sha256": "digest",
                "results": [{"case_index": 0, "status_code": 500}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(brand_eval.ResultFileError, match="missing a case object"):
        brand_eval.load_resume_results(path, "digest")


def test_correct_abstention_is_not_scored_as_a_retrieval_miss():
    records = [
        _record(0, _case("bottle_front", "a"), [{"whiskey_id": "a", "brand_text": "A"}]),
        _record(1, _case("glass_only", None), [{"brand_text": "unresolved"}]),
    ]

    overall = brand_eval.calculate_metrics(records)["overall"]

    assert overall["top1_accuracy"] == pytest.approx(1.0)
    assert overall["top3_accuracy"] == pytest.approx(1.0)
    assert overall["false_confirmation_rate"] == pytest.approx(0.0)
    assert overall["correct_abstention_rate"] == pytest.approx(1.0)


def test_over_confirming_system_is_penalised_on_every_axis():
    records = [
        _record(0, _case("bottle_front", "a"), [{"whiskey_id": "wrong", "brand_text": "W"}]),
        _record(1, _case("glass_only", None), [{"whiskey_id": "invented", "brand_text": "I"}]),
    ]

    overall = brand_eval.calculate_metrics(records)["overall"]

    assert overall["top1_accuracy"] == pytest.approx(0.0)
    assert overall["false_confirmation_rate"] == pytest.approx(1.0)
    assert overall["miss_rate"] == pytest.approx(0.0)
    assert overall["correct_abstention_rate"] == pytest.approx(0.0)


def test_unanswerable_only_scope_reports_no_retrieval_denominator():
    records = [_record(0, _case("glass_only", None), [{"brand_text": "unresolved"}])]

    overall = brand_eval.calculate_metrics(records)["overall"]

    assert overall["top1_accuracy"] is None
    assert overall["miss_rate"] is None
    assert brand_eval.format_rate(0, 0, None) == "該当なし"


@pytest.mark.parametrize(
    ("name", "expected_brand", "expected_age"),
    [
        ("The Glenlivet 12 Year Old", "The Glenlivet", "12"),
        ("Ardbeg 10YO", "Ardbeg", "10"),
        ("Nikka From The Barrel", "Nikka From The Barrel", None),
    ],
)
def test_synthetic_label_parts_extract_brand_and_age(
    name, expected_brand, expected_age
):
    assert synthetic_labels._label_parts({"name_en": name}) == (
        expected_brand,
        expected_age,
    )
