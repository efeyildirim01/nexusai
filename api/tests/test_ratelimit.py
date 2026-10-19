import os
import uuid

import pytest

from app.ratelimit import MemoryRateLimiter, RateLimiter, RedisRateLimiter

REDIS_URL = os.environ.get("NEXUS_TEST_REDIS_URL")


def limiters() -> list[RateLimiter]:
    found: list[RateLimiter] = [MemoryRateLimiter()]
    if REDIS_URL:
        found.append(RedisRateLimiter(REDIS_URL))
    return found


@pytest.mark.parametrize("limiter", limiters(), ids=lambda limiter: type(limiter).__name__)
def test_limit_per_key_and_window(limiter: RateLimiter) -> None:
    a, b = f"t-{uuid.uuid4()}", f"t-{uuid.uuid4()}"
    results = [limiter.hit(a, limit=3, window_seconds=60)[0] for _ in range(4)]
    assert results == [True, True, True, False]
    allowed, retry_after = limiter.hit(b, limit=3, window_seconds=60)
    assert allowed
    assert 0 < retry_after <= 60


@pytest.mark.skipif(not REDIS_URL, reason="NEXUS_TEST_REDIS_URL not set (runs in CI)")
def test_redis_limit_is_shared_between_instances() -> None:
    assert REDIS_URL
    key = f"t-{uuid.uuid4()}"
    first, second = RedisRateLimiter(REDIS_URL), RedisRateLimiter(REDIS_URL)
    assert first.hit(key, 2)[0]
    assert second.hit(key, 2)[0]
    assert not first.hit(key, 2)[0]
