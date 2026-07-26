import json
from pathlib import Path

import pytest

from scripts import extract_whiskey_names_claude_sonnet as extraction


BRANDS_PATH = Path(__file__).parents[1] / "scripts" / "catalog" / "brands.json"
BOTTLERS_PATH = Path(__file__).parents[1] / "scripts" / "catalog" / "bottlers.json"


def model_result(source_title, **overrides):
    result = {
        "source_title": source_title,
        "is_whiskey": True,
        "is_multi_bottle_set": False,
        "brand_ja": None,
        "brand_en": None,
        "distillery_ja": None,
        "bottler_ja": None,
        "bottler_en": None,
        "expression": None,
        "edition": None,
        "age": None,
        "vintage": None,
        "cask": None,
        "abv": None,
        "volume_ml": None,
        "confidence": 0.9,
    }
    result.update(overrides)
    return result


def sanitized(source_title, **overrides):
    return extraction.sanitize_model_result(
        model_result(source_title, **overrides),
        source_title,
        bottlers=extraction.load_bottlers(BOTTLERS_PATH),
    )


@pytest.fixture
def brands():
    return extraction.load_brands(BRANDS_PATH)


@pytest.fixture
def bottlers():
    return extraction.load_bottlers(BOTTLERS_PATH)


def test_multi_bottle_sets_and_non_whiskey_items_are_excluded(brands):
    records = [
        sanitized(
            "ウイスキー4本セット 角、デュワーズ、ベル",
            is_multi_bottle_set=True,
            brand_ja="デュワーズ",
        ),
        sanitized(
            "ウイスキーグラス 2脚",
            is_whiskey=False,
            is_multi_bottle_set=False,
        ),
        sanitized("アラン 10年 700ml", brand_ja="アラン", age=10, volume_ml=700),
    ]

    expressions, _, _, summary = extraction.build_catalog_outputs(
        records, brands, extraction.DEFAULT_MODEL_ID, "2026-07-26T00:00:00+00:00"
    )

    assert len(expressions) == 1
    assert summary == {
        "total": 3,
        "whiskey": 2,
        "set_excluded": 1,
        "deduplicated": 1,
        "known_brand": 1,
        "unknown_brand": 0,
        "unknown_bottler": 0,
    }


def test_golden_cask_and_macduff_are_separated_after_measured_model_failure():
    title = "ゴールデンカスク マクダフ 10年 2012 63.8% 700ml"

    record = sanitized(
        title,
        brand_ja="ゴールデンカスク マクダフ",
        age=10,
        vintage=2012,
        abv="63.8%",
        volume_ml=700,
    )

    assert record["brand_ja"] == "マクダフ"
    assert record["bottler_ja"] == "ゴールデンカスク"
    assert record["age"] == 10
    assert record["vintage"] == 2012


@pytest.mark.parametrize(
    ("title", "model_brand", "expected_brand", "expected_bottler"),
    [
        (
            "ダグラスレイン プロベナンス カリラ 8年",
            "ダグラスレイン プロベナンス カリラ",
            "カリラ",
            "ダグラスレイン",
        ),
        (
            "シグナトリー ポートダンダス 15年 2006",
            "シグナトリー ポートダンダス",
            "ポートダンダス",
            "シグナトリー",
        ),
        (
            "モートラック 30年 キングスバリー サー オービル 1995",
            "モートラック キングスバリー サー オービル",
            "モートラック",
            "キングスバリー",
        ),
    ],
)
def test_curated_bottlers_are_separated_regardless_of_title_position(
    title, model_brand, expected_brand, expected_bottler
):
    record = sanitized(title, brand_ja=model_brand)

    assert record["brand_ja"] == expected_brand
    assert record["bottler_ja"] == expected_bottler
    assert record["bottler_key"]


def test_bottler_separation_stops_when_definition_is_removed(tmp_path):
    document = json.loads(BOTTLERS_PATH.read_text(encoding="utf-8"))
    document["bottlers"] = [
        bottler
        for bottler in document["bottlers"]
        if bottler["bottler_ja"] != "ダグラスレイン"
    ]
    reduced_path = tmp_path / "bottlers.json"
    reduced_path.write_text(
        json.dumps(document, ensure_ascii=False), encoding="utf-8"
    )
    reduced_bottlers = extraction.load_bottlers(reduced_path)
    title = "ダグラスレイン プロベナンス カリラ 8年"

    record = extraction.sanitize_model_result(
        model_result(
            title,
            brand_ja="ダグラスレイン プロベナンス カリラ",
            age=8,
        ),
        title,
        bottlers=reduced_bottlers,
    )

    assert record["brand_ja"] == "ダグラスレイン プロベナンス カリラ"
    assert record.get("bottler_key") is None
    assert record["bottler_ja"] is None


def test_different_bottlers_produce_different_catalog_keys(brands, bottlers):
    records = [
        extraction.sanitize_model_result(
            model_result(
                "ダグラスレイン プロベナンス カリラ 8年",
                brand_ja="ダグラスレイン プロベナンス カリラ",
                age=8,
            ),
            "ダグラスレイン プロベナンス カリラ 8年",
            bottlers=bottlers,
        ),
        extraction.sanitize_model_result(
            model_result(
                "シグナトリー カリラ 8年",
                brand_ja="シグナトリー カリラ",
                age=8,
            ),
            "シグナトリー カリラ 8年",
            bottlers=bottlers,
        ),
    ]

    expressions, _, _, _ = extraction.build_catalog_outputs(
        records,
        brands,
        extraction.DEFAULT_MODEL_ID,
        "2026-07-26T00:00:00+00:00",
        bottlers=bottlers,
    )

    assert len(expressions) == 2
    assert {record["brand_ja"] for record in expressions} == {"カリラ"}
    assert len({record["catalog_key"] for record in expressions}) == 2
    assert len({record["bottler_key"] for record in expressions}) == 2


def test_brand_is_null_when_alias_removal_leaves_no_brand():
    title = "シグナトリー 15年 2006"

    record = sanitized(title, brand_ja="シグナトリー", age=15, vintage=2006)

    assert record["brand_ja"] is None
    assert record["brand_en"] is None
    assert record["bottler_ja"] == "シグナトリー"


def test_volume_is_not_identity_and_duplicate_titles_are_aggregated(brands):
    records = [
        sanitized(
            "アラン バレルリザーヴ 700ml 43度",
            brand_ja="アラン",
            expression="バレルリザーヴ",
            abv="43",
            volume_ml=700,
        ),
        sanitized(
            "アラン バレルリザーヴ 750ml 43度",
            brand_ja="アラン",
            expression="バレルリザーヴ",
            abv="43",
            volume_ml=750,
            confidence=0.95,
        ),
    ]

    expressions, _, _, summary = extraction.build_catalog_outputs(
        records, brands, extraction.DEFAULT_MODEL_ID, "2026-07-26T00:00:00+00:00"
    )

    assert len(expressions) == 1
    assert expressions[0]["catalog_key"] == extraction.catalog_key(
        {
            "brand_key": "arran",
            "expression_code": "バレルリザーヴ",
            "age": None,
            "edition": None,
            "cask": None,
            "vintage": None,
            "bottler": None,
        }
    )
    assert expressions[0]["source_title"] == records[0]["source_title"]
    assert expressions[0]["source_titles"] == [
        record["source_title"] for record in records
    ]
    assert expressions[0]["confidence"] == 0.95
    assert summary["deduplicated"] == 1


def test_vintage_and_cask_changes_produce_different_catalog_keys(brands):
    records = [
        sanitized(
            "マクダフ 10年 2012 ホグスヘッド",
            brand_ja="マクダフ",
            age=10,
            vintage=2012,
            cask="ホグスヘッド",
        ),
        sanitized(
            "マクダフ 10年 2013 ホグスヘッド",
            brand_ja="マクダフ",
            age=10,
            vintage=2013,
            cask="ホグスヘッド",
        ),
        sanitized(
            "マクダフ 10年 2012 シェリーバット",
            brand_ja="マクダフ",
            age=10,
            vintage=2012,
            cask="シェリーバット",
        ),
    ]

    expressions, _, _, _ = extraction.build_catalog_outputs(
        records, brands, extraction.DEFAULT_MODEL_ID, "2026-07-26T00:00:00+00:00"
    )

    assert len(expressions) == 3
    assert len({record["catalog_key"] for record in expressions}) == 3


class StubBedrock:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        indexed_results = [
            {"input_index": index, **result}
            for index, result in enumerate(self.results, start=1)
        ]
        return {
            "output": {
                "message": {
                    "content": [{"text": json.dumps({"results": indexed_results})}]
                }
            }
        }


def test_unknown_bottler_is_proposed_without_modifying_curated_catalog(tmp_path):
    titles = [
        f"ミステリーボトラー カリラ 8年 2012 ホグスヘッド ロット{index}"
        for index in range(4)
    ]
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps({"product_names": titles}), encoding="utf-8")
    output_path = tmp_path / "expressions.json"
    bottler_proposals_path = tmp_path / "proposed_bottlers.json"
    original_bottlers = BOTTLERS_PATH.read_bytes()
    stub = StubBedrock(
        [
            model_result(
                title,
                brand_ja="カリラ",
                bottler_ja="ミステリーボトラー",
                age=8,
                vintage=2012,
                cask="ホグスヘッド",
            )
            for title in titles
        ]
    )
    extractor = extraction.ClaudeSonnetWhiskeyExtractor(
        bedrock_client=stub,
        now_fn=lambda: "2026-07-26T00:00:00+00:00",
    )

    summary = extractor.process_file(
        input_path,
        output_path=output_path,
        proposals_path=tmp_path / "proposed_brands.json",
        bottler_proposals_path=bottler_proposals_path,
        checkpoint_path=tmp_path / "checkpoint.json",
    )

    output = json.loads(output_path.read_text(encoding="utf-8"))
    proposals = json.loads(bottler_proposals_path.read_text(encoding="utf-8"))
    assert summary["unknown_bottler"] == 4
    assert proposals["proposed_bottlers"] == [
        {
            "bottler_key": proposals["proposed_bottlers"][0]["bottler_key"],
            "observed_variants": ["ミステリーボトラー"],
            "occurrence_count": 4,
            "sample_source_titles": titles[:3],
        }
    ]
    assert output["expressions"][0]["brand_key"] is None
    assert output["expressions"][0]["brand_ja"] is None
    assert output["expressions"][0]["brand_en"] is None
    assert BOTTLERS_PATH.read_bytes() == original_bottlers


def test_unknown_bottler_prefix_is_proposed_when_model_mixes_it_into_brand(
    brands, bottlers
):
    title = "ミステリーボトラー カリラ 8年 2012 ホグスヘッド"
    record = extraction.sanitize_model_result(
        model_result(
            title,
            brand_ja="ミステリーボトラー カリラ",
            age=8,
            vintage=2012,
            cask="ホグスヘッド",
        ),
        title,
        bottlers=bottlers,
    )

    expressions, brand_proposals, bottler_proposals, summary = (
        extraction.build_catalog_outputs(
            [record],
            brands,
            extraction.DEFAULT_MODEL_ID,
            "2026-07-26T00:00:00+00:00",
            bottlers=bottlers,
        )
    )

    assert expressions[0]["brand_key"] is None
    assert expressions[0]["brand_ja"] is None
    assert brand_proposals == []
    assert bottler_proposals[0]["observed_variants"] == ["ミステリーボトラー"]
    assert summary["unknown_bottler"] == 1


def test_prompt_contains_all_curated_bottlers_as_reference(bottlers):
    extractor = extraction.ClaudeSonnetWhiskeyExtractor()

    prompt = extractor.create_extraction_prompt(["テスト商品"])

    for bottler in bottlers.values():
        assert bottler["bottler_key"] in prompt
        assert bottler["bottler_ja"] in prompt
    assert "do not invent aliases" in prompt


def test_unknown_brand_review_output_does_not_modify_brands_or_accept_aliases(
    tmp_path,
):
    titles = [
        "マクダフ 10年 2012 700ml",
        "マクダフ 10年 2012 750ml",
    ]
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps({"product_names": titles}), encoding="utf-8")
    original_brands = BRANDS_PATH.read_bytes()
    output_path = tmp_path / "extracted_expressions.json"
    proposals_path = tmp_path / "proposed_brands.json"
    checkpoint_path = tmp_path / "checkpoint.json"
    stub = StubBedrock(
        [
            model_result(
                titles[0],
                brand_ja="マクダフ",
                age=10,
                vintage=2012,
                volume_ml=700,
                aliases=["Macduff", "架空の別名"],
            ),
            model_result(
                titles[1],
                brand_ja="マクダフ",
                age=10,
                vintage=2012,
                volume_ml=750,
                aliases=["Macduff"],
            ),
        ]
    )
    extractor = extraction.ClaudeSonnetWhiskeyExtractor(
        bedrock_client=stub,
        now_fn=lambda: "2026-07-26T00:00:00+00:00",
    )

    summary = extractor.process_file(
        input_path,
        brands_path=BRANDS_PATH,
        output_path=output_path,
        proposals_path=proposals_path,
        bottler_proposals_path=tmp_path / "proposed_bottlers.json",
        checkpoint_path=checkpoint_path,
    )

    output = json.loads(output_path.read_text(encoding="utf-8"))
    proposals = json.loads(proposals_path.read_text(encoding="utf-8"))
    assert summary["unknown_brand"] == 2
    assert len(output["expressions"]) == 1
    assert output["expressions"][0]["source_title"] == titles[0]
    assert output["expressions"][0]["source_titles"] == titles
    assert output["expressions"][0]["source"] == "rakuten_bedrock"
    assert output["expressions"][0]["is_whiskey"] is True
    assert output["expressions"][0]["is_multi_bottle_set"] is False
    assert output["expressions"][0]["extraction_model"] == extraction.DEFAULT_MODEL_ID
    assert output["expressions"][0]["extracted_at"] == "2026-07-26T00:00:00+00:00"
    assert proposals["proposed_brands"] == [
        {
            "brand_key": "proposed_18dc05f0e2",
            "observed_variants": ["マクダフ"],
            "occurrence_count": 2,
            "sample_source_titles": titles,
        }
    ]
    assert "aliases" not in json.dumps(output, ensure_ascii=False)
    assert "架空の別名" not in json.dumps(proposals, ensure_ascii=False)
    assert BRANDS_PATH.read_bytes() == original_brands
    assert not checkpoint_path.exists()
    assert len(stub.calls) == 1
    assert stub.calls[0]["modelId"] == extraction.DEFAULT_MODEL_ID
    assert (
        stub.calls[0]["inferenceConfig"]["maxTokens"] == extraction.DEFAULT_MAX_TOKENS
    )


def test_source_title_is_restored_from_input_instead_of_model_output():
    real_title = "アラン 10年 700ml"
    raw = model_result(
        "モデルが改変したタイトル",
        input_index=1,
        brand_ja="アラン",
        age=10,
        volume_ml=700,
    )

    records = extraction.map_batch_results([real_title], [raw])

    assert records[0]["source_title"] == real_title


def test_date_code_is_not_accepted_as_a_vintage():
    title = "グレンリベット 21年 700ml 43% 20250827"

    record = sanitized(
        title,
        brand_ja="グレンリベット",
        age=21,
        vintage=2025,
        abv="43",
        volume_ml=700,
    )

    assert record["age"] == 21
    assert record["vintage"] is None
    assert record["abv"] == "43"
    assert record["volume_ml"] == 700


def test_dry_run_honors_limit_without_creating_a_bedrock_client(tmp_path, capsys):
    input_path = tmp_path / "input.json"
    input_path.write_text(
        json.dumps({"product_names": [f"title-{index}" for index in range(45)]}),
        encoding="utf-8",
    )
    extractor = extraction.ClaudeSonnetWhiskeyExtractor(batch_size=20)

    result = extractor.process_file(input_path, limit=21, dry_run=True)

    assert result is None
    assert extractor.bedrock is None
    output = capsys.readouterr().out
    assert "処理対象: 21件" in output
    assert "バッチ数: 2" in output
    assert "Bedrock予定コール数: 2（リトライ込み最大 4 コール）" in output


def test_checkpoint_is_resumed_without_reprocessing_completed_titles(tmp_path, brands):
    titles = ["アラン 10年 700ml", "アラン 18年 700ml"]
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps({"product_names": titles}), encoding="utf-8")
    checkpoint_path = tmp_path / "checkpoint.json"
    first = sanitized(titles[0], brand_ja="アラン", age=10, volume_ml=700)
    extraction.write_json(
        checkpoint_path,
        {
            "version": 1,
            "input_file": str(input_path.resolve()),
            "input_fingerprint": extraction.titles_fingerprint(titles),
            "model_id": extraction.DEFAULT_MODEL_ID,
            "batch_size": 1,
            "next_index": 1,
            "extracted_at": "2026-07-26T00:00:00+00:00",
            "raw_results": [first],
        },
    )
    stub = StubBedrock(
        [model_result(titles[1], brand_ja="アラン", age=18, volume_ml=700)]
    )
    extractor = extraction.ClaudeSonnetWhiskeyExtractor(
        batch_size=1,
        bedrock_client=stub,
        now_fn=lambda: "2026-07-27T00:00:00+00:00",
    )
    output_path = tmp_path / "output.json"

    extractor.process_file(
        input_path,
        brands_path=BRANDS_PATH,
        output_path=output_path,
        proposals_path=tmp_path / "proposals.json",
        bottler_proposals_path=tmp_path / "bottler-proposals.json",
        checkpoint_path=checkpoint_path,
    )

    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert len(stub.calls) == 1
    assert {record["age"] for record in output["expressions"]} == {10, 18}
    assert {record["extracted_at"] for record in output["expressions"]} == {
        "2026-07-26T00:00:00+00:00"
    }
