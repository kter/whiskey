from decimal import Decimal
from types import SimpleNamespace

import boto3
import pytest
from moto import mock_aws

from tests.lambda_module_loader import load_lambda_module


aggregator = load_lambda_module(
    "ranking_aggregator_lambda_tests",
    "lambda/ranking-aggregator/index.py",
)


@pytest.fixture
def ranking_tables(monkeypatch):
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="ap-northeast-1")
        for name, key in (
            ("Reviews-test", "id"),
            ("WhiskeySearch-test", "id"),
            ("AppState-test", "pk"),
        ):
            dynamodb.create_table(
                TableName=name,
                KeySchema=[{"AttributeName": key, "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": key, "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
            )
        monkeypatch.setenv("REVIEWS_TABLE", "Reviews-test")
        monkeypatch.setenv("WHISKEY_SEARCH_TABLE", "WhiskeySearch-test")
        monkeypatch.setenv("APP_STATE_TABLE", "AppState-test")
        app_state = dynamodb.Table("AppState-test")
        app_state.put_item(Item={"pk": aggregator.REVIEW_COUNTER_KEY, "count": 1})
        app_state.put_item(Item={"pk": aggregator.WHISKEY_COUNTER_KEY, "count": 1})
        yield dynamodb


def context():
    return SimpleNamespace(get_remaining_time_in_millis=lambda: 120_000)


def seed_sources(dynamodb):
    reviews = dynamodb.Table("Reviews-test")
    reviews.put_item(
        Item={
            "id": "r1",
            "whiskey_id": "w1",
            "rating": Decimal("4"),
            "is_public": True,
        }
    )
    reviews.put_item(
        Item={
            "id": "r2",
            "whiskey_id": "w2",
            "rating": Decimal("5"),
            "is_public": False,
        }
    )
    whiskeys = dynamodb.Table("WhiskeySearch-test")
    whiskeys.put_item(Item={"id": "w1", "name": "One"})
    whiskeys.put_item(Item={"id": "w2", "name": "Two"})


def test_generation_publish_switches_atomically_and_expires_old_generation(ranking_tables):
    seed_sources(ranking_tables)
    first = aggregator.aggregate_rankings({}, context(), ranking_tables)
    assert first["status"] == "published"
    app_state = ranking_tables.Table("AppState-test")
    first_meta = app_state.get_item(Key={"pk": aggregator.RANKING_META_KEY})["Item"]
    first_page_key = aggregator._page_key(first_meta["generation_id"], 0)
    first_page = app_state.get_item(Key={"pk": first_page_key})["Item"]
    assert "ttl" not in first_page
    assert first_page["rankings"][0]["id"] == "w1"
    assert first_page["rankings"][0]["review_count"] == 1

    app_state.update_item(
        Key={"pk": aggregator.REVIEW_COUNTER_KEY},
        UpdateExpression="ADD #count :one",
        ExpressionAttributeNames={"#count": "count"},
        ExpressionAttributeValues={":one": 1},
    )
    second = aggregator.aggregate_rankings({}, context(), ranking_tables)
    assert second["status"] == "published"
    second_meta = app_state.get_item(Key={"pk": aggregator.RANKING_META_KEY})["Item"]
    assert second_meta["generation_id"] != first_meta["generation_id"]
    assert "dirty_since" not in second_meta
    assert "ttl" in app_state.get_item(Key={"pk": first_page_key})["Item"]


def test_missing_current_page_forces_regeneration_even_when_counters_are_clean(ranking_tables):
    seed_sources(ranking_tables)
    first = aggregator.aggregate_rankings({}, context(), ranking_tables)
    app_state = ranking_tables.Table("AppState-test")
    app_state.delete_item(Key={"pk": aggregator._page_key(first["generation_id"], 0)})
    second = aggregator.aggregate_rankings({}, context(), ranking_tables)
    assert second["status"] == "published"
    assert second["generation_id"] != first["generation_id"]


def test_counter_change_during_scan_does_not_clean_or_switch_generation(ranking_tables, monkeypatch):
    seed_sources(ranking_tables)
    first = aggregator.aggregate_rankings({}, context(), ranking_tables)
    app_state = ranking_tables.Table("AppState-test")
    app_state.update_item(
        Key={"pk": aggregator.REVIEW_COUNTER_KEY},
        UpdateExpression="ADD #count :one",
        ExpressionAttributeNames={"#count": "count"},
        ExpressionAttributeValues={":one": 1},
    )
    original_scan = aggregator._scan_sources

    def changing_scan(dynamodb, lambda_context):
        result = original_scan(dynamodb, lambda_context)
        app_state.update_item(
            Key={"pk": aggregator.REVIEW_COUNTER_KEY},
            UpdateExpression="ADD #count :one",
            ExpressionAttributeNames={"#count": "count"},
            ExpressionAttributeValues={":one": 1},
        )
        return result

    monkeypatch.setattr(aggregator, "_scan_sources", changing_scan)
    result = aggregator.aggregate_rankings({}, context(), ranking_tables)
    assert result == {"status": "dirty"}
    meta = app_state.get_item(Key={"pk": aggregator.RANKING_META_KEY})["Item"]
    assert meta["generation_id"] == first["generation_id"]
    assert "dirty_since" in meta


@pytest.mark.parametrize("with_existing_generation", [False, True])
def test_invalidation_before_activation_supersedes_and_expires_staging_generation(
    ranking_tables,
    monkeypatch,
    with_existing_generation,
):
    seed_sources(ranking_tables)
    app_state = ranking_tables.Table("AppState-test")
    old_generation = None
    if with_existing_generation:
        first = aggregator.aggregate_rankings({}, context(), ranking_tables)
        old_generation = first["generation_id"]
        app_state.update_item(
            Key={"pk": aggregator.REVIEW_COUNTER_KEY},
            UpdateExpression="ADD #count :one",
            ExpressionAttributeNames={"#count": "count"},
            ExpressionAttributeValues={":one": 1},
        )

    original_activate = aggregator._activate_generation
    staged = {}

    def invalidate_then_activate(
        table,
        old_meta,
        generation_id,
        page_sizes,
        total_items,
        counters,
    ):
        staged["generation_id"] = generation_id
        staged_page = table.get_item(
            Key={"pk": aggregator._page_key(generation_id, 0)}
        )["Item"]
        assert "ttl" in staged_page
        table.update_item(
            Key={"pk": aggregator.RANKING_META_KEY},
            UpdateExpression="SET invalidated_at = :invalidated_at",
            ExpressionAttributeValues={":invalidated_at": "2026-07-19T00:00:00Z"},
        )
        return original_activate(
            table,
            old_meta,
            generation_id,
            page_sizes,
            total_items,
            counters,
        )

    monkeypatch.setattr(aggregator, "_activate_generation", invalidate_then_activate)
    result = aggregator.aggregate_rankings({}, context(), ranking_tables)

    assert result == {"status": "superseded"}
    meta = app_state.get_item(Key={"pk": aggregator.RANKING_META_KEY})["Item"]
    assert meta["invalidated_at"] == "2026-07-19T00:00:00Z"
    if old_generation:
        assert meta["generation_id"] == old_generation
    staged_page = app_state.get_item(
        Key={"pk": aggregator._page_key(staged["generation_id"], 0)}
    )["Item"]
    assert "ttl" in staged_page


def test_staging_pages_keep_ttl_until_generation_is_activated(ranking_tables, monkeypatch):
    seed_sources(ranking_tables)
    original_activate = aggregator._activate_generation
    observed = {}

    def inspect_then_activate(
        table,
        old_meta,
        generation_id,
        page_sizes,
        total_items,
        counters,
    ):
        observed["had_ttl"] = all(
            "ttl"
            in table.get_item(
                Key={"pk": aggregator._page_key(generation_id, page_number)}
            )["Item"]
            for page_number in range(len(page_sizes))
        )
        return original_activate(
            table,
            old_meta,
            generation_id,
            page_sizes,
            total_items,
            counters,
        )

    monkeypatch.setattr(aggregator, "_activate_generation", inspect_then_activate)
    result = aggregator.aggregate_rankings({}, context(), ranking_tables)

    assert result["status"] == "published"
    assert observed["had_ttl"] is True
    page = ranking_tables.Table("AppState-test").get_item(
        Key={"pk": aggregator._page_key(result["generation_id"], 0)}
    )["Item"]
    assert "ttl" not in page


def test_deadline_exceeded_returns_deferred_and_releases_lease(ranking_tables, monkeypatch):
    monkeypatch.setattr(aggregator, "get_dynamodb_resource", lambda: ranking_tables)
    deadline_context = SimpleNamespace(get_remaining_time_in_millis=lambda: 0)

    assert aggregator.lambda_handler({}, deadline_context) == {"status": "deferred"}
    lease = ranking_tables.Table("AppState-test").get_item(
        Key={"pk": aggregator.RANKING_LEASE_KEY}
    )
    assert "Item" not in lease


def test_owner_lease_rejects_concurrent_owner_and_allows_expired_takeover(ranking_tables):
    table = ranking_tables.Table("AppState-test")
    assert aggregator.acquire_lease(table, "owner-1", "g1", now_epoch=100) == {}
    assert aggregator.acquire_lease(table, "owner-2", "g2", now_epoch=101) is None
    prior = aggregator.acquire_lease(
        table,
        "owner-2",
        "g2",
        now_epoch=100 + aggregator.LEASE_SECONDS + 1,
    )
    assert prior["owner"] == "owner-1"


def test_force_event_rebuilds_clean_generation(ranking_tables):
    seed_sources(ranking_tables)
    first = aggregator.aggregate_rankings({}, context(), ranking_tables)
    second = aggregator.aggregate_rankings({"force": True}, context(), ranking_tables)
    assert second["status"] == "published"
    assert second["generation_id"] != first["generation_id"]
