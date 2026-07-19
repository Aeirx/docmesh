"""TokenBucket with an injected fake clock — exact math, zero sleeping."""

import pytest

from app.core.ratelimit import TokenBucket


def _bucket(capacity: int = 2, rpm: float = 60.0) -> tuple[TokenBucket, list[float]]:
    now = [0.0]
    return TokenBucket(capacity, rpm, clock=lambda: now[0]), now


def test_starts_full_and_exhausts() -> None:
    bucket, _ = _bucket(capacity=2)
    assert bucket.try_acquire() == (True, 0.0)
    assert bucket.try_acquire() == (True, 0.0)
    allowed, retry_after = bucket.try_acquire()
    assert allowed is False
    assert retry_after == pytest.approx(1.0)  # 60/min = 1 token/s, 1 token short


def test_retry_after_shrinks_with_partial_refill() -> None:
    bucket, now = _bucket(capacity=1)
    assert bucket.try_acquire()[0] is True
    now[0] = 0.25
    allowed, retry_after = bucket.try_acquire()
    assert allowed is False
    assert retry_after == pytest.approx(0.75)


def test_refill_restores_and_caps_at_capacity() -> None:
    bucket, now = _bucket(capacity=2)
    assert bucket.try_acquire()[0] and bucket.try_acquire()[0]
    now[0] = 1.0  # exactly one token refilled
    assert bucket.try_acquire()[0] is True
    assert bucket.try_acquire()[0] is False
    now[0] = 1000.0  # long idle: refill must cap at capacity, not accumulate
    assert bucket.try_acquire()[0] is True
    assert bucket.try_acquire()[0] is True
    assert bucket.try_acquire()[0] is False
