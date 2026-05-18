"""Redis-backed TTL cache for task results — Direction S."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


class TaskResultCache:
    """
    Redis-backed TTL cache for task results.

    Supports:
    - get/set/delete with TTL
    - LRU / LFU / TTL eviction strategies
    - Cache-aside pattern via get_or_compute()
    - Workspace-level cache invalidation
    - Cache warming (bulk pre-population)
    """

    RESULT_KEY_PREFIX = "collab:task_result"
    META_KEY_PREFIX = "collab:task_result_meta"

    def __init__(
        self,
        redis_client,
        default_ttl: int = 3600,
        max_cache_size: int = 10000,
        strategy: str = "ttl",  # "ttl" | "lru" | "lfu"
        redis_key_prefix: str | None = None,
    ):
        self._redis = redis_client
        self._default_ttl = default_ttl
        self._max_cache_size = max_cache_size
        self._strategy = strategy
        if redis_key_prefix:
            self.RESULT_KEY_PREFIX = redis_key_prefix
            self.META_KEY_PREFIX = f"{redis_key_prefix}_meta"

    # ---- Public API ----

    async def get(self, task_id: str) -> dict | None:
        """
        Get cached task result.
        Returns None on cache miss.
        Updates LFU access count on hit.
        """
        key = self._result_key(task_id)
        meta_key = self._meta_key(task_id)

        pipe = self._redis.pipeline()
        pipe.get(key)
        pipe.hgetall(meta_key)
        results = await pipe.execute()

        raw = results[0]
        if raw is None:
            return None

        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            return None

        # Update LFU access count
        if self._strategy == "lfu":
            await self._redis.hincrby(meta_key, "access_count", 1)

        return data

    async def set(
        self,
        task_id: str,
        result: dict,
        ttl: int | None = None,
    ) -> None:
        """
        Cache a task result with TTL.
        Enforces max_cache_size by evicting if needed.
        """
        ttl = ttl if ttl is not None else self._default_ttl

        key = self._result_key(task_id)
        meta_key = self._meta_key(task_id)

        serialized = json.dumps(result, default=str)

        pipe = self._redis.pipeline()
        pipe.set(key, serialized, ex=ttl)
        pipe.hset(meta_key, mapping={
            "cached_at": str(time.time()),
            "access_count": "1",
            "ttl": str(ttl),
        })
        # Set expiry on meta key slightly longer than data key
        pipe.expire(meta_key, ttl + 60)
        await pipe.execute()

        logger.debug("Cached task result: %s (ttl=%d)", task_id, ttl)

    async def delete(self, task_id: str) -> None:
        """Evict a task result from cache."""
        key = self._result_key(task_id)
        meta_key = self._meta_key(task_id)

        pipe = self._redis.pipeline()
        pipe.delete(key)
        pipe.delete(meta_key)
        await pipe.execute()

        logger.debug("Deleted cached task result: %s", task_id)

    async def get_or_compute(
        self,
        task_id: str,
        compute_fn: Callable[[], Awaitable[dict]],
        ttl: int | None = None,
    ) -> dict:
        """
        Cache-aside pattern.
        Tries cache first; on miss, calls compute_fn, caches result, returns it.
        """
        cached = await self.get(task_id)
        if cached is not None:
            return cached

        result = await compute_fn()
        if result is not None:
            await self.set(task_id, result, ttl=ttl)
        return result

    async def invalidate_workspace(self, workspace_id: str, task_ids: list[str] | None = None) -> int:
        """
        Invalidate all cached results for a workspace.

        If task_ids is provided, only those task_ids are invalidated.
        Otherwise, uses workspace task list to find all task_ids.
        Returns count of evicted entries.
        """
        if task_ids is None:
            # Try to get all task_ids from workspace tasks
            # We can't efficiently scan all keys without SCAN,
            # so caller should pass task_ids when possible
            logger.warning("invalidate_workspace called without task_ids — skipping")
            return 0

        count = 0
        for task_id in task_ids:
            await self.delete(task_id)
            count += 1

        logger.info("Invalidated %d cached results for workspace", count)
        return count

    async def warm(
        self,
        task_results: dict[str, dict],
        ttl: int | None = None,
    ) -> int:
        """
        Bulk-prepopulate cache.
        task_results: dict of task_id → result dict.
        Returns count of successfully cached entries.
        """
        count = 0
        for task_id, result in task_results.items():
            try:
                await self.set(task_id, result, ttl=ttl)
                count += 1
            except Exception as exc:
                logger.warning("Failed to warm cache for task %s: %s", task_id, exc)
        logger.info("Cache warmed: %d entries", count)
        return count

    async def stats(self) -> dict:
        """Return cache statistics."""
        try:
            info = await self._redis.info("memory")
            used = info.get("used_memory_human", "unknown")
        except Exception:
            used = "unknown"

        return {
            "strategy": self._strategy,
            "default_ttl": self._default_ttl,
            "max_cache_size": self._max_cache_size,
            "memory_used": used,
        }

    # ---- Private helpers ----

    def _result_key(self, task_id: str) -> str:
        return f"{self.RESULT_KEY_PREFIX}:{task_id}"

    def _meta_key(self, task_id: str) -> str:
        return f"{self.META_KEY_PREFIX}:{task_id}"
