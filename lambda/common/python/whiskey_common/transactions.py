"""DynamoDB transaction helpers."""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any


def transact_write_with_retry(
    client: Any,
    transact_items: Sequence[Mapping[str, Any]],
    *,
    max_attempts: int = 4,
    base_delay: float = 0.05,
    max_delay: float = 0.4,
    remaining_ms: Callable[[], int] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    jitter: Callable[[], float] = random.random,
) -> None:
    """Write a transaction, retrying only unambiguous transaction conflicts."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    for attempt in range(1, max_attempts + 1):
        try:
            client.transact_write_items(TransactItems=transact_items)
            return
        except client.exceptions.TransactionCanceledException as exc:
            if attempt == max_attempts:
                raise

            reasons = exc.response.get("CancellationReasons", [])
            if not reasons:
                raise
            if any(not isinstance(reason, Mapping) for reason in reasons):
                raise
            codes = [reason.get("Code") for reason in reasons]
            # Retry only an unambiguous conflict: at least one item must report
            # TransactionConflict, and no item may report anything else. A lone
            # ConditionalCheckFailed means a limit was reached or a condition
            # genuinely failed, and retrying it would erode the cost ceiling.
            if "TransactionConflict" not in codes:
                raise
            if any(code not in {None, "None", "TransactionConflict"} for code in codes):
                raise

            delay = min(max_delay, base_delay * 2 ** (attempt - 1)) * jitter()
            if remaining_ms is not None and delay * 1000 + 200 > remaining_ms():
                raise
            sleep(delay)
