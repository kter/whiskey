import json
from pathlib import Path

import pytest

from scripts import extract_whiskey_names_claude_sonnet as extraction


BRANDS_PATH = Path(__file__).parents[1] / "scripts" / "catalog" / "brands.json"
BOTTLERS_PATH = Path(__file__).parents[1] / "scripts" / "catalog" / "bottlers.json"


def model_result(_source_title, **overrides):
    result = {
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
            for index, result in enumerate(self.results)
        ]
        return {
            "output": {
                "message": {
                    "content": [{"text": json.dumps({"results": indexed_results})}]
                }
            }
        }


class CallbackBedrock:
    def __init__(self, callback):
        self.callback = callback
        self.calls = []
        self.call_title_batches = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        prompt = kwargs["messages"][0]["content"][0]["text"]
        inputs = json.loads(prompt.split("Inputs:\n", maxsplit=1)[1])
        titles = [item["source_title"] for item in inputs]
        self.call_title_batches.append(titles)
        response_text = self.callback(titles)
        return {
            "output": {
                "message": {
                    "content": [{"text": response_text}]
                }
            }
        }


def valid_response(titles, **overrides):
    results = [
        {"input_index": index, **model_result(title, **overrides)}
        for index, title in enumerate(titles)
    ]
    return json.dumps({"results": results}, ensure_ascii=False)


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
    output_schema = prompt.split("Return JSON only in this shape:", maxsplit=1)[1]
    output_schema = output_schema.split("Known bottlers", maxsplit=1)[0]
    assert '"source_title"' not in output_schema


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
            "suggested_aliases": ["マクダフ"],
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


@pytest.mark.parametrize(
    ("title", "brand_ja", "expected_brand_key"),
    [
        ("ザ・マッカラン 12年 700ml", "ザ・マッカラン", "macallan"),
        ("ザ グレンリベット 12年 700ml", "ザ グレンリベット", "glenlivet"),
    ],
)
def test_japanese_leading_article_matches_known_brand_without_proposal(
    brands, title, brand_ja, expected_brand_key
):
    record = sanitized(title, brand_ja=brand_ja, age=12, volume_ml=700)

    expressions, proposals, _, summary = extraction.build_catalog_outputs(
        [record],
        brands,
        extraction.DEFAULT_MODEL_ID,
        "2026-07-26T00:00:00+00:00",
    )

    assert expressions[0]["brand_key"] == expected_brand_key
    assert proposals == []
    assert summary["known_brand"] == 1
    assert summary["unknown_brand"] == 0


def test_japanese_article_removal_is_limited_to_the_start():
    value = "ニッカ ザ ネッサンス"

    assert extraction.comparison_keys(value) == {
        extraction.normalize_label(value)
    }
    assert (
        extraction.normalize_label("ニッカ ネッサンス")
        not in extraction.comparison_keys(value)
    )


@pytest.mark.parametrize("value", ["ザ・響", "ザ AB", "THE A B"])
def test_article_is_not_removed_when_only_one_or_two_characters_remain(value):
    assert extraction.comparison_keys(value) == {
        extraction.normalize_label(value)
    }


def _unknown_brand_proposals(records):
    _, proposals, _, _ = extraction.build_catalog_outputs(
        records,
        {},
        extraction.DEFAULT_MODEL_ID,
        "2026-07-26T00:00:00+00:00",
    )
    return proposals


def test_japanese_only_and_later_english_brand_observations_are_merged():
    records = [
        sanitized("ジムビーム 700ml", brand_ja="ジムビーム", volume_ml=700),
        sanitized(
            "Jim Beam ジムビーム 1000ml",
            brand_ja="ジムビーム",
            brand_en="Jim Beam",
            volume_ml=1000,
        ),
    ]

    expressions, proposals, _, _ = extraction.build_catalog_outputs(
        records,
        {},
        extraction.DEFAULT_MODEL_ID,
        "2026-07-26T00:00:00+00:00",
    )

    assert len(expressions) == 1
    assert expressions[0]["brand_key"] == "jim_beam"
    assert proposals == [
        {
            "brand_key": "jim_beam",
            "observed_variants": ["ジムビーム", "Jim Beam"],
            "occurrence_count": 2,
            "sample_source_titles": [record["source_title"] for record in records],
            "suggested_aliases": ["ジムビーム", "Jim Beam"],
        }
    ]


def test_merged_brand_key_does_not_depend_on_observation_order():
    records = [
        sanitized("ジムビーム 700ml", brand_ja="ジムビーム", volume_ml=700),
        sanitized(
            "Jim Beam ジムビーム 1000ml",
            brand_ja="ジムビーム",
            brand_en="Jim Beam",
            volume_ml=1000,
        ),
    ]

    forward = _unknown_brand_proposals(records)
    reversed_order = _unknown_brand_proposals(list(reversed(records)))

    assert forward[0]["brand_key"] == "jim_beam"
    assert reversed_order[0]["brand_key"] == forward[0]["brand_key"]


def test_suggested_aliases_contain_only_observed_variants():
    records = [
        sanitized(
            "AMAHAGAN アマハガン 700ml",
            brand_ja="アマハガン",
            brand_en="AMAHAGAN",
            volume_ml=700,
        ),
        sanitized("アマハガン 500ml", brand_ja="アマハガン", volume_ml=500),
    ]

    proposal = _unknown_brand_proposals(records)[0]

    assert set(proposal["suggested_aliases"]) == {"アマハガン", "AMAHAGAN"}
    assert proposal["suggested_aliases"] == proposal["observed_variants"]


def test_similar_but_not_exact_english_brands_are_not_fuzzy_merged():
    records = [
        sanitized("Arran 10 years old", brand_en="Arran", age=10),
        sanitized("Aran 10 years old", brand_en="Aran", age=10),
    ]

    proposals = _unknown_brand_proposals(records)

    assert len(proposals) == 2
    assert {proposal["brand_key"] for proposal in proposals} == {"arran", "aran"}
    assert {tuple(proposal["observed_variants"]) for proposal in proposals} == {
        ("Arran",),
        ("Aran",),
    }


def test_brand_proposals_are_sorted_by_descending_occurrence_count():
    records = [
        sanitized(f"Alpha ロット{index}", brand_en="Alpha")
        for index in range(3)
    ]
    records.extend(
        [
            sanitized("Beta 700ml", brand_en="Beta", volume_ml=700),
            sanitized("Gamma 700ml", brand_en="Gamma", volume_ml=700),
            sanitized("Gamma 1000ml", brand_en="Gamma", volume_ml=1000),
        ]
    )

    proposals = _unknown_brand_proposals(records)

    assert [proposal["occurrence_count"] for proposal in proposals] == [3, 2, 1]
    assert [proposal["brand_key"] for proposal in proposals] == [
        "alpha",
        "gamma",
        "beta",
    ]


def test_source_title_with_quotes_is_restored_from_input_without_model_field():
    real_title = (
        "【ウイスキー】イチローズモルト　モルト＆グレーン　"
        "“クラシカルエディション”　700ml　2本セット"
    )
    raw = model_result(
        real_title,
        input_index=0,
        brand_ja="イチローズモルト",
        volume_ml=700,
    )

    records = extraction.map_batch_results([real_title], [raw])

    assert "source_title" not in raw
    assert records[0]["source_title"] == real_title
    assert "source_title" not in extraction.MODEL_RESULT_FIELDS


def test_missing_input_index_is_discarded_with_warning(caplog):
    titles = ["アラン 10年 700ml", "アラン 18年 700ml"]
    missing = model_result(titles[0], age=10)
    valid = model_result(titles[1], input_index=1, age=18)

    records = extraction.map_batch_results(titles, [missing, valid])

    assert [record["source_title"] for record in records] == [titles[1]]
    assert "missing input_index" in caplog.text
    assert "No valid model result for input_index: 0" in caplog.text


def test_duplicate_and_out_of_range_input_indexes_are_discarded(caplog):
    titles = ["アラン 10年 700ml", "アラン 18年 700ml"]
    results = [
        model_result(titles[0], input_index=0, age=10),
        model_result(titles[0], input_index=0, age=10),
        model_result(titles[1], input_index=2, age=18),
    ]

    records = extraction.map_batch_results(titles, results)

    assert records == []
    assert "duplicate model results for input_index: 0" in caplog.text
    assert "out-of-range input_index: 2" in caplog.text


def test_reapplied_source_title_still_rejects_invented_values():
    title = "アラン 10年 700ml"
    raw = model_result(
        title,
        input_index=0,
        brand_ja="アラン",
        expression="モデルが発明した表現",
        age=10,
        volume_ml=700,
    )

    records = extraction.map_batch_results([title], [raw])

    assert records[0]["source_title"] == title
    assert records[0]["brand_ja"] == "アラン"
    assert records[0]["expression"] is None
    assert records[0]["age"] == 10


def test_response_json_accepts_fences_and_surrounding_text():
    response = (
        "Extraction follows.\n```json\n"
        '{"results": [{"input_index": 0}]}'
        "\n```\nDone."
    )

    parsed = extraction.parse_response_json(response)

    assert parsed == {"results": [{"input_index": 0}]}


def test_broken_batch_continues_writes_successes_and_returns_nonzero(
    tmp_path, monkeypatch, capsys
):
    titles = ["壊れる商品", "アラン 10年 700ml"]
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps({"product_names": titles}), encoding="utf-8")

    def response(titles_in_call):
        if titles_in_call == ["壊れる商品"]:
            return '{"results": [{"input_index": 0, "is_whiskey": true'
        return valid_response(
            titles_in_call,
            brand_ja="アラン",
            age=10,
            volume_ml=700,
        )

    stub = CallbackBedrock(response)
    extractor = extraction.ClaudeSonnetWhiskeyExtractor(
        batch_size=1,
        bedrock_client=stub,
        now_fn=lambda: "2026-07-26T00:00:00+00:00",
        failed_batches_dir=tmp_path / "failed_batches",
    )
    monkeypatch.setattr(
        extraction, "ClaudeSonnetWhiskeyExtractor", lambda: extractor
    )
    output_path = tmp_path / "output.json"

    exit_code = extraction.main(
        [
            "--input-file",
            str(input_path),
            "--output-file",
            str(output_path),
            "--proposed-brands-file",
            str(tmp_path / "proposed-brands.json"),
            "--proposed-bottlers-file",
            str(tmp_path / "proposed-bottlers.json"),
            "--checkpoint-file",
            str(tmp_path / "checkpoint.json"),
        ]
    )

    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert len(output["expressions"]) == 1
    assert output["expressions"][0]["source_title"] == titles[1]
    assert output["metadata"]["failed_batch_count"] == 1
    assert output["metadata"]["failed_batches"] == [
        {
            "batch_number": 1,
            "start_index": 0,
            "end_index": 0,
            "failed_indexes": [0],
        }
    ]
    summary_output = capsys.readouterr().out
    assert "失敗バッチ数: 1" in summary_output
    assert "対象インデックス 0-0" in summary_output
    assert len(stub.calls) == 2


def test_retry_shrinks_20_to_halves_then_singletons_and_recovers_19(tmp_path):
    titles = [f"title-{index}" for index in range(20)]
    broken_title = titles[0]

    def response(titles_in_call):
        if broken_title in titles_in_call:
            return '{"results": [{"input_index": 0, "is_whiskey": true'
        return valid_response(titles_in_call)

    stub = CallbackBedrock(response)
    extractor = extraction.ClaudeSonnetWhiskeyExtractor(
        bedrock_client=stub,
        failed_batches_dir=tmp_path / "failed_batches",
    )

    records = extractor.process_batch(titles, batch_start_index=100)

    assert [len(batch) for batch in stub.call_title_batches] == [
        20,
        10,
        10,
        *([1] * 10),
    ]
    assert len(records) == 19
    assert {record["source_title"] for record in records} == set(titles[1:])
    assert {record["_input_index"] for record in records} == set(range(1, 20))


def test_failed_raw_response_is_saved_and_logged_with_context(tmp_path, caplog):
    malformed = (
        '{"results": [{"input_index": 0, "is_whiskey": true, '
        '"expression": "broken "quote""}]}'
    )
    stub = CallbackBedrock(lambda _titles: malformed)
    failed_dir = tmp_path / "failed_batches"
    extractor = extraction.ClaudeSonnetWhiskeyExtractor(
        bedrock_client=stub,
        failed_batches_dir=failed_dir,
    )

    assert extractor.process_batch(["broken"], batch_start_index=42) == []

    saved = list(failed_dir.glob("*_42.txt"))
    assert len(saved) == 1
    assert saved[0].read_text(encoding="utf-8") == malformed
    assert "first 200 chars=" in caplog.text
    assert "context (+/-100 chars)=" in caplog.text


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
    assert "Bedrock予定コール数: 2（リトライ込み最大 24 コール）" in output


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
