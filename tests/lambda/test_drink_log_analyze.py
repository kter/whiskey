import io
import json
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError
from PIL import Image

from tests.lambda_module_loader import load_lambda_module


analyze = load_lambda_module("drink_log_analyze_tests", "lambda/drink-log-analyze/index.py")
drink_logs = load_lambda_module("drink_logs_analysis_contract_tests", "lambda/drink-logs/index.py")

SONNET_MODEL_ID = "jp.anthropic.claude-sonnet-4-6"
CAOL_ILA_ITEM = {
    "id": "caol-ila-12",
    "name": "カリラ 12年",
    "name_ja": "カリラ 12年",
    "name_en": "Caol Ila 12 Year Old",
    "normalized_name": "かりら12年|caolila12yearold",
}


class TransactionCanceled(Exception):
    def __init__(self, reasons=None):
        self.response = {"CancellationReasons": reasons or []}
        super().__init__("transaction cancelled")


class RecordingClient:
    exceptions = SimpleNamespace(TransactionCanceledException=TransactionCanceled)

    def __init__(self):
        self.transactions = []

    def transact_write_items(self, **kwargs):
        self.transactions.append(kwargs["TransactItems"])


class AppStateTable:
    def __init__(self):
        self.items = {}

    def put_item(self, *, Item):
        self.items[Item["pk"]] = dict(Item)

    def get_item(self, *, Key, **kwargs):
        del kwargs
        item = self.items.get(Key["pk"])
        return {"Item": dict(item)} if item else {}


class WhiskeyTable:
    def __init__(self, items=None, pages=None):
        self.items = [dict(item) for item in (items if items is not None else [CAOL_ILA_ITEM])]
        self.pages = pages
        self.scan_calls = []

    def scan(self, **kwargs):
        self.scan_calls.append(kwargs)
        if self.pages is not None:
            return self.pages[len(self.scan_calls) - 1]
        return {"Items": [dict(item) for item in self.items]}


class FakeDynamoDB:
    def __init__(self, app=None, whiskeys=None):
        self.meta = SimpleNamespace(client=RecordingClient())
        self.app = app or AppStateTable()
        self.whiskeys = whiskeys or WhiskeyTable()

    def Table(self, name):
        if name == "AppState-test":
            return self.app
        if name == "WhiskeySearch-test":
            return self.whiskeys
        raise AssertionError(name)


class MemoryS3:
    def __init__(self, key, body, etag='"etag-1"'):
        self.key = key
        self.body = body
        self.etag = etag
        self.get_calls = []

    def head_object(self, *, Bucket, Key):
        assert Bucket == "images-test"
        assert Key == self.key
        return {
            "ContentLength": len(self.body),
            "ContentType": "image/png",
            "ETag": self.etag,
        }

    def get_object(self, **kwargs):
        self.get_calls.append(kwargs)
        assert kwargs["Bucket"] == "images-test"
        assert kwargs["Key"] == self.key
        if "Range" in kwargs:
            assert kwargs["Range"] == "bytes=0-15"
            return {"Body": io.BytesIO(self.body[:16])}
        assert kwargs["IfMatch"] == self.etag
        return {"Body": io.BytesIO(self.body)}


class Context:
    aws_request_id = "request-1"

    def __init__(self, remaining=28_000):
        self.remaining = remaining

    def get_remaining_time_in_millis(self):
        return self.remaining


class SequencedContext(Context):
    """Return a different remaining time on each call.

    Lets a test give the model call enough budget while leaving the work that
    follows it short, which is where the post-invoke guards matter.
    """

    def __init__(self, remaining_values):
        super().__init__()
        self.remaining_values = iter(remaining_values)
        self.last = 0

    def get_remaining_time_in_millis(self):
        self.last = next(self.remaining_values, self.last)
        return self.last


class Bedrock:
    def __init__(self, texts):
        self.texts = list(texts)
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        text = self.texts.pop(0)
        return {"output": {"message": {"content": [{"text": text}]}}}


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    analyze._reset_master_cache()
    values = {
        "ENVIRONMENT": "dev",
        "APP_STATE_TABLE": "AppState-test",
        "WHISKEY_SEARCH_TABLE": "WhiskeySearch-test",
        "IMAGES_BUCKET": "images-test",
        "COGNITO_USER_POOL_ID": "ap-northeast-1_pool",
        "COGNITO_CLIENT_ID": "client-123",
        "AWS_REGION": "ap-northeast-1",
        "BEDROCK_MODEL_ID": SONNET_MODEL_ID,
        "BEDROCK_MODEL_ALLOWLIST": (
            "jp.amazon.nova-2-lite-v1:0,"
            "jp.anthropic.claude-haiku-4-5-20251001-v1:0,"
            f"{SONNET_MODEL_ID}"
        ),
        "ANALYZE_USER_DAILY_LIMIT": "20",
        "ANALYZE_GLOBAL_DAILY_LIMIT": "50",
        "ANALYZE_GLOBAL_MONTHLY_LIMIT": "1000",
        "IMAGE_MAX_BYTES": "1572864",
        "UPLOAD_MAX_BYTES": "3670016",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("MOCK_AI", raising=False)
    monkeypatch.delenv("MOCK_PLACES", raising=False)


def _snapshot(items, *, complete=True):
    return {
        "table_name": "WhiskeySearch-test",
        "expires_at": analyze.time.monotonic() + 300,
        "items": tuple(analyze._snapshot_record(item) for item in items),
        "complete": complete,
        "incomplete_reason": None if complete else "scan_error",
        "page_count": 1,
    }


def _analysis(whiskeys, serving_style="NEAT", glass_type="tumbler"):
    return {
        "whiskeys": whiskeys,
        "serving_style": serving_style,
        "glass_type": glass_type,
    }


def _whiskey(name_ja, name_en="", confidence=0.9):
    return {
        "name_ja": name_ja,
        "name_en": name_en,
        "confidence": Decimal(str(confidence)),
    }


def _model_json(whiskeys, serving_style="NEAT", glass_type="tumbler"):
    serializable = [
        {
            "name_ja": whiskey["name_ja"],
            "name_en": whiskey.get("name_en", ""),
            **(
                {"brand_ja": whiskey["brand_ja"]}
                if "brand_ja" in whiskey
                else {}
            ),
            **(
                {"brand_en": whiskey["brand_en"]}
                if "brand_en" in whiskey
                else {}
            ),
            "confidence": float(whiskey.get("confidence", 0.9)),
        }
        for whiskey in whiskeys
    ]
    return json.dumps(
        {
            "whiskeys": serializable,
            "serving_style": serving_style,
            "glass_type": glass_type,
        },
        ensure_ascii=False,
    )


def _png_bytes():
    image = Image.new("RGBA", (40, 20), (255, 0, 0, 128))
    output = io.BytesIO()
    image.save(output, format="PNG", pnginfo=None)
    return output.getvalue()


def _event(key):
    return {
        "httpMethod": "POST",
        "path": "/api/drink-logs/analyze",
        "body": json.dumps({"s3_key": key}),
        "requestContext": {
            "authorizer": {
                "claims": {"sub": "user-1", "aud": "client-123", "token_use": "id"}
            }
        },
    }


def _wire_handler(monkeypatch, dynamodb, s3, bedrock):
    monkeypatch.setattr(analyze, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(analyze, "get_s3_client", lambda: s3)
    monkeypatch.setattr(analyze, "_bedrock_client", lambda timeout: bedrock)


@pytest.mark.parametrize(
    "text",
    [
        '{"whiskeys":[],"serving_style":"NEAT","glass_type":"tumbler"}',
        '```json\n{"whiskeys":[],"serving_style":"NEAT","glass_type":"tumbler"}\n```',
    ],
)
def test_fenced_and_plain_json_are_accepted(monkeypatch, text):
    bedrock = Bedrock([text])
    monkeypatch.setattr(analyze, "_bedrock_client", lambda timeout: bedrock)

    result = analyze._invoke_model(
        SONNET_MODEL_ID, b"jpeg", Context(), analyze.time.monotonic()
    )

    assert result == {
        "whiskeys": [],
        "serving_style": "NEAT",
        "glass_type": "tumbler",
    }
    assert bedrock.calls[0]["inferenceConfig"] == {
        "maxTokens": 512,
        "temperature": 0,
    }
    assert bedrock.calls[0]["modelId"] == SONNET_MODEL_ID


def test_prompt_requires_llm_first_multi_bottle_non_inventing_output():
    assert "正式な日本語表記" in analyze.PROMPT
    assert "熟成年数が読み取れる場合は必ず" in analyze.PROMPT
    assert "空配列" in analyze.PROMPT
    assert "推測しない" in analyze.PROMPT
    assert "複数のボトル" in analyze.PROMPT
    assert "全て列挙" in analyze.PROMPT
    assert "補完しない" in analyze.PROMPT
    assert "brand_ja" in analyze.PROMPT
    assert "brand_en" in analyze.PROMPT
    assert "蒸留所またはブランドの名前だけ" in analyze.PROMPT
    assert "熟成年数・カスク・限定表記・シングルモルト等の種別語" in analyze.PROMPT
    assert "最も大きい文字ではなく" in analyze.PROMPT
    assert "brand_candidates" not in analyze.PROMPT
    assert "label_text" not in analyze.PROMPT


def test_model_output_validation_uses_new_schema_and_decimal_confidence():
    result = analyze._validate_model_output(
        {
            "whiskeys": [
                {
                    "name_ja": "カリラ 12年",
                    "name_en": "Caol Ila 12 Year Old",
                    "brand_ja": "カリラ",
                    "brand_en": "Caol Ila",
                    "confidence": 0.95,
                }
            ],
            "serving_style": "highball",
            "glass_type": "",
        }
    )

    assert result["serving_style"] == "SODA"
    assert result["whiskeys"][0]["confidence"] == Decimal("0.95")
    assert isinstance(result["whiskeys"][0]["confidence"], Decimal)
    assert result["whiskeys"][0]["brand_ja"] == "カリラ"
    assert result["whiskeys"][0]["brand_en"] == "Caol Ila"


def test_model_output_without_brand_fields_still_validates():
    payload = {
        "whiskeys": [
            {
                "name_ja": "カリラ 12年",
                "name_en": "Caol Ila 12 Year Old",
                "confidence": 0.95,
            }
        ],
        "serving_style": "NEAT",
        "glass_type": "",
    }

    assert analyze._validate_model_output(payload) is not None


def test_empty_brand_fields_degrade_to_legacy_candidate_shape():
    payload = {
        "whiskeys": [
            {
                "name_ja": "カリラ 12年",
                "name_en": "Caol Ila 12 Year Old",
                "brand_ja": "",
                "brand_en": "",
                "confidence": 0.95,
            }
        ],
        "serving_style": "NEAT",
        "glass_type": "",
    }

    result = analyze._validate_model_output(payload)

    assert set(result["whiskeys"][0]) == {"name_ja", "name_en", "confidence"}


def test_model_output_rejects_unknown_whiskey_key():
    payload = {
        "whiskeys": [
            {
                "name_ja": "カリラ 12年",
                "name_en": "Caol Ila 12 Year Old",
                "confidence": 0.95,
                "edition": "unknown key",
            }
        ],
        "serving_style": "NEAT",
        "glass_type": "",
    }

    assert analyze._validate_model_output(payload) is None


@pytest.mark.parametrize(
    ("brand_field", "brand_value"),
    [
        ("brand_ja", 123),
        ("brand_en", "a" * 201),
    ],
)
def test_model_output_rejects_invalid_brand_field_type_or_length(
    brand_field, brand_value
):
    whiskey = {
        "name_ja": "カリラ 12年",
        "name_en": "Caol Ila 12 Year Old",
        "confidence": 0.95,
        brand_field: brand_value,
    }
    payload = {
        "whiskeys": [whiskey],
        "serving_style": "NEAT",
        "glass_type": "",
    }

    assert analyze._validate_model_output(payload) is None


@pytest.mark.parametrize(
    "payload",
    [
        {
            "whiskeys": [{"name_ja": "", "name_en": "Yamazaki", "confidence": 0.9}],
            "serving_style": "NEAT",
            "glass_type": "",
        },
        {
            "whiskeys": [{"name_ja": " ", "name_en": "", "confidence": 0.9}],
            "serving_style": "NEAT",
            "glass_type": "",
        },
        {
            "whiskeys": [
                {"name_ja": str(index), "name_en": "", "confidence": 0.9}
                for index in range(6)
            ],
            "serving_style": "NEAT",
            "glass_type": "",
        },
        {
            "whiskeys": [],
            "serving_style": "NEAT",
            "glass_type": "",
            "label_text": "not accepted",
        },
    ],
)
def test_model_output_validation_rejects_invalid_new_schema(payload):
    assert analyze._validate_model_output(payload) is None


def test_model_read_is_never_upgraded_to_catalog_canonical_name():
    snapshot = _snapshot(
        [
            {
                "id": "yamazaki-12",
                "name_ja": "山崎 12年",
                "name_en": "Yamazaki 12 Year Old",
            }
        ]
    )

    candidates = analyze._build_candidates(
        snapshot,
        _analysis([_whiskey("山崎", "Yamazaki", 0.96)]),
    )

    assert candidates == [
        {
            "brand_text": "山崎",
            "name_ja": "山崎",
            "name_en": "Yamazaki",
            "confidence": Decimal("0.96"),
            "match_source": "ai",
        }
    ]


def test_normalized_exact_match_adds_id_without_overwriting_model_name():
    candidates = analyze._build_candidates(
        _snapshot([CAOL_ILA_ITEM]),
        _analysis([_whiskey("カリラ 12年", "Caol Ila 12 Year Old", 0.95)]),
    )

    assert candidates[0]["brand_text"] == "カリラ 12年"
    assert candidates[0]["name_ja"] == "カリラ 12年"
    assert candidates[0]["whiskey_id"] == "caol-ila-12"
    assert candidates[0]["match_source"] == "catalog"


def test_brand_only_does_not_match_age_statement():
    candidates = analyze._build_candidates(
        _snapshot([CAOL_ILA_ITEM]),
        _analysis([_whiskey("カリラ", "Caol Ila", 0.9)]),
    )

    assert candidates[0]["brand_text"] == "カリラ"
    assert candidates[0]["match_source"] == "ai"
    assert "whiskey_id" not in candidates[0]


def test_normalize_text_allows_spacing_variation_for_exact_match():
    snapshot = _snapshot(
        [{"id": "arran-10", "name_ja": "アラン 10年", "name_en": "Arran 10 Year Old"}]
    )

    candidates = analyze._build_candidates(
        snapshot,
        _analysis([_whiskey("アラン10年", "", 0.93)]),
    )

    assert candidates[0]["brand_text"] == "アラン10年"
    assert candidates[0]["whiskey_id"] == "arran-10"
    assert candidates[0]["match_source"] == "catalog"


def test_unknown_whiskey_still_produces_recordable_ai_candidate():
    candidates = analyze._build_candidates(
        _snapshot([CAOL_ILA_ITEM]),
        _analysis([_whiskey("厚岸 シングルモルト", "Akkeshi Single Malt", 0.91)]),
    )

    assert candidates == [
        {
            "brand_text": "厚岸 シングルモルト",
            "name_ja": "厚岸 シングルモルト",
            "name_en": "Akkeshi Single Malt",
            "confidence": Decimal("0.91"),
            "match_source": "ai",
        }
    ]


def test_brand_alias_match_is_independent_from_expression_match():
    whiskey = _whiskey("厚岸 立春", "Akkeshi Risshun", 0.91)
    whiskey.update(brand_ja="アッケシ", brand_en="Akkeshi")

    candidates = analyze._build_candidates(
        _snapshot([CAOL_ILA_ITEM]),
        _analysis([whiskey]),
    )

    assert candidates[0]["match_source"] == "ai"
    assert "whiskey_id" not in candidates[0]
    assert candidates[0]["brand_ja"] == "アッケシ"
    assert candidates[0]["brand_en"] == "Akkeshi"
    assert candidates[0]["brand_key"] == "akkeshi"
    assert candidates[0]["distillery_ja"] == "厚岸蒸溜所"


@pytest.mark.parametrize(
    ("brand_field", "brand_name"),
    [
        ("brand_ja", "遊佐蒸溜所"),
        ("brand_en", "The Yuza Distillery"),
    ],
)
def test_distillery_label_resolves_to_yuza(brand_field, brand_name):
    whiskey = _whiskey("遊佐 シングルモルト", "Yuza Single Malt")
    whiskey[brand_field] = brand_name

    candidate = analyze._build_candidates(
        _snapshot([CAOL_ILA_ITEM]),
        _analysis([whiskey]),
    )[0]

    assert candidate["brand_key"] == "yuza"


@pytest.mark.parametrize("model_brand", ["厚岸", "厚岸蒸留所"])
def test_catalog_distillery_suffix_and_kanji_variation_resolve_to_akkeshi(
    model_brand,
):
    akkeshi = next(
        brand for brand in analyze.BRAND_CATALOG if brand["brand_key"] == "akkeshi"
    )
    assert analyze.normalize_text("厚岸蒸溜所") in akkeshi["_normalized_names"]

    whiskey = _whiskey("厚岸 シングルモルト", "Akkeshi Single Malt")
    whiskey["brand_ja"] = model_brand

    candidate = analyze._build_candidates(
        _snapshot([CAOL_ILA_ITEM]),
        _analysis([whiskey]),
    )[0]

    assert candidate["brand_key"] == "akkeshi"


@pytest.mark.parametrize(
    ("brand_field", "brand_name"),
    [
        ("brand_ja", "ミドルトン蒸溜所"),
        ("brand_en", "Midleton Distillery"),
        ("brand_en", "Midleton"),
        ("brand_ja", "ニッカウヰスキー"),
        ("brand_en", "Nikka Whisky"),
    ],
)
def test_shared_distillery_name_does_not_attach_arbitrary_brand_key(
    brand_field, brand_name
):
    whiskey = _whiskey("共有蒸溜所のウイスキー", "Shared Distillery Whisky")
    whiskey[brand_field] = brand_name

    candidate = analyze._build_candidates(
        _snapshot([CAOL_ILA_ITEM]),
        _analysis([whiskey]),
    )[0]

    assert "brand_key" not in candidate


@pytest.mark.parametrize(
    ("brand_name", "expected_brand_key"),
    [
        ("Bruichladdich Distillery", "bruichladdich"),
        ("Buffalo Trace Distillery", "buffalo_trace"),
    ],
)
def test_brand_named_for_shared_distillery_takes_precedence(
    brand_name, expected_brand_key
):
    whiskey = _whiskey("同名ブランドのウイスキー", "Same-name Brand Whisky")
    whiskey["brand_en"] = brand_name

    candidate = analyze._build_candidates(
        _snapshot([CAOL_ILA_ITEM]),
        _analysis([whiskey]),
    )[0]

    assert candidate["brand_key"] == expected_brand_key


@pytest.mark.parametrize(
    ("brand_field", "brand_name"),
    [
        ("brand_ja", "蒸溜所"),
        ("brand_en", "The "),
        ("brand_en", "Distillery"),
    ],
)
def test_affix_only_brand_name_does_not_attach_brand_key(brand_field, brand_name):
    whiskey = _whiskey("接辞のみのウイスキー", "Affix-only Whisky")
    whiskey[brand_field] = brand_name

    candidate = analyze._build_candidates(
        _snapshot([CAOL_ILA_ITEM]),
        _analysis([whiskey]),
    )[0]

    assert "brand_key" not in candidate


def test_real_brand_catalog_normalized_names_never_include_empty_string():
    assert all(
        "" not in brand["_normalized_names"] for brand in analyze.BRAND_CATALOG
    )


@pytest.mark.parametrize(
    ("brand_field", "brand_name"),
    [
        ("brand_en", "Yuza Distillery Co."),
        ("brand_ja", "遊佐蒸溜所です"),
    ],
)
def test_distillery_affixes_are_removed_only_at_anchors(brand_field, brand_name):
    whiskey = _whiskey("遊佐ではないウイスキー", "Not Yuza Whisky")
    whiskey[brand_field] = brand_name

    candidate = analyze._build_candidates(
        _snapshot([CAOL_ILA_ITEM]),
        _analysis([whiskey]),
    )[0]

    assert "brand_key" not in candidate


def test_normalized_brand_name_variants_remove_only_complete_affixes():
    assert analyze.normalize_text("yuza") in analyze._normalized_brand_name_variants(
        "The Yuza Distillery"
    )
    assert analyze.normalize_text("遊佐") in analyze._normalized_brand_name_variants(
        "遊佐蒸溜所"
    )
    assert "" not in analyze._normalized_brand_name_variants("蒸溜所")
    assert analyze._normalized_brand_name_variants("Theakston") == (
        analyze.normalize_text("Theakston"),
    )


def test_brand_with_the_prefix_resolves_to_glenlivet():
    whiskey = _whiskey("ザ・グレンリベット", "The Glenlivet")
    whiskey["brand_en"] = "The Glenlivet"

    candidate = analyze._build_candidates(
        _snapshot([CAOL_ILA_ITEM]),
        _analysis([whiskey]),
    )[0]

    assert candidate["brand_key"] == "glenlivet"


def test_handler_accepts_brand_fields_and_returns_them_on_candidate(monkeypatch):
    key = f"tmp/user-1/{uuid.uuid4()}.png"
    dynamodb = FakeDynamoDB(whiskeys=WhiskeyTable(items=[]))
    bedrock = Bedrock(
        [
            _model_json(
                [
                    {
                        "name_ja": "厚岸 立春",
                        "name_en": "Akkeshi Risshun",
                        "brand_ja": "アッケシ",
                        "brand_en": "Akkeshi",
                        "confidence": 0.91,
                    }
                ]
            )
        ]
    )
    _wire_handler(monkeypatch, dynamodb, MemoryS3(key, _png_bytes()), bedrock)

    response = analyze.lambda_handler(_event(key), Context())
    candidate = json.loads(response["body"])["candidates"][0]

    assert response["statusCode"] == 200
    assert candidate["brand_ja"] == "アッケシ"
    assert candidate["brand_en"] == "Akkeshi"
    assert candidate["brand_key"] == "akkeshi"
    assert candidate["distillery_ja"] == "厚岸蒸溜所"
    assert "whiskey_id" not in candidate


def test_unmatched_brand_omits_catalog_brand_keys():
    whiskey = _whiskey("未登録ウイスキー", "Unlisted Whisky", 0.7)
    whiskey.update(brand_ja="未登録ブランド", brand_en="Unlisted Brand")

    candidate = analyze._build_candidates(
        _snapshot([CAOL_ILA_ITEM]),
        _analysis([whiskey]),
    )[0]

    assert candidate["brand_ja"] == "未登録ブランド"
    assert candidate["brand_en"] == "Unlisted Brand"
    assert "brand_key" not in candidate
    assert "distillery_ja" not in candidate


def test_brand_without_distillery_keeps_brand_key_and_omits_distillery(monkeypatch):
    # Synthetic rather than a real catalog row: whether any given brand has a
    # known distillery is data that changes, but the guard must not.
    monkeypatch.setattr(
        analyze,
        "BRAND_CATALOG",
        (
            {
                "brand_key": "unverified_brand",
                "distillery_ja": "",
                "_normalized_names": (analyze.normalize_text("Unverified Brand"),),
            },
        ),
    )
    whiskey = _whiskey("蒸溜所不明ウイスキー", "Unverified Brand Whisky", 0.9)
    whiskey.update(brand_en="unverified brand")

    candidate = analyze._build_candidates(
        _snapshot([CAOL_ILA_ITEM]),
        _analysis([whiskey]),
    )[0]

    assert candidate["brand_key"] == "unverified_brand"
    assert "distillery_ja" not in candidate


def test_packaged_brand_catalog_matches_curated_source():
    root = Path(__file__).resolve().parents[2]
    packaged = json.loads(
        (root / "lambda" / "drink-log-analyze" / "brands.json").read_text(
            encoding="utf-8"
        )
    )
    curated = json.loads(
        (root / "scripts" / "catalog" / "brands.json").read_text(encoding="utf-8")
    )

    assert packaged == curated


def test_real_brand_catalog_has_no_normalized_name_collisions():
    owners = {}
    for brand in analyze.BRAND_CATALOG:
        for normalized_name in brand["_normalized_names"]:
            owners.setdefault(normalized_name, set()).add(brand["brand_key"])
    collisions = {
        normalized_name: sorted(brand_keys)
        for normalized_name, brand_keys in owners.items()
        if len(brand_keys) > 1
    }
    details = ", ".join(
        f"{normalized_name}: {brand_keys}"
        for normalized_name, brand_keys in sorted(collisions.items())
    )

    assert not collisions, f"Normalized brand-name collisions: {details}"
    assert len(analyze.BRAND_CATALOG) == 60


def test_duplicate_exact_catalog_names_do_not_attach_an_arbitrary_id():
    snapshot = _snapshot(
        [
            {"id": "duplicate-1", "name_ja": "同名"},
            {"id": "duplicate-2", "name_ja": "同名"},
        ]
    )

    candidate = analyze._build_candidates(
        snapshot,
        _analysis([_whiskey("同名")]),
    )[0]

    assert candidate["match_source"] == "ai"
    assert "whiskey_id" not in candidate


def test_duplicate_normalized_brand_names_do_not_attach_arbitrary_keys(monkeypatch):
    normalized_name = analyze.normalize_text("Same Brand")
    monkeypatch.setattr(
        analyze,
        "BRAND_CATALOG",
        (
            {
                "brand_key": "duplicate_brand_1",
                "distillery_ja": "第一蒸溜所",
                "_normalized_names": (normalized_name,),
            },
            {
                "brand_key": "duplicate_brand_2",
                "distillery_ja": "第二蒸溜所",
                "_normalized_names": (analyze.normalize_text("ＳＡＭＥＢＲＡＮＤ"),),
            },
        ),
    )
    whiskey = _whiskey("同名ウイスキー", "Same Brand Whisky")
    whiskey.update(brand_en="same brand")

    candidate = analyze._build_candidates(
        _snapshot([CAOL_ILA_ITEM]),
        _analysis([whiskey]),
    )[0]

    assert "brand_key" not in candidate
    assert "distillery_ja" not in candidate


def test_incomplete_snapshot_never_attaches_catalog_id():
    candidate = analyze._build_candidates(
        _snapshot([CAOL_ILA_ITEM], complete=False),
        _analysis([_whiskey("カリラ 12年", "Caol Ila 12 Year Old")]),
    )[0]

    assert candidate["match_source"] == "ai"
    assert "whiskey_id" not in candidate


def test_handler_saves_exact_model_text_decimal_and_round_trips_to_create(monkeypatch):
    upload_uuid = "12345678-1234-4234-8234-123456789abc"
    key = f"tmp/user-1/{upload_uuid}.png"
    raw = _png_bytes()
    s3 = MemoryS3(key, raw)
    dynamodb = FakeDynamoDB()
    bedrock = Bedrock(
        [
            "```json\n"
            + _model_json(
                [
                    {
                        "name_ja": "カリラ 12年",
                        "name_en": "Caol Ila 12 Year Old",
                        "confidence": 0.91,
                    }
                ],
                serving_style="highball",
            )
            + "\n```"
        ]
    )
    _wire_handler(monkeypatch, dynamodb, s3, bedrock)

    response = analyze.lambda_handler(_event(key), Context())

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    analysis_id = f"ai-result:user-1:{upload_uuid}"
    assert body["analysis_id"] == analysis_id
    assert body["serving_style"] == "SODA"
    assert body["multiple_detected"] is False
    assert body["candidates"][0]["brand_text"] == "カリラ 12年"
    assert body["candidates"][0]["whiskey_id"] == "caol-ila-12"
    assert body["candidates"][0]["match_source"] == "catalog"

    sent_image = bedrock.calls[0]["messages"][0]["content"][0]["image"]["source"]["bytes"]
    assert sent_image.startswith(b"\xff\xd8\xff")
    assert sent_image != raw
    with Image.open(io.BytesIO(sent_image)) as normalized:
        assert normalized.mode == "RGB"
        assert not normalized.getexif()

    saved = dynamodb.app.items[analysis_id]
    assert saved["ETag"] == '"etag-1"'
    assert saved["user"] == "user-1"
    assert saved["ttl"] == saved["expires_at"]
    assert saved["confidence"] == Decimal("0.91")
    assert saved["candidates"][0]["confidence"] == Decimal("0.91")
    assert isinstance(saved["confidence"], Decimal)
    assert isinstance(saved["candidates"][0]["confidence"], Decimal)
    assert "label_text" not in saved
    assert "shortlist" not in saved
    assert [len(transaction) for transaction in dynamodb.meta.client.transactions] == [1, 2]

    pending, consume = drink_logs._prepare_initial_record(
        dynamodb,
        s3,
        "AppState-test",
        "images-test",
        "user-1",
        analysis_id,
        upload_uuid,
        0,
    )
    assert pending["_completion"]["brand_text"] == "カリラ 12年"
    assert pending["_completion"]["whiskey_id"] == "caol-ila-12"
    assert consume["Delete"]["ExpressionAttributeValues"][":candidate"] == saved["candidates"][0]


def test_two_whiskeys_create_two_candidates_and_multiple_detected(monkeypatch):
    key = f"tmp/user-1/{uuid.uuid4()}.png"
    dynamodb = FakeDynamoDB(
        whiskeys=WhiskeyTable(
            items=[
                {
                    "id": "glenlivet-12",
                    "name_ja": "ザ・グレンリベット 12年",
                    "name_en": "The Glenlivet 12 Year Old",
                }
            ]
        )
    )
    bedrock = Bedrock(
        [
            _model_json(
                [
                    {
                        "name_ja": "ザ・グレンリベット 12年",
                        "name_en": "The Glenlivet 12 Year Old",
                        "confidence": 0.95,
                    },
                    {
                        "name_ja": "ラガヴーリン 16年",
                        "name_en": "Lagavulin 16 Year Old",
                        "confidence": 0.94,
                    },
                ]
            )
        ]
    )
    _wire_handler(monkeypatch, dynamodb, MemoryS3(key, _png_bytes()), bedrock)

    response = analyze.lambda_handler(_event(key), Context())
    body = json.loads(response["body"])

    assert response["statusCode"] == 200
    assert body["multiple_detected"] is True
    assert [candidate["brand_text"] for candidate in body["candidates"]] == [
        "ザ・グレンリベット 12年",
        "ラガヴーリン 16年",
    ]
    assert [candidate["match_source"] for candidate in body["candidates"]] == [
        "catalog",
        "ai",
    ]


def test_empty_whiskeys_returns_zero_candidates_with_200(monkeypatch):
    key = f"tmp/user-1/{uuid.uuid4()}.png"
    dynamodb = FakeDynamoDB(whiskeys=WhiskeyTable(items=[]))
    bedrock = Bedrock([_model_json([])])
    _wire_handler(monkeypatch, dynamodb, MemoryS3(key, _png_bytes()), bedrock)

    response = analyze.lambda_handler(_event(key), Context())
    body = json.loads(response["body"])

    assert response["statusCode"] == 200
    assert body["candidates"] == []
    assert body["multiple_detected"] is False
    assert next(iter(dynamodb.app.items.values()))["candidates"] == []


def test_candidate_resolution_log_contains_counts_but_no_whiskey_names(monkeypatch, caplog):
    key = f"tmp/user-1/{uuid.uuid4()}.png"
    dynamodb = FakeDynamoDB()
    bedrock = Bedrock(
        [
            _model_json(
                [
                    {
                        "name_ja": "カリラ 12年",
                        "name_en": "Caol Ila 12 Year Old",
                        "confidence": 0.8,
                    },
                    {
                        "name_ja": "秘密の未登録銘柄",
                        "name_en": "Secret Unlisted Whisky",
                        "confidence": 0.7,
                    },
                ]
            )
        ]
    )
    _wire_handler(monkeypatch, dynamodb, MemoryS3(key, _png_bytes()), bedrock)

    with caplog.at_level("INFO", logger="drink-log-analyze"):
        response = analyze.lambda_handler(_event(key), Context())

    assert response["statusCode"] == 200
    assert "Brand candidates resolved" in caplog.text
    assert '"detected_count": 2' in caplog.text
    assert '"catalog": 1' in caplog.text
    assert '"ai": 1' in caplog.text
    assert '"whiskey_id_present_count": 1' in caplog.text
    assert f'"model_id": "{SONNET_MODEL_ID}"' in caplog.text
    assert '"master_snapshot_complete": true' in caplog.text
    assert '"master_snapshot_size": 1' in caplog.text
    assert all(
        value not in caplog.text
        for value in (
            "カリラ 12年",
            "Caol Ila 12 Year Old",
            "秘密の未登録銘柄",
            "Secret Unlisted Whisky",
        )
    )


def test_malformed_or_wrong_schema_output_retries_at_most_twice(monkeypatch):
    key = f"tmp/user-1/{uuid.uuid4()}.png"
    dynamodb = FakeDynamoDB(whiskeys=WhiskeyTable(items=[]))
    bedrock = Bedrock(
        [
            '{"brand_candidates":[],"serving_style":"NEAT","glass_type":""}',
            _model_json([]),
        ]
    )
    _wire_handler(monkeypatch, dynamodb, MemoryS3(key, _png_bytes()), bedrock)

    response = analyze.lambda_handler(_event(key), Context())

    assert response["statusCode"] == 200
    assert len(bedrock.calls) == 2
    assert [len(transaction) for transaction in dynamodb.meta.client.transactions] == [1, 2, 2]


def test_mock_ai_output_uses_valid_new_schema(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("MOCK_AI", "1")

    result = analyze._invoke_model(
        SONNET_MODEL_ID,
        b"jpeg",
        Context(),
        analyze.time.monotonic(),
    )

    assert set(result) == {"whiskeys", "serving_style", "glass_type"}
    assert result["whiskeys"][0]["name_ja"] == "モックウイスキー"
    assert analyze._validate_model_output(result) == result


def test_master_snapshot_reads_every_page_and_uses_required_projection():
    pages = [
        {"Items": [{"id": "one", "name": "One"}], "LastEvaluatedKey": {"id": "one"}},
        {"Items": [{"id": "two", "name_ja": "Two"}], "LastEvaluatedKey": {"id": "two"}},
        {"Items": [{"id": "three", "name_en": "Three"}]},
    ]
    table = WhiskeyTable(items=[], pages=pages)

    snapshot = analyze._get_master_snapshot(table, "WhiskeySearch-test")

    assert snapshot["complete"] is True
    assert snapshot["page_count"] == 3
    assert len(snapshot["items"]) == 3
    assert len(table.scan_calls) == 3
    assert table.scan_calls[1]["ExclusiveStartKey"] == {"id": "one"}
    assert table.scan_calls[2]["ExclusiveStartKey"] == {"id": "two"}
    assert table.scan_calls[0]["ProjectionExpression"] == (
        "id, #name, name_ja, name_en, normalized_name"
    )


def test_master_snapshot_cache_is_reused(monkeypatch):
    key = f"tmp/user-1/{uuid.uuid4()}.png"
    whiskey_table = WhiskeyTable()
    dynamodb = FakeDynamoDB(whiskeys=whiskey_table)
    bedrock = Bedrock([_model_json([]), _model_json([])])
    _wire_handler(monkeypatch, dynamodb, MemoryS3(key, _png_bytes()), bedrock)

    first = analyze.lambda_handler(_event(key), Context())
    second = analyze.lambda_handler(_event(key), Context())

    assert first["statusCode"] == second["statusCode"] == 200
    assert len(whiskey_table.scan_calls) == 1


def test_scan_failure_degrades_to_ai_without_500_and_is_not_cached(monkeypatch, caplog):
    key = f"tmp/user-1/{uuid.uuid4()}.png"

    class ErrorThenSuccessTable(WhiskeyTable):
        def scan(self, **kwargs):
            self.scan_calls.append(kwargs)
            if len(self.scan_calls) == 1:
                raise ClientError(
                    {
                        "Error": {
                            "Code": "ThrottlingException",
                            "Message": "sensitive detail",
                        }
                    },
                    "Scan",
                )
            return {"Items": [dict(CAOL_ILA_ITEM)]}

    whiskey_table = ErrorThenSuccessTable(items=[])
    dynamodb = FakeDynamoDB(whiskeys=whiskey_table)
    analysis_text = _model_json(
        [
            {
                "name_ja": "カリラ 12年",
                "name_en": "Caol Ila 12 Year Old",
                "confidence": 0.8,
            }
        ]
    )
    bedrock = Bedrock([analysis_text, analysis_text])
    _wire_handler(monkeypatch, dynamodb, MemoryS3(key, _png_bytes()), bedrock)

    with caplog.at_level("INFO", logger="drink-log-analyze"):
        first = analyze.lambda_handler(_event(key), Context())
        second = analyze.lambda_handler(_event(key), Context())

    first_candidate = json.loads(first["body"])["candidates"][0]
    second_candidate = json.loads(second["body"])["candidates"][0]
    assert first["statusCode"] == second["statusCode"] == 200
    assert first_candidate["brand_text"] == "カリラ 12年"
    assert first_candidate["match_source"] == "ai"
    assert "whiskey_id" not in first_candidate
    assert second_candidate["match_source"] == "catalog"
    assert second_candidate["whiskey_id"] == "caol-ila-12"
    assert len(whiskey_table.scan_calls) == 2
    assert "Master snapshot scan failed" in caplog.text
    assert '"error_type": "ClientError"' in caplog.text
    assert "ThrottlingException" not in caplog.text
    assert "sensitive detail" not in caplog.text


def test_master_item_limit_degrades_to_ai_and_caches_incomplete_snapshot(
    monkeypatch,
    caplog,
):
    key = f"tmp/user-1/{uuid.uuid4()}.png"
    whiskey_table = WhiskeyTable(
        items=[
            dict(CAOL_ILA_ITEM),
            {"id": "other", "name_ja": "余市", "name_en": "Yoichi"},
        ]
    )
    dynamodb = FakeDynamoDB(whiskeys=whiskey_table)
    analysis_text = _model_json(
        [
            {
                "name_ja": "カリラ 12年",
                "name_en": "Caol Ila 12 Year Old",
                "confidence": 0.8,
            }
        ]
    )
    bedrock = Bedrock([analysis_text, analysis_text])
    monkeypatch.setattr(analyze, "MASTER_SNAPSHOT_MAX_ITEMS", 1)
    _wire_handler(monkeypatch, dynamodb, MemoryS3(key, _png_bytes()), bedrock)

    with caplog.at_level("INFO", logger="drink-log-analyze"):
        first = analyze.lambda_handler(_event(key), Context())
        second = analyze.lambda_handler(_event(key), Context())

    assert first["statusCode"] == second["statusCode"] == 200
    for response in (first, second):
        candidate = json.loads(response["body"])["candidates"][0]
        assert candidate["match_source"] == "ai"
        assert "whiskey_id" not in candidate
    assert len(whiskey_table.scan_calls) == 1
    assert '"incomplete_reason": "max_items"' in caplog.text


def test_global_profile_is_rejected_at_startup(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6")
    monkeypatch.setenv(
        "BEDROCK_MODEL_ALLOWLIST",
        "global.anthropic.claude-sonnet-4-6",
    )

    with pytest.raises(RuntimeError, match="Global"):
        analyze.lambda_handler(_event(f"tmp/user-1/{uuid.uuid4()}.jpg"), Context())


def test_non_allowlisted_model_and_nonlocal_mock_are_startup_errors(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_ID", "jp.unapproved")
    with pytest.raises(RuntimeError, match="ALLOWLIST"):
        analyze.lambda_handler(_event(f"tmp/user-1/{uuid.uuid4()}.jpg"), Context())

    monkeypatch.setenv("BEDROCK_MODEL_ID", SONNET_MODEL_ID)
    monkeypatch.setenv("MOCK_AI", "1")
    with pytest.raises(RuntimeError, match="local"):
        analyze.lambda_handler(_event(f"tmp/user-1/{uuid.uuid4()}.jpg"), Context())


def test_ownership_is_rejected_before_aws_calls(monkeypatch):
    key = f"tmp/other/{uuid.uuid4()}.jpg"
    monkeypatch.setattr(
        analyze,
        "get_dynamodb_resource",
        lambda: pytest.fail("must not create client"),
    )

    response = analyze.lambda_handler(_event(key), Context())

    assert response["statusCode"] == 403


def test_invalid_magic_bytes_are_rejected_before_bedrock(monkeypatch):
    key = f"tmp/user-1/{uuid.uuid4()}.jpg"
    s3 = MemoryS3(key, b"not-an-image")
    dynamodb = FakeDynamoDB()
    monkeypatch.setattr(analyze, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(analyze, "get_s3_client", lambda: s3)
    monkeypatch.setattr(
        analyze,
        "_bedrock_client",
        lambda timeout: pytest.fail("must not invoke"),
    )

    response = analyze.lambda_handler(_event(key), Context())

    assert response["statusCode"] == 400
    assert dynamodb.meta.client.transactions == []


def test_counter_write_failure_is_fail_closed(monkeypatch):
    key = f"tmp/user-1/{uuid.uuid4()}.png"
    s3 = MemoryS3(key, _png_bytes())
    dynamodb = FakeDynamoDB()

    def fail_write(**kwargs):
        del kwargs
        raise RuntimeError("DynamoDB unavailable")

    dynamodb.meta.client.transact_write_items = fail_write
    monkeypatch.setattr(analyze, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(analyze, "get_s3_client", lambda: s3)
    monkeypatch.setattr(
        analyze,
        "_bedrock_client",
        lambda timeout: pytest.fail("must not invoke"),
    )

    response = analyze.lambda_handler(_event(key), Context())

    assert response["statusCode"] == 500


def test_low_remaining_time_consumes_user_request_but_returns_empty_200(monkeypatch):
    key = f"tmp/user-1/{uuid.uuid4()}.png"
    dynamodb = FakeDynamoDB(whiskeys=WhiskeyTable(items=[]))
    monkeypatch.setattr(analyze, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(analyze, "get_s3_client", lambda: MemoryS3(key, _png_bytes()))
    monkeypatch.setattr(
        analyze,
        "_bedrock_client",
        lambda timeout: pytest.fail("must not invoke"),
    )

    response = analyze.lambda_handler(_event(key), Context(remaining=1_000))

    assert response["statusCode"] == 200
    assert json.loads(response["body"])["candidates"] == []
    saved = next(iter(dynamodb.app.items.values()))
    assert saved["candidates"] == []
    assert [len(transaction) for transaction in dynamodb.meta.client.transactions] == [1]


def test_handler_budget_gives_sonnet_twenty_seconds_and_keeps_four_second_safety():
    remaining = analyze._remaining_budget_ms(Context(remaining=28_000), analyze.time.monotonic())

    assert analyze.HANDLER_BUDGET_MS == 24_000
    assert analyze.INVOKE_SAFETY_MS == 4_000
    assert 19_900 <= remaining <= 20_000


def test_monthly_analysis_limit_is_a_503_circuit_breaker():
    class MonthlyLimitClient(RecordingClient):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def transact_write_items(self, **kwargs):
            del kwargs
            self.calls += 1
            raise TransactionCanceled(
                [{"Code": "None"}, {"Code": "ConditionalCheckFailed"}]
            )

    dynamodb = FakeDynamoDB()
    dynamodb.meta.client = MonthlyLimitClient()

    with pytest.raises(analyze.BudgetExceeded) as exc:
        analyze._reserve_analysis_budget(
            dynamodb,
            "AppState-test",
            "user-1",
            user_request=False,
        )

    assert exc.value.status_code == 503
    assert dynamodb.meta.client.calls == 1


def test_analysis_budget_retries_a_transaction_conflict(monkeypatch):
    class ConflictOnceClient(RecordingClient):
        def transact_write_items(self, **kwargs):
            self.transactions.append(kwargs["TransactItems"])
            if len(self.transactions) == 1:
                raise TransactionCanceled([{"Code": "TransactionConflict"}])

    dynamodb = FakeDynamoDB()
    dynamodb.meta.client = ConflictOnceClient()
    retry = analyze.transact_write_with_retry
    monkeypatch.setattr(
        analyze,
        "transact_write_with_retry",
        lambda client, items, **kwargs: retry(
            client,
            items,
            sleep=lambda _delay: None,
            jitter=lambda: 1.0,
            **kwargs,
        ),
    )

    analyze._reserve_analysis_budget(
        dynamodb,
        "AppState-test",
        "user-1",
        user_request=True,
        remaining_ms=lambda: 1_000,
    )

    assert len(dynamodb.meta.client.transactions) == 2


def test_low_budget_skips_the_catalog_scan_and_still_returns_200(monkeypatch):
    """The post-invoke scan must not be able to push the handler past timeout.

    _get_master_snapshot can cost up to MASTER_SNAPSHOT_MAX_PAGES sequential
    round trips on a cold container, and it runs after the model call. Without
    a budget check it can exceed the Lambda timeout, which the client sees as a
    502 rather than a record saved with no catalog id.
    """
    upload_uuid = "12345678-1234-4234-8234-123456789abc"
    key = f"tmp/user-1/{upload_uuid}.png"
    dynamodb = FakeDynamoDB()
    bedrock = Bedrock([_model_json([_whiskey("カリラ 12年")])])
    _wire_handler(monkeypatch, dynamodb, MemoryS3(key, _png_bytes()), bedrock)

    # Enough budget for the model call, not enough for the scan afterwards.
    response = analyze.lambda_handler(_event(key), SequencedContext([28_000, 28_000, 1_000]))

    assert response["statusCode"] == 200
    assert dynamodb.whiskeys.scan_calls == []
    body = json.loads(response["body"])
    assert [candidate["match_source"] for candidate in body["candidates"]] == ["ai"]
    assert "whiskey_id" not in body["candidates"][0]


def test_warm_cache_is_used_even_when_the_budget_is_low(monkeypatch):
    """A cached snapshot costs nothing, so a tight budget must not discard it."""
    upload_uuid = "12345678-1234-4234-8234-123456789abc"
    key = f"tmp/user-1/{upload_uuid}.png"
    dynamodb = FakeDynamoDB()
    analyze._MASTER_CACHE = _snapshot([CAOL_ILA_ITEM])
    try:
        bedrock = Bedrock([_model_json([_whiskey("カリラ 12年")])])
        _wire_handler(monkeypatch, dynamodb, MemoryS3(key, _png_bytes()), bedrock)

        response = analyze.lambda_handler(
            _event(key), SequencedContext([28_000, 28_000, 1_000])
        )
    finally:
        analyze._reset_master_cache()

    assert response["statusCode"] == 200
    assert dynamodb.whiskeys.scan_calls == []
    body = json.loads(response["body"])
    assert body["candidates"][0]["match_source"] == "catalog"
