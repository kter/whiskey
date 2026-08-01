from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from tests.lambda_module_loader import COMMON_PYTHON


if str(COMMON_PYTHON) not in sys.path:
    sys.path.insert(0, str(COMMON_PYTHON))

from whiskey_common import transact_write_with_retry


class TransactionCanceled(Exception):
    def __init__(self, reasons):
        self.response = {"CancellationReasons": reasons}
        super().__init__("transaction canceled")


class SequencedClient:
    exceptions = SimpleNamespace(TransactionCanceledException=TransactionCanceled)

    def __init__(self, failures):
        self.failures = list(failures)
        self.calls = []
        self.raised = []

    def transact_write_items(self, **kwargs):
        self.calls.append(kwargs)
        if self.failures:
            exc = TransactionCanceled(self.failures.pop(0))
            self.raised.append(exc)
            raise exc


CONFLICT = [{"Code": "TransactionConflict"}, {"Code": "None"}]


def test_transaction_conflict_retries_and_second_attempt_succeeds():
    client = SequencedClient([CONFLICT])
    sleeps = []
    items = [{"Put": {"TableName": "table", "Item": {"pk": "value"}}}]

    transact_write_with_retry(client, items, sleep=sleeps.append, jitter=lambda: 1.0)

    assert len(client.calls) == 2
    assert all(call == {"TransactItems": items} for call in client.calls)
    assert sleeps == [0.05]


def test_conditional_check_failure_is_not_retried():
    client = SequencedClient(
        [[{"Code": "TransactionConflict"}, {"Code": "ConditionalCheckFailed"}]]
    )

    with pytest.raises(TransactionCanceled) as exc:
        transact_write_with_retry(client, [], sleep=lambda _delay: None)

    assert exc.value is client.raised[-1]
    assert len(client.calls) == 1


def test_empty_cancellation_reasons_are_not_retried():
    client = SequencedClient([[]])

    with pytest.raises(TransactionCanceled):
        transact_write_with_retry(client, [], sleep=lambda _delay: None)

    assert len(client.calls) == 1


def test_max_attempts_raises_last_exception_after_exponential_backoff():
    client = SequencedClient([CONFLICT, CONFLICT, CONFLICT, CONFLICT])
    sleeps = []

    with pytest.raises(TransactionCanceled) as exc:
        transact_write_with_retry(
            client,
            [],
            max_attempts=4,
            sleep=sleeps.append,
            jitter=lambda: 1.0,
        )

    assert exc.value is client.raised[-1]
    assert len(client.calls) == 4
    assert sleeps == [0.05, 0.1, 0.2]


def test_remaining_budget_prevents_retry_before_sleep():
    client = SequencedClient([CONFLICT])
    sleeps = []

    with pytest.raises(TransactionCanceled):
        transact_write_with_retry(
            client,
            [],
            remaining_ms=lambda: 249,
            sleep=sleeps.append,
            jitter=lambda: 1.0,
        )

    assert len(client.calls) == 1
    assert sleeps == []


def test_full_jitter_scales_the_backoff_delay():
    client = SequencedClient([CONFLICT])
    sleeps = []

    transact_write_with_retry(client, [], sleep=sleeps.append, jitter=lambda: 0.25)

    assert sleeps == [0.0125]


def test_reasons_without_any_conflict_are_not_retried():
    """An all-None cancellation is not an unambiguous conflict, so it must surface."""
    client = SequencedClient([[{"Code": "None"}, {"Code": "None"}]])
    sleeps = []

    with pytest.raises(TransactionCanceled):
        transact_write_with_retry(client, [], sleep=sleeps.append, jitter=lambda: 1.0)

    assert len(client.calls) == 1
    assert sleeps == []


def test_remaining_budget_above_the_margin_still_retries():
    client = SequencedClient([CONFLICT])
    sleeps = []

    transact_write_with_retry(
        client,
        [],
        remaining_ms=lambda: 251,
        sleep=sleeps.append,
        jitter=lambda: 1.0,
    )

    assert len(client.calls) == 2
    assert sleeps == [0.05]
