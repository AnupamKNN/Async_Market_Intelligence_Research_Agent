import pytest

from market_intelligence.services.research_outbox_publisher import (
    calculate_retry_delay,
)


def test_outbox_retry_delay_uses_capped_exponential_backoff():
    assert calculate_retry_delay(1) == 2
    assert calculate_retry_delay(2) == 4
    assert calculate_retry_delay(3) == 8
    assert calculate_retry_delay(4) == 16

    assert calculate_retry_delay(100) == 300


def test_outbox_retry_delay_rejects_invalid_attempt_count():
    with pytest.raises(ValueError):
        calculate_retry_delay(0)
