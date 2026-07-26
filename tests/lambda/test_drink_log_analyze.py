import io
import json
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError
from PIL import Image

from tests.lambda_module_loader import load_lambda_module


analyze = load_lambda_module("drink_log_analyze_tests", "lambda/drink-log-analyze/index.py")
drink_logs = load_lambda_module("drink_logs_analysis_contract_tests", "lambda/drink-logs/index.py")

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
    def __init__(self, match=True, items=None, pages=None):
        self.items = [dict(CAOL_ILA_ITEM)] if match else []
        if items is not None:
            self.items = [dict(item) for item in items]
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
    def __init__(self, remaining_values):
        self.remaining_values = iter(remaining_values)

    def get_remaining_time_in_millis(self):
        return next(self.remaining_values)


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
        "BEDROCK_MODEL_ID": "jp.amazon.nova-2-lite-v1:0",
        "BEDROCK_MODEL_ALLOWLIST": (
            "jp.amazon.nova-2-lite-v1:0,"
            "jp.anthropic.claude-haiku-4-5-20251001-v1:0"
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
        "page_count": 1,
    }


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


@pytest.mark.parametrize(
    "text",
    [
        '{"brand_candidates":[],"serving_style":"NEAT","glass_type":"tumbler","label_text":""}',
        '```json\n{"brand_candidates":[],"serving_style":"NEAT","glass_type":"tumbler","label_text":""}\n```',
    ],
)
def test_fenced_and_plain_json_are_accepted(monkeypatch, text):
    bedrock = Bedrock([text])
    monkeypatch.setattr(analyze, "_bedrock_client", lambda timeout: bedrock)
    result = analyze._invoke_model(
        "jp.amazon.nova-2-lite-v1:0", b"jpeg", Context(), analyze.time.monotonic()
    )
    assert result == {
        "brand_candidates": [],
        "serving_style": "NEAT",
        "glass_type": "tumbler",
        "label_text": "",
    }
    assert bedrock.calls[0]["inferenceConfig"]["maxTokens"] == 512


def test_handler_normalizes_image_saves_contract_and_round_trips_to_create(monkeypatch):
    upload_uuid = "12345678-1234-4234-8234-123456789abc"
    key = f"tmp/user-1/{upload_uuid}.png"
    raw = _png_bytes()
    s3 = MemoryS3(key, raw)
    dynamodb = FakeDynamoDB()
    bedrock = Bedrock(
        [
            "```json\n"
            '{"brand_candidates":[{"name_ja":"カオルイラ","name_en":"Caol Ila",'
            '"confidence":0.91}],"serving_style":"highball","glass_type":"tumbler",'
            '"label_text":"CAOL ILA 12"}'
            "\n```"
        ]
    )
    monkeypatch.setattr(analyze, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(analyze, "get_s3_client", lambda: s3)
    monkeypatch.setattr(analyze, "_bedrock_client", lambda timeout: bedrock)

    response = analyze.lambda_handler(_event(key), Context())
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    analysis_id = f"ai-result:user-1:{upload_uuid}"
    assert body["analysis_id"] == analysis_id
    assert body["serving_style"] == "SODA"
    assert body["candidates"][0]["brand_text"] == "カリラ 12年"
    assert body["candidates"][0]["whiskey_id"] == "caol-ila-12"
    assert body["candidates"][0]["match_source"] == "master:substring"
    assert body["candidates"][0]["ai_name_ja"] == "カオルイラ"

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
    assert saved["candidates"][0]["confidence"] == Decimal("0.91")
    assert isinstance(saved["confidence"], Decimal)
    assert isinstance(saved["candidates"][0]["confidence"], Decimal)
    assert "label_text" not in saved
    assert "label_text" not in body
    assert "shortlist" not in saved
    assert "shortlist" not in body
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


def test_caol_ila_match_uses_canonical_master_name():
    analysis = {
        "brand_candidates": [
            {
                "name_ja": "カオルイラ",
                "name_en": "Caol Ila",
                "confidence": Decimal("0.8"),
            }
        ]
    }

    candidate = analyze._build_candidates(_snapshot([CAOL_ILA_ITEM]), analysis)[0]

    assert candidate["brand_text"] == "カリラ 12年"
    assert candidate["whiskey_id"] == "caol-ila-12"
    assert candidate["match_source"] == "master:substring"
    assert candidate["ai_name_ja"] == "カオルイラ"
    assert isinstance(candidate["confidence"], Decimal)


def test_exact_match_has_priority_over_substring_matches():
    items = [
        {"id": "exact", "name_ja": "余市", "name_en": "Yoichi"},
        {"id": "aged", "name_ja": "余市 10年", "name_en": "Yoichi 10 Year Old"},
    ]
    analysis = {
        "brand_candidates": [
            {"name_ja": "余市", "name_en": "Yoichi", "confidence": Decimal("0.9")}
        ]
    }

    candidate = analyze._build_candidates(_snapshot(items), analysis)[0]

    assert candidate["match_source"] == "master:exact"
    assert candidate["whiskey_id"] == "exact"


def test_label_text_can_uniquely_confirm_a_master_name():
    analysis = {
        "brand_candidates": [
            {
                "name_ja": "判読不能",
                "name_en": "Unreadable",
                "confidence": Decimal("0.4"),
            }
        ]
    }

    candidate = analyze._build_candidates(
        _snapshot([CAOL_ILA_ITEM]),
        analysis,
        "SINGLE MALT SCOTCH WHISKY\nCAOL ILA 12 YEAR OLD",
    )[0]

    assert candidate["match_source"] == "master:substring"
    assert candidate["whiskey_id"] == "caol-ila-12"


def test_unmatched_candidate_keeps_ai_name_without_whiskey_id():
    analysis = {
        "brand_candidates": [
            {
                "name_ja": "未登録ウイスキー",
                "name_en": "Unknown Whisky",
                "confidence": Decimal("0.7"),
            }
        ]
    }

    candidate = analyze._build_candidates(_snapshot([]), analysis)[0]

    assert candidate["brand_text"] == "未登録ウイスキー"
    assert candidate["match_source"] == "ai"
    assert "whiskey_id" not in candidate


def test_canonical_name_falls_back_to_master_name_when_name_ja_is_missing():
    item = {
        "id": "master-name-only",
        "name": "Caol Ila Master",
        "name_en": "",
        "normalized_name": "unused",
    }
    analysis = {
        "brand_candidates": [
            {
                "name_ja": "カオルイラ",
                "name_en": "Caol Ila",
                "confidence": Decimal("0.8"),
            }
        ]
    }

    candidate = analyze._build_candidates(_snapshot([item]), analysis)[0]

    assert candidate["brand_text"] == "Caol Ila Master"
    assert candidate["whiskey_id"] == "master-name-only"
    assert candidate["match_source"] == "master:substring"


def test_canonical_name_over_200_characters_falls_back_to_llm_name():
    item = {
        "id": "oversized-master-name",
        "name": f"Caol Ila {'x' * 201}",
        "normalized_name": "unused",
    }
    analysis = {
        "brand_candidates": [
            {
                "name_ja": "カオルイラ",
                "name_en": "Caol Ila",
                "confidence": Decimal("0.8"),
            }
        ]
    }

    candidate = analyze._build_candidates(_snapshot([item]), analysis)[0]

    assert candidate["brand_text"] == "カオルイラ"
    assert candidate["whiskey_id"] == "oversized-master-name"
    assert candidate["match_source"] == "master:substring"


def test_unrelated_candidate_stays_ai_with_nonempty_master():
    analysis = {
        "brand_candidates": [
            {
                "name_ja": "余市",
                "name_en": "Yoichi",
                "confidence": Decimal("0.7"),
            }
        ]
    }

    candidate = analyze._build_candidates(_snapshot([CAOL_ILA_ITEM]), analysis)[0]

    assert candidate["match_source"] == "ai"
    assert candidate["brand_text"] == "余市"
    assert "whiskey_id" not in candidate


def test_yamazaki_brand_only_match_is_ambiguous():
    items = [
        {
            "id": "yamazaki-12",
            "name_ja": "山崎 12年",
            "name_en": "Yamazaki 12 Year Old",
        },
        {
            "id": "yamazaki-18",
            "name_ja": "山崎 18年",
            "name_en": "Yamazaki 18 Year Old",
        },
    ]
    analysis = {
        "brand_candidates": [
            {
                "name_ja": "山崎",
                "name_en": "Yamazaki",
                "confidence": Decimal("0.9"),
            }
        ]
    }

    snapshot = _snapshot(items)
    candidates, unresolved, ambiguous_items = analyze._resolve_candidates(
        snapshot,
        analysis,
        "",
    )
    candidate = candidates[0]
    shortlist = analyze._build_fuzzy_shortlist(
        snapshot,
        unresolved,
        "",
        ambiguous_items,
    )

    assert candidate["match_source"] == "ambiguous"
    assert candidate["brand_text"] == "山崎"
    assert "whiskey_id" not in candidate
    assert {item["id"] for item in shortlist} >= {"yamazaki-12", "yamazaki-18"}


@pytest.mark.parametrize(
    ("name_ja", "expected_source", "expected_brand"),
    [
        ("白州", "master:substring", "白州 12年"),
        ("響", "ai", "響"),
    ],
)
def test_japanese_only_brand_name_matching(name_ja, expected_source, expected_brand):
    """Two-character kanji brands must still match when name_en is empty.

    A three-character floor is right for Latin fragments but silently blinds
    the matcher to 山崎 / 白州 / 余市. A single character stays unusable.
    """
    items = [
        {
            "id": "hakushu-12",
            "name_ja": "白州 12年",
            "name_en": "Hakushu 12 Year Old",
        }
    ]
    analysis = {
        "brand_candidates": [
            {"name_ja": name_ja, "name_en": "", "confidence": Decimal("0.9")}
        ]
    }

    candidate = analyze._build_candidates(_snapshot(items), analysis)[0]

    assert candidate["match_source"] == expected_source
    assert candidate["brand_text"] == expected_brand


def test_japanese_only_brand_name_keeps_ambiguity_gate():
    """The relaxed CJK floor must not weaken the uniqueness gate."""
    items = [
        {"id": "yamazaki-12", "name_ja": "山崎 12年", "name_en": "Yamazaki 12 Year Old"},
        {"id": "yamazaki-18", "name_ja": "山崎 18年", "name_en": "Yamazaki 18 Year Old"},
    ]
    analysis = {
        "brand_candidates": [
            {"name_ja": "山崎", "name_en": "", "confidence": Decimal("0.9")}
        ]
    }

    candidate = analyze._build_candidates(_snapshot(items), analysis)[0]

    assert candidate["match_source"] == "ambiguous"
    assert candidate["brand_text"] == "山崎"
    assert "whiskey_id" not in candidate


@pytest.mark.parametrize(
    ("name_ja", "name_en", "master", "label_text"),
    [
        (
            "シングルモルト",
            "Single Malt",
            {
                "id": "fuji-single-malt",
                "name_ja": "富士 シングルモルト",
                "name_en": "Fuji Single Malt",
            },
            "",
        ),
        (
            "",
            "Aberlour 12 Year Old",
            {
                "id": "aberfeldy-12",
                "name_ja": "アバフェルディ 12年",
                "name_en": "Aberfeldy 12 Year Old",
            },
            "",
        ),
        (
            "判読不能",
            "",
            {
                "id": "genshu",
                "name_ja": "シングルモルト原酒",
                "name_en": "",
            },
            "山崎蒸溜所 貯蔵 原酒 限定 700ml 43%",
        ),
        (
            "判読不能",
            "",
            {"id": "new-make", "name_ja": "限定新酒", "name_en": ""},
            "蒸留所 限定 新酒",
        ),
        (
            "判読不能",
            "",
            {"id": "old-liquor", "name_ja": "熟成古酒", "name_en": ""},
            "蒸溜所 熟成 古酒",
        ),
    ],
)
def test_fuzzy_similar_names_never_auto_confirm(
    name_ja,
    name_en,
    master,
    label_text,
):
    analysis = {
        "brand_candidates": [
            {"name_ja": name_ja, "name_en": name_en, "confidence": Decimal("0.5")}
        ]
    }

    candidate = analyze._build_candidates(
        _snapshot([master]),
        analysis,
        label_text,
    )[0]

    assert candidate["match_source"] == "ai"
    assert "whiskey_id" not in candidate


def test_two_character_latin_fragment_never_auto_confirms():
    analysis = {
        "brand_candidates": [
            {"name_ja": "", "name_en": "sq", "confidence": Decimal("0.5")}
        ]
    }
    master = {
        "id": "square-one",
        "name_ja": "",
        "name_en": "Square One",
    }

    candidate = analyze._build_candidates(_snapshot([master]), analysis)[0]

    assert candidate["match_source"] == "ai"
    assert "whiskey_id" not in candidate


def test_one_character_ocr_error_is_shortlisted_but_not_auto_confirmed():
    snapshot = _snapshot([CAOL_ILA_ITEM])
    candidate = {
        "name_ja": "",
        "name_en": "Caol lla",
        "confidence": Decimal("0.6"),
    }

    match = analyze._match_whiskey(snapshot, candidate, "")
    shortlist = analyze._build_fuzzy_shortlist(snapshot, [candidate], "", [])

    assert match["source"] == "ai"
    assert shortlist[0]["id"] == "caol-ila-12"
    assert shortlist[0]["score"] > 0


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("カリラ 12年", "かりら"),
        ("Caol Ila 12 Year Old", "caolila"),
        ("Fuji Single Malt", "fuji"),
        ("AGED 12 YEARS | Caol Ila 700ml 43%", "caolila"),
        # An all-generic value collapses to "" instead of falling back to the
        # original text. The fallback used to keep the noise words, which let a
        # master row named only "ブレンデッドウイスキー" match a bare
        # "ウイスキー" token — printed on practically every bottle.
        ("Single Malt Whisky", ""),
        ("ブレンデッドウイスキー", ""),
        ("ウイスキー", ""),
    ],
)
def test_brand_core_removes_age_generic_and_measurement_noise(value, expected):
    assert analyze._brand_core(value) == expected


@pytest.mark.parametrize(
    ("master_name_ja", "master_name_en", "label_text"),
    [
        ("ブレンデッドウイスキー", "", "サントリー ウイスキー 700ml"),
        ("", "Blended Whisky", "SINGLE MALT SCOTCH WHISKY 43%"),
        ("シングルモルトウイスキー蒸溜所原酒", "", "白州 蒸溜所 貯蔵"),
    ],
)
def test_all_generic_master_never_confirms_from_a_generic_label_token(
    master_name_ja, master_name_en, label_text
):
    """A master row whose name is only generic words must stay unmatchable.

    Otherwise a label token like ウイスキー / WHISKY / 蒸溜所 — present on
    essentially every bottle — auto-confirms it and the UI claims 照合済み.
    """
    master = {"id": "generic", "name_ja": master_name_ja, "name_en": master_name_en}
    candidate = {"name_ja": "判読不能", "name_en": "", "confidence": Decimal("0.4")}

    match = analyze._match_whiskey(_snapshot([master]), candidate, label_text)

    assert match["source"] == "ai"
    assert match["item"] is None


def test_generic_label_tokens_do_not_dilute_a_unique_name_match():
    """Label evidence must not outvote a unique candidate-name match.

    Caught on dev: a real Caol Ila photo returned "ambiguous" because the
    label's "SINGLE" and "MALT" tokens also hit 竹鶴ピュアモルト and
    フォアローゼズ. Pooling the two evidence classes let the noisy one bury a
    name match that was unique on its own.
    """
    items = [
        {"id": "caol-ila-12", "name_ja": "カリラ 12年", "name_en": "Caol Ila 12 Year Old"},
        {"id": "taketsuru", "name_ja": "竹鶴 ピュアモルト", "name_en": "Taketsuru Pure Malt"},
        {"id": "four-roses", "name_ja": "フォアローゼズ", "name_en": "Four Roses Single Barrel"},
    ]
    candidate = {"name_ja": "", "name_en": "Caol Ila", "confidence": Decimal("0.95")}

    match = analyze._match_whiskey(
        _snapshot(items), candidate, "CAOL ILA ISLAY SINGLE MALT AGED 12 YEARS"
    )

    assert match["source"] == "master:substring"
    assert match["item"]["id"] == "caol-ila-12"


def test_label_text_is_consulted_only_when_names_match_nothing():
    """The demoted label tier must still rescue an unreadable brand name."""
    items = [
        {"id": "caol-ila-12", "name_ja": "カリラ 12年", "name_en": "Caol Ila 12 Year Old"}
    ]
    candidate = {"name_ja": "判読不能", "name_en": "", "confidence": Decimal("0.4")}

    rescued = analyze._match_whiskey(
        _snapshot(items), candidate, "CAOL ILA AGED 12 YEARS"
    )
    generic = analyze._match_whiskey(
        _snapshot(items), candidate, "SINGLE MALT WHISKY 700ml"
    )

    assert rescued["source"] == "master:substring"
    assert rescued["item"]["id"] == "caol-ila-12"
    assert generic["source"] == "ai"


def test_label_tokens_split_on_japanese_punctuation():
    """、and ・ must separate tokens.

    They are stripped by the core separator, so without splitting first the
    neighbours glue together ("サントリー、山崎" -> "さんとりー山崎") and
    manufacture substrings that were never printed side by side.
    """
    assert analyze._LABEL_TOKEN_RE.split("サントリー、山崎") == ["サントリー", "山崎"]
    assert analyze._LABEL_TOKEN_RE.split("響・白州・山崎") == ["響", "白州", "山崎"]


def test_adjacent_label_tokens_do_not_manufacture_a_master_match():
    """Token splitting must be load-bearing, not decorative.

    Neither "アオ" nor "ヤマ" is usable on the label path on its own (two
    characters, and the CJK relaxation is disabled there), but concatenating
    them spells the master core exactly. Without the split this confirms a
    bottle whose label never printed the brand as one word.
    """
    master = {"id": "glued", "name_ja": "アオヤマ", "name_en": ""}
    candidate = {"name_ja": "判読不能", "name_en": "", "confidence": Decimal("0.4")}

    assert analyze._brand_core("アオ・ヤマ") == analyze._brand_core("アオヤマ")

    match = analyze._match_whiskey(_snapshot([master]), candidate, "アオ・ヤマ")

    assert match["source"] == "ai"


def test_fuzzy_shortlist_handles_large_master_snapshot():
    items = [
        {"id": f"brand-{index}", "name_ja": "", "name_en": f"Brand {index}"}
        for index in range(3000)
    ]
    candidate = {
        "name_ja": "",
        "name_en": "Brand 2999 typo",
        "confidence": Decimal("0.5"),
    }

    shortlist = analyze._build_fuzzy_shortlist(
        _snapshot(items),
        [candidate],
        "",
    )

    assert len(shortlist) == analyze.FUZZY_SHORTLIST_SIZE
    assert all("score" in item for item in shortlist)


def test_fuzzy_shortlist_caps_candidate_and_label_comparison_cores(monkeypatch):
    comparisons = []

    class RecordingMatcher:
        def __init__(self, _junk, query_core, master_core):
            comparisons.append((query_core, master_core))

        def ratio(self):
            return 0.5

    monkeypatch.setattr(analyze, "SequenceMatcher", RecordingMatcher)
    candidates = [
        {
            "name_ja": "",
            "name_en": f"Candidate {index}",
            "confidence": Decimal("0.5"),
        }
        for index in range(20)
    ]
    label_text = " ".join(f"token{index}" for index in range(100))

    shortlist = analyze._build_fuzzy_shortlist(
        _snapshot([{"id": "master", "name_en": "Master Brand"}]),
        candidates,
        label_text,
    )

    assert shortlist[0]["id"] == "master"
    query_cores = {query_core for query_core, _master_core in comparisons}
    assert len(query_cores) == 20
    assert "candidate9" in query_cores
    assert "candidate10" not in query_cores
    assert "token9" in query_cores
    assert "token10" not in query_cores


def test_fuzzy_shortlist_keeps_all_scored_forced_ids_without_ghost_offset():
    items = [
        {"id": f"forced-{index}", "name_en": f"Forced Brand {index}"}
        for index in range(11)
    ]
    items.extend(
        {"id": f"other-{index}", "name_en": f"Other Brand {index}"}
        for index in range(5)
    )
    snapshot = _snapshot(items)
    ambiguous_items = list(snapshot["items"][:11])
    ambiguous_items.append({"id": "ghost-forced"})
    candidate = {
        "name_ja": "",
        "name_en": "Unresolved Brand",
        "confidence": Decimal("0.5"),
    }

    shortlist = analyze._build_fuzzy_shortlist(
        snapshot,
        [candidate],
        "",
        ambiguous_items,
    )

    shortlist_ids = {item["id"] for item in shortlist}
    assert shortlist_ids == {f"forced-{index}" for index in range(11)}
    assert len(shortlist) == 11


def test_candidate_resolution_log_does_not_include_brand_names(monkeypatch, caplog):
    upload_uuid = "12345678-1234-4234-8234-123456789abc"
    key = f"tmp/user-1/{upload_uuid}.png"
    dynamodb = FakeDynamoDB()
    bedrock = Bedrock(
        [
            '{"brand_candidates":[{"name_ja":"カオルイラ","name_en":"Caol Ila",'
            '"confidence":0.8}],"serving_style":"NEAT","glass_type":"tumbler",'
            '"label_text":"CAOL ILA SECRET LABEL"}'
        ]
    )
    monkeypatch.setattr(analyze, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(analyze, "get_s3_client", lambda: MemoryS3(key, _png_bytes()))
    monkeypatch.setattr(analyze, "_bedrock_client", lambda timeout: bedrock)

    with caplog.at_level("INFO", logger="drink-log-analyze"):
        response = analyze.lambda_handler(_event(key), Context())

    assert response["statusCode"] == 200
    assert "Brand candidates resolved" in caplog.text
    assert '"matched_count": 1' in caplog.text
    assert '"label_text_length": 21' in caplog.text
    assert '"master_snapshot_complete": true' in caplog.text
    assert '"master_snapshot_size": 1' in caplog.text
    assert '"shortlist_size": 0' in caplog.text
    assert '"ambiguous_count": 0' in caplog.text
    assert all(
        value not in caplog.text
        for value in ("カオルイラ", "カリラ", "Caol Ila", "CAOL ILA SECRET LABEL")
    )


def test_malformed_output_retries_and_consumes_each_global_attempt(monkeypatch):
    upload_uuid = "12345678-1234-4234-8234-123456789abc"
    key = f"tmp/user-1/{upload_uuid}.png"
    s3 = MemoryS3(key, _png_bytes())
    dynamodb = FakeDynamoDB(whiskeys=WhiskeyTable(match=False))
    bedrock = Bedrock(
        [
            "```json\nnot-json\n```",
            '{"brand_candidates":[],"serving_style":"NEAT","glass_type":"rocks",'
            '"label_text":""}',
        ]
    )
    monkeypatch.setattr(analyze, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(analyze, "get_s3_client", lambda: s3)
    monkeypatch.setattr(analyze, "_bedrock_client", lambda timeout: bedrock)
    response = analyze.lambda_handler(_event(key), Context())
    assert response["statusCode"] == 200
    assert len(bedrock.calls) == 2
    assert [len(transaction) for transaction in dynamodb.meta.client.transactions] == [1, 2, 2]
    for transaction in dynamodb.meta.client.transactions[1:]:
        keys = [write["Update"]["Key"]["pk"] for write in transaction]
        assert all("#global" in key for key in keys)


@pytest.mark.parametrize(
    "malformed",
    [
        '{"brand_candidates":[],"serving_style":"NEAT","glass_type":"rocks"}',
        '{"brand_candidates":[],"serving_style":"NEAT","glass_type":"rocks",'
        '"label_text":123}',
    ],
)
def test_invalid_label_text_uses_existing_retry_path(monkeypatch, malformed):
    key = f"tmp/user-1/{uuid.uuid4()}.png"
    dynamodb = FakeDynamoDB(whiskeys=WhiskeyTable(match=False))
    bedrock = Bedrock(
        [
            malformed,
            '{"brand_candidates":[],"serving_style":"NEAT","glass_type":"rocks",'
            '"label_text":""}',
        ]
    )
    monkeypatch.setattr(analyze, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(analyze, "get_s3_client", lambda: MemoryS3(key, _png_bytes()))
    monkeypatch.setattr(analyze, "_bedrock_client", lambda timeout: bedrock)

    response = analyze.lambda_handler(_event(key), Context())

    assert response["statusCode"] == 200
    assert len(bedrock.calls) == 2


def test_long_label_text_is_clamped_without_retry_or_losing_candidates(monkeypatch):
    label_text = "CAOL ILA " + ("x" * 201)
    bedrock = Bedrock(
        [
            json.dumps(
                {
                    "brand_candidates": [
                        {
                            "name_ja": "カオルイラ",
                            "name_en": "Caol Ila",
                            "confidence": 0.8,
                        }
                    ],
                    "serving_style": "NEAT",
                    "glass_type": "tumbler",
                    "label_text": label_text,
                }
            )
        ]
    )
    monkeypatch.setattr(analyze, "_bedrock_client", lambda timeout: bedrock)

    result = analyze._invoke_model(
        "jp.amazon.nova-2-lite-v1:0",
        b"jpeg",
        Context(),
        analyze.time.monotonic(),
    )

    assert len(bedrock.calls) == 1
    assert len(result["label_text"]) == 200
    assert result["label_text"] == label_text[:200]
    assert result["brand_candidates"][0]["name_en"] == "Caol Ila"


def test_mock_ai_output_includes_valid_label_text(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("MOCK_AI", "1")

    result = analyze._invoke_model(
        "jp.amazon.nova-2-lite-v1:0",
        b"jpeg",
        Context(),
        analyze.time.monotonic(),
    )

    assert result["label_text"] == ""
    assert analyze._validate_model_output(result) == result


def test_master_snapshot_reads_every_page():
    pages = [
        {"Items": [{"id": "one", "name": "One"}], "LastEvaluatedKey": {"id": "one"}},
        {"Items": [{"id": "two", "name": "Two"}], "LastEvaluatedKey": {"id": "two"}},
        {"Items": [{"id": "three", "name": "Three"}]},
    ]
    table = WhiskeyTable(match=False, pages=pages)

    snapshot = analyze._get_master_snapshot(table, "WhiskeySearch-test")

    assert snapshot["complete"] is True
    assert snapshot["page_count"] == 3
    assert len(snapshot["items"]) == 3
    assert len(table.scan_calls) == 3
    assert table.scan_calls[1]["ExclusiveStartKey"] == {"id": "one"}
    assert table.scan_calls[2]["ExclusiveStartKey"] == {"id": "two"}


def test_master_snapshot_exact_item_limit_is_complete_without_last_key(monkeypatch):
    monkeypatch.setattr(analyze, "MASTER_SNAPSHOT_MAX_ITEMS", 2)
    table = WhiskeyTable(
        match=False,
        pages=[
            {
                "Items": [
                    {"id": "one", "name": "One"},
                    {"id": "two", "name": "Two"},
                ]
            }
        ],
    )

    snapshot = analyze._get_master_snapshot(table, "WhiskeySearch-test")

    assert snapshot["complete"] is True
    assert snapshot["incomplete_reason"] is None
    assert len(snapshot["items"]) == 2


def test_master_snapshot_cache_is_reused_across_analyses(monkeypatch):
    upload_uuid = "12345678-1234-4234-8234-123456789abc"
    key = f"tmp/user-1/{upload_uuid}.png"
    whiskey_table = WhiskeyTable()
    dynamodb = FakeDynamoDB(whiskeys=whiskey_table)
    bedrock = Bedrock(
        [
            '{"brand_candidates":[],"serving_style":"NEAT","glass_type":"tumbler",'
            '"label_text":""}',
            '{"brand_candidates":[],"serving_style":"NEAT","glass_type":"tumbler",'
            '"label_text":""}',
        ]
    )
    monkeypatch.setattr(analyze, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(analyze, "get_s3_client", lambda: MemoryS3(key, _png_bytes()))
    monkeypatch.setattr(analyze, "_bedrock_client", lambda timeout: bedrock)

    first = analyze.lambda_handler(_event(key), Context())
    second = analyze.lambda_handler(_event(key), Context())

    assert first["statusCode"] == second["statusCode"] == 200
    assert len(whiskey_table.scan_calls) == 1


def test_scan_client_error_degrades_to_ai_and_is_retried(
    monkeypatch,
    caplog,
):
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

    whiskey_table = ErrorThenSuccessTable(match=False)
    dynamodb = FakeDynamoDB(whiskeys=whiskey_table)
    analysis_text = (
        '{"brand_candidates":[{"name_ja":"カオルイラ","name_en":"Caol Ila",'
        '"confidence":0.8},{"name_ja":"余市","name_en":"Yoichi","confidence":0.7}],'
        '"serving_style":"NEAT","glass_type":"tumbler",'
        '"label_text":""}'
    )
    bedrock = Bedrock([analysis_text, analysis_text])
    monkeypatch.setattr(analyze, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(analyze, "get_s3_client", lambda: MemoryS3(key, _png_bytes()))
    monkeypatch.setattr(analyze, "_bedrock_client", lambda timeout: bedrock)

    with caplog.at_level("INFO", logger="drink-log-analyze"):
        first = analyze.lambda_handler(_event(key), Context())
        second = analyze.lambda_handler(_event(key), Context())

    first_candidates = json.loads(first["body"])["candidates"]
    second_candidates = json.loads(second["body"])["candidates"]
    assert first["statusCode"] == second["statusCode"] == 200
    assert all(candidate["match_source"] == "ai" for candidate in first_candidates)
    assert all("whiskey_id" not in candidate for candidate in first_candidates)
    assert second_candidates[0]["match_source"] == "master:substring"
    assert second_candidates[1]["match_source"] == "ai"
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
        match=False,
        items=[
            dict(CAOL_ILA_ITEM),
            {"id": "other", "name_ja": "余市", "name_en": "Yoichi"},
        ],
    )
    dynamodb = FakeDynamoDB(whiskeys=whiskey_table)
    analysis_text = (
        '{"brand_candidates":[{"name_ja":"カオルイラ","name_en":"Caol Ila",'
        '"confidence":0.8}],"serving_style":"NEAT","glass_type":"tumbler",'
        '"label_text":"CAOL ILA"}'
    )
    bedrock = Bedrock([analysis_text, analysis_text])
    monkeypatch.setattr(analyze, "MASTER_SNAPSHOT_MAX_ITEMS", 1)
    monkeypatch.setattr(analyze, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(analyze, "get_s3_client", lambda: MemoryS3(key, _png_bytes()))
    monkeypatch.setattr(analyze, "_bedrock_client", lambda timeout: bedrock)

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


def test_incomplete_master_snapshot_disables_matching_and_shortlist(
    monkeypatch,
    caplog,
):
    key = f"tmp/user-1/{uuid.uuid4()}.png"
    whiskey_table = WhiskeyTable(
        match=False,
        pages=[
            {
                "Items": [dict(CAOL_ILA_ITEM)],
                "LastEvaluatedKey": {"id": "caol-ila-12"},
            }
        ],
    )
    dynamodb = FakeDynamoDB(whiskeys=whiskey_table)
    bedrock = Bedrock(
        [
            '{"brand_candidates":[{"name_ja":"カオルイラ","name_en":"Caol Ila",'
            '"confidence":0.8}],"serving_style":"NEAT","glass_type":"tumbler",'
            '"label_text":"CAOL ILA"}'
        ]
    )
    monkeypatch.setattr(analyze, "MASTER_SNAPSHOT_MAX_PAGES", 1)
    monkeypatch.setattr(analyze, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(analyze, "get_s3_client", lambda: MemoryS3(key, _png_bytes()))
    monkeypatch.setattr(analyze, "_bedrock_client", lambda timeout: bedrock)

    with caplog.at_level("INFO", logger="drink-log-analyze"):
        response = analyze.lambda_handler(_event(key), Context())

    assert response["statusCode"] == 200
    candidate = json.loads(response["body"])["candidates"][0]
    assert candidate["match_source"] == "ai"
    assert "whiskey_id" not in candidate
    assert "Master snapshot incomplete" in caplog.text
    assert '"master_snapshot_complete": false' in caplog.text
    assert '"shortlist_size": 0' in caplog.text


def test_low_budget_skips_fuzzy_shortlist_and_logs_zero(monkeypatch, caplog):
    key = f"tmp/user-1/{uuid.uuid4()}.png"
    dynamodb = FakeDynamoDB()
    bedrock = Bedrock(
        [
            '{"brand_candidates":[{"name_ja":"","name_en":"Caol lla",'
            '"confidence":0.6}],"serving_style":"NEAT","glass_type":"tumbler",'
            '"label_text":""}'
        ]
    )
    monkeypatch.setattr(analyze, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(analyze, "get_s3_client", lambda: MemoryS3(key, _png_bytes()))
    monkeypatch.setattr(analyze, "_bedrock_client", lambda timeout: bedrock)

    with caplog.at_level("INFO", logger="drink-log-analyze"):
        response = analyze.lambda_handler(
            _event(key),
            SequencedContext([10_000, 10_000, 1_000]),
        )

    body = json.loads(response["body"])
    saved = next(iter(dynamodb.app.items.values()))
    assert response["statusCode"] == 200
    assert body["candidates"][0]["match_source"] == "ai"
    assert '"shortlist_size": 0' in caplog.text
    assert "shortlist" not in body
    assert "shortlist" not in saved


def test_ownership_is_rejected_before_aws_calls(monkeypatch):
    key = f"tmp/other/{uuid.uuid4()}.jpg"
    monkeypatch.setattr(analyze, "get_dynamodb_resource", lambda: pytest.fail("must not create client"))
    response = analyze.lambda_handler(_event(key), Context())
    assert response["statusCode"] == 403


def test_invalid_model_allowlist_and_nonlocal_mock_are_startup_errors(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_ID", "global.forbidden")
    with pytest.raises(RuntimeError):
        analyze.lambda_handler(_event(f"tmp/user-1/{uuid.uuid4()}.jpg"), Context())
    monkeypatch.setenv("BEDROCK_MODEL_ID", "jp.amazon.nova-2-lite-v1:0")
    monkeypatch.setenv("MOCK_AI", "1")
    with pytest.raises(RuntimeError, match="local"):
        analyze.lambda_handler(_event(f"tmp/user-1/{uuid.uuid4()}.jpg"), Context())


def test_invalid_magic_bytes_are_rejected_before_bedrock(monkeypatch):
    key = f"tmp/user-1/{uuid.uuid4()}.jpg"
    s3 = MemoryS3(key, b"not-an-image")
    dynamodb = FakeDynamoDB()
    monkeypatch.setattr(analyze, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(analyze, "get_s3_client", lambda: s3)
    monkeypatch.setattr(analyze, "_bedrock_client", lambda timeout: pytest.fail("must not invoke"))
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
    monkeypatch.setattr(analyze, "_bedrock_client", lambda timeout: pytest.fail("must not invoke"))
    response = analyze.lambda_handler(_event(key), Context())
    assert response["statusCode"] == 500


def test_low_remaining_time_consumes_user_request_but_degrades_without_invocation(monkeypatch):
    key = f"tmp/user-1/{uuid.uuid4()}.png"
    dynamodb = FakeDynamoDB(whiskeys=WhiskeyTable(match=False))
    monkeypatch.setattr(analyze, "get_dynamodb_resource", lambda: dynamodb)
    monkeypatch.setattr(analyze, "get_s3_client", lambda: MemoryS3(key, _png_bytes()))
    monkeypatch.setattr(analyze, "_bedrock_client", lambda timeout: pytest.fail("must not invoke"))
    response = analyze.lambda_handler(_event(key), Context(remaining=1_000))
    assert response["statusCode"] == 200
    assert json.loads(response["body"])["candidates"] == []
    saved = next(iter(dynamodb.app.items.values()))
    assert "label_text" not in saved
    assert [len(transaction) for transaction in dynamodb.meta.client.transactions] == [1]


def test_monthly_analysis_limit_is_a_503_circuit_breaker():
    class MonthlyLimitClient(RecordingClient):
        def transact_write_items(self, **kwargs):
            del kwargs
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
