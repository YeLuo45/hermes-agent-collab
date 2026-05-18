"""
Rate Limiting for hermes-agent-collab.

Implements Token Bucket + Sliding Window rate limiting with per-key, per-endpoint,
and global limits. Supports both in-memory and Redis-backed storage.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

from .config import CollabConfig, get_config


# ─── Exceptions ────────────────────────────────────────────────────────────────


class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded."""

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        limit: int = 0,
        retry_after: int = 60,
        scope: str = "global",
    ):
        super().__init__(message)
        self.limit = limit
        self.retry_after = retry_after
        self.scope = scope


# ─── Token Bucket ───────────────────────────────────────────────────────────────


@dataclass
class TokenBucket:
    """Token bucket for burst traffic control."""

    capacity: int  # max tokens
    refill_rate: float  # tokens per second
    tokens: float = field(init=False)
    last_refill: float = field(init=False)

    def __post_init__(self):
        self.tokens = float(self.capacity)
        self.last_refill = time.monotonic()

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    def consume(self, tokens: int = 1) -> bool:
        """Try to consume tokens. Returns True if allowed."""
        self._refill()
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    @property
    def available_tokens(self) -> float:
        self._refill()
        return self.tokens


# ─── Sliding Window Counter ─────────────────────────────────────────────────────


@dataclass
class SlidingWindowCounter:
    """Sliding window counter for precise rate limiting."""

    max_requests: int
    window_seconds: int

    _window: dict[str, tuple[int, float]] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def is_allowed(self, key: str) -> tuple[bool, int, int]:
        """
        Check if request is allowed under the rate limit.

        Returns (allowed, remaining, reset_timestamp).
        """
        async with self._lock:
            now = time.time()
            window_start = now - self.window_seconds

            # Clean old entries
            expired = [k for k, (_, ts) in self._window.items() if ts < window_start]
            for k in expired:
                del self._window[k]

            current_count, _ = self._window.get(key, (0, now))

            if current_count >= self.max_requests:
                # Find when this key's window resets
                _, first_ts = self._window.get(key, (0, now))
                reset_ts = int(first_ts + self.window_seconds)
                return False, 0, reset_ts

            # Increment
            self._window[key] = (current_count + 1, now)
            remaining = self.max_requests - current_count - 1
            reset_ts = int(now + self.window_seconds)
            return True, remaining, reset_ts


# ─── Redis-backed Sliding Window ────────────────────────────────────────────────


class RedisSlidingWindowCounter:
    """Redis-backed sliding window counter for distributed rate limiting."""

    def __init__(
        self,
        key_prefix: str,
        max_requests: int,
        window_seconds: int,
        config: CollabConfig | None = None,
    ):
        self.key_prefix = key_prefix
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.config = config or get_config()
        self._client = None

    async def _get_client(self):
        """Lazy Redis client initialization."""
        if self._client is None:
            import redis.asyncio as redis

            self._client = redis.Redis(
                host=self.config.REDIS_HOST,
                port=self.config.REDIS_PORT,
                db=self.config.REDIS_DB,
                password=self.config.REDIS_PASSWORD,
                decode_responses=True,
            )
        return self._client

    async def is_allowed(self, key: str) -> tuple[bool, int, int]:
        """Check if request is allowed using Redis sorted sets."""
        client = await self._get_client()
        redis_key = f"{self.key_prefix}:{key}"
        now = time.time()
        window_start = now - self.window_seconds

        pipe = client.pipeline()
        # Remove expired entries
        pipe.zremrangebyscore(redis_key, 0, window_start)
        # Count current entries
        pipe.zcard(redis_key)
        # Get oldest entry timestamp for reset calculation
        pipe.zrange(redis_key, 0, 0, withscores=True)
        results = await pipe.execute()

        current_count = results[1] or 0
        oldest = results[2]
        oldest_ts = oldest[0][1] if oldest else now

        if current_count >= self.max_requests:
            reset_ts = int(oldest_ts + self.window_seconds)
            return False, 0, reset_ts

        # Add new entry
        entry_key = f"{now}:{key}"
        pipe2 = client.pipeline()
        pipe2.zadd(redis_key, {entry_key: now})
        pipe2.expire(redis_key, self.window_seconds + 1)
        await pipe2.execute()

        remaining = self.max_requests - current_count - 1
        reset_ts = int(now + self.window_seconds)
        return True, remaining, reset_ts

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None


# ─── Rate Limiter ──────────────────────────────────────────────────────────────


class RateLimiter:
    """
    Hierarchical rate limiter with Token Bucket + Sliding Window.

    Limits are enforced in this order:
    1. Global limit (all requests)
    2. Per-API-Key limit
    3. Per-Endpoint limit
    4. Burst capacity (Token Bucket)
    """

    def __init__(self, config: CollabConfig | None = None):
        self.config = config or get_config()
        self._enabled = self.config.METRICS_ENABLED  # Reuse metrics flag initially

        # Global sliding window
        self._global_counter: SlidingWindowCounter | RedisSlidingWindowCounter | None = None
        # Per-key counters (lazy)
        self._key_counters: dict[str, SlidingWindowCounter | RedisSlidingWindowCounter] = {}
        # Per-endpoint counters (lazy)
        self._endpoint_counters: dict[str, SlidingWindowCounter | RedisSlidingWindowCounter] = {}
        # Token buckets per key
        self._buckets: dict[str, TokenBucket] = {}
        # Lock for counter creation
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return getattr(self.config, "RATE_LIMIT_ENABLED", True)

    def _get_storage(self) -> str:
        return getattr(self.config, "RATE_LIMIT_STORAGE", "memory")

    async def _get_global_counter(self) -> SlidingWindowCounter | RedisSlidingWindowCounter:
        if self._global_counter is None:
            storage = self._get_storage()
            max_req = getattr(self.config, "RATE_LIMIT_GLOBAL", 1000)
            window = getattr(self.config, "RATE_LIMIT_WINDOW", 60)

            if storage == "redis":
                self._global_counter = RedisSlidingWindowCounter(
                    "ratelimit:global",
                    max_req,
                    window,
                    self.config,
                )
            else:
                self._global_counter = SlidingWindowCounter(max_req, window)
        return self._global_counter

    async def _get_key_counter(self, api_key: str) -> SlidingWindowCounter | RedisSlidingWindowCounter:
        if api_key not in self._key_counters:
            storage = self._get_storage()
            max_req = getattr(self.config, "RATE_LIMIT_PER_KEY", 100)
            window = getattr(self.config, "RATE_LIMIT_WINDOW", 60)
            # Hash the API key for Redis key safety
            key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16]

            async with self._lock:
                if storage == "redis":
                    self._key_counters[api_key] = RedisSlidingWindowCounter(
                        f"ratelimit:key:{key_hash}",
                        max_req,
                        window,
                        self.config,
                    )
                else:
                    self._key_counters[api_key] = SlidingWindowCounter(max_req, window)
        return self._key_counters[api_key]

    async def _get_endpoint_counter(self, endpoint: str) -> SlidingWindowCounter | RedisSlidingWindowCounter:
        if endpoint not in self._endpoint_counters:
            storage = self._get_storage()
            max_req = getattr(self.config, "RATE_LIMIT_PER_ENDPOINT", 200)
            window = getattr(self.config, "RATE_LIMIT_WINDOW", 60)

            async with self._lock:
                if storage == "redis":
                    self._endpoint_counters[endpoint] = RedisSlidingWindowCounter(
                        f"ratelimit:endpoint:{endpoint}",
                        max_req,
                        window,
                        self.config,
                    )
                else:
                    self._endpoint_counters[endpoint] = SlidingWindowCounter(max_req, window)
        return self._endpoint_counters

    def _get_bucket(self, api_key: str) -> TokenBucket:
        if api_key not in self._buckets:
            burst = getattr(self.config, "RATE_LIMIT_BURST", 50)
            # refill_rate: allow full bucket in window_seconds
            window = getattr(self.config, "RATE_LIMIT_WINDOW", 60)
            refill_rate = burst / window if window > 0 else burst
            self._buckets[api_key] = TokenBucket(capacity=burst, refill_rate=refill_rate)
        return self._buckets[api_key]

    async def check(
        self,
        api_key: str | None,
        endpoint: str,
    ) -> tuple[int, int, int]:
        """
        Check rate limit for a request.

        Returns (limit, remaining, reset_timestamp).
        Raises RateLimitExceeded if limit is exceeded.
        """
        if not self.enabled:
            return (-1, -1, -1)  # Disabled

        # 1. Global limit
        global_counter = await self._get_global_counter()
        allowed, remaining, reset_ts = await global_counter.is_allowed("global")
        if not allowed:
            raise RateLimitExceeded(
                "Global rate limit exceeded",
                limit=getattr(self.config, "RATE_LIMIT_GLOBAL", 1000),
                retry_after=reset_ts - int(time.time()),
                scope="global",
            )

        # 2. Per-key limit
        if api_key:
            key_counter = await self._get_key_counter(api_key)
            allowed, remaining, reset_ts = await key_counter.is_allowed(api_key)
            if not allowed:
                raise RateLimitExceeded(
                    "API key rate limit exceeded",
                    limit=getattr(self.config, "RATE_LIMIT_PER_KEY", 100),
                    retry_after=reset_ts - int(time.time()),
                    scope="per_key",
                )

            # 3. Burst check (Token Bucket)
            bucket = self._get_bucket(api_key)
            if not bucket.consume():
                raise RateLimitExceeded(
                    "Burst limit exceeded",
                    limit=getattr(self.config, "RATE_LIMIT_BURST", 50),
                    retry_after=1,
                    scope="burst",
                )

        # 4. Per-endpoint limit
        endpoint_counter = await self._get_endpoint_counter(endpoint)
        allowed, remaining, reset_ts = await endpoint_counter.is_allowed(endpoint)
        if not allowed:
            raise RateLimitExceeded(
                "Endpoint rate limit exceeded",
                limit=getattr(self.config, "RATE_LIMIT_PER_ENDPOINT", 200),
                retry_after=reset_ts - int(time.time()),
                scope="per_endpoint",
            )

        # Return current limits info
        return (
            getattr(self.config, "RATE_LIMIT_PER_KEY", 100),
            remaining,
            reset_ts,
        )

    async def close(self):
        """Close Redis connections."""
        if isinstance(self._global_counter, RedisSlidingWindowCounter):
            await self._global_counter.close()
        for counter in self._key_counters.values():
            if isinstance(counter, RedisSlidingWindowCounter):
                await counter.close()
        for counter in self._endpoint_counters.values():
            if isinstance(counter, RedisSlidingWindowCounter):
                await counter.close()


# Singleton
_rate_limiter: RateLimiter | None = None


def get_rate_limiter(config: CollabConfig | None = None) -> RateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter(config)
    return _rate_limiter
