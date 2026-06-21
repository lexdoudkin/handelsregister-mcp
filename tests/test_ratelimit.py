"""Tests for the sliding-window rate limiter."""

import pytest

from handelsregister_mcp.ratelimit import RateLimiter, RateLimitError


def test_consume_then_block(tmp_path):
    rl = RateLimiter(max_per_hour=3, state_path=tmp_path / "rl.json")
    for _ in range(3):
        rl.check_and_consume()
    with pytest.raises(RateLimitError):
        rl.check_and_consume()


def test_status(tmp_path):
    rl = RateLimiter(max_per_hour=5, state_path=tmp_path / "rl.json")
    rl.check_and_consume()
    rl.check_and_consume()
    s = rl.status()
    assert s["max_per_hour"] == 5
    assert s["used_last_hour"] == 2
    assert s["remaining"] == 3


def test_retry_after_is_positive(tmp_path):
    rl = RateLimiter(max_per_hour=1, state_path=tmp_path / "rl.json")
    rl.check_and_consume()
    with pytest.raises(RateLimitError) as exc:
        rl.check_and_consume()
    assert exc.value.retry_after_seconds > 0
