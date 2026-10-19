"""Fixed-window rate limiting, keyed per tenant. Redis when configured (shared across API
instances), otherwise an in-process dictionary."""

import threading
import time
from typing import Protocol

import redis


class RateLimiter(Protocol):
    def hit(self, key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
        """Count one request. Returns (allowed, seconds until the window resets)."""
        ...


class RedisRateLimiter:
    def __init__(self, url: str) -> None:
        self._client = redis.Redis.from_url(url, socket_timeout=1, socket_connect_timeout=1)

    def hit(self, key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
        window = int(time.time()) // window_seconds
        redis_key = f"nexusai:rl:{key}:{window}"
        pipe = self._client.pipeline()
        pipe.incr(redis_key)
        pipe.expire(redis_key, window_seconds + 1)
        count, _ = pipe.execute()
        retry_after = window_seconds - int(time.time()) % window_seconds
        return int(count) <= limit, retry_after


class MemoryRateLimiter:
    def __init__(self) -> None:
        self._counts: dict[str, tuple[int, int]] = {}  # key -> (window, count)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
        now = int(time.time())
        window = now // window_seconds
        with self._lock:
            current_window, count = self._counts.get(key, (window, 0))
            count = count + 1 if current_window == window else 1
            self._counts[key] = (window, count)
        return count <= limit, window_seconds - now % window_seconds


def make_rate_limiter(redis_url: str | None) -> RateLimiter:
    return RedisRateLimiter(redis_url) if redis_url else MemoryRateLimiter()
