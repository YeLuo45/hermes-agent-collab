"""
Resource quota management for multi-tenant workspaces.
Provides sliding window rate limiting and fixed-window resource quotas.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

try:
    import redis
    HAS_REDIS = True
except ImportError:
    redis = None
    HAS_REDIS = False


class QuotaResource(str, Enum):
    TASKS = "tasks"
    AGENTS = "agents"
    API_CALLS = "api_calls"
    STORAGE_MB = "storage_mb"
    WEBHOOKS = "webhooks"
    EVENTS = "events"


@dataclass
class QuotaLimit:
    """Defines a single quota limit."""
    resource: str
    max_count: int
    window_seconds: int = 0  # 0 = no window (permanent/all-time)

    def is_rate(self) -> bool:
        return self.window_seconds > 0


@dataclass
class WorkspaceQuota:
    """Quota configuration for a single workspace."""
    workspace_id: str
    limits: dict[str, QuotaLimit] = field(default_factory=dict)
    enabled: bool = True

    def get_limit(self, resource: str) -> QuotaLimit | None:
        return self.limits.get(resource)


@dataclass
class UsageRecord:
    """Current usage for a resource."""
    resource: str
    used: int
    limit: int
    remaining: int
    reset_at: str | None = None
    window_seconds: int = 0


class QuotaManager:
    """
    Multi-tenant quota manager.
    
    Supports two backends:
    - Redis (recommended): sliding window with ZSET
    - In-memory: simple fixed counter (not distributed)
    
    Quota types:
    - Fixed window (max_count, window_seconds=0): total limit e.g. TASKS_MAX=1000
    - Sliding window (max_count, window_seconds>0): rate limit e.g. TASKS_PER_HOUR=100
    """

    # Default limits per workspace
    DEFAULT_LIMITS: list[QuotaLimit] = [
        QuotaLimit("tasks", 1000, 0),            # max 1000 tasks total
        QuotaLimit("tasks", 100, 3600),          # max 100 tasks/hour
        QuotaLimit("agents", 50, 0),              # max 50 agents
        QuotaLimit("api_calls", 60, 60),         # max 60 calls/minute
        QuotaLimit("storage_mb", 500, 0),         # max 500 MB
        QuotaLimit("webhooks", 20, 0),           # max 20 webhooks
    ]

    def __init__(
        self,
        redis_client: Any = None,
        in_memory: bool = True,
    ):
        self._redis = redis_client
        self._in_memory = in_memory
        # In-memory counters: {workspace_id: {resource: count}}
        self._counters: dict[str, dict[str, int]] = {}
        self._timers: dict[str, dict[str, float]] = {}
        self._workspace_quotas: dict[str, WorkspaceQuota] = {}
        self._init_default_quotas()

    def _init_default_quotas(self) -> None:
        """Initialize default quota configs for all known workspaces."""
        # Will be populated when workspaces are first accessed
        pass

    def _redis_key(self, workspace_id: str, resource: str, prefix: str = "quota") -> str:
        return f"tenant:{workspace_id}:{prefix}:{resource}"

    # -------------------------------------------------------------------------
    # Quota check and recording
    # -------------------------------------------------------------------------

    def check_quota(
        self,
        workspace_id: str,
        resource: str,
        cost: int = 1,
        workspace_limits: dict[str, QuotaLimit] | None = None,
    ) -> tuple[bool, UsageRecord]:
        """
        Check if a quota allows the requested cost.
        Returns (allowed, usage_record).
        """
        limits = workspace_limits or self._get_workspace_limits(workspace_id)
        limit_def = limits.get(resource)

        if limit_def is None:
            return True, UsageRecord(resource=resource, used=0, limit=-1, remaining=-1)

        if not limit_def.is_rate():
            # Fixed window: permanent or session-long limit
            current = self._get_fixed_count(workspace_id, resource)
            allowed = current + cost <= limit_def.max_count
            remaining = max(0, limit_def.max_count - current - cost)
            return (
                allowed,
                UsageRecord(
                    resource=resource,
                    used=current + cost,
                    limit=limit_def.max_count,
                    remaining=remaining,
                    window_seconds=0,
                ),
            )
        else:
            # Sliding window: rate limit
            current = self._get_sliding_count(workspace_id, resource, limit_def.window_seconds)
            allowed = current + cost <= limit_def.max_count
            remaining = max(0, limit_def.max_count - current - cost)
            reset_at = datetime.fromtimestamp(
                time.time() + limit_def.window_seconds, tz=timezone.utc
            ).isoformat()
            return (
                allowed,
                UsageRecord(
                    resource=resource,
                    used=current + cost,
                    limit=limit_def.max_count,
                    remaining=remaining,
                    reset_at=reset_at,
                    window_seconds=limit_def.window_seconds,
                ),
            )

    def record_usage(
        self,
        workspace_id: str,
        resource: str,
        cost: int = 1,
    ) -> None:
        """Record resource usage after check_quota passed."""
        limits = self._get_workspace_limits(workspace_id)
        limit_def = limits.get(resource)

        if limit_def is None:
            return

        if not limit_def.is_rate():
            self._incr_fixed(workspace_id, resource, cost)
        else:
            self._add_sliding(workspace_id, resource, cost, limit_def.window_seconds)

    def get_usage(self, workspace_id: str) -> dict[str, UsageRecord]:
        """Get current usage for all resources in a workspace."""
        limits = self._get_workspace_limits(workspace_id)
        result = {}

        for resource, limit_def in limits.items():
            if limit_def.is_rate():
                current = self._get_sliding_count(workspace_id, resource, limit_def.window_seconds)
            else:
                current = self._get_fixed_count(workspace_id, resource)

            result[resource] = UsageRecord(
                resource=resource,
                used=current,
                limit=limit_def.max_count,
                remaining=max(0, limit_def.max_count - current),
                window_seconds=limit_def.window_seconds,
            )

        return result

    def reset_quota(self, workspace_id: str, resource: str | None = None) -> None:
        """Reset quota counters for a workspace (optionally for a specific resource)."""
        if self._redis:
            pattern = f"tenant:{workspace_id}:quota:{resource or '*'}"
            for key in self._redis.scan_iter(match=pattern):
                self._redis.delete(key)
        if resource:
            self._counters.setdefault(workspace_id, {}).pop(resource, None)
            self._timers.setdefault(workspace_id, {}).pop(resource, None)
        else:
            self._counters.pop(workspace_id, None)
            self._timers.pop(workspace_id, None)

    # -------------------------------------------------------------------------
    # Per-workspace quota config
    # -------------------------------------------------------------------------

    def set_workspace_quota(self, workspace_id: str, quota: WorkspaceQuota) -> None:
        self._workspace_quotas[workspace_id] = quota

    def get_workspace_quota(self, workspace_id: str) -> WorkspaceQuota | None:
        return self._workspace_quotas.get(workspace_id)

    def _get_workspace_limits(self, workspace_id: str) -> dict[str, QuotaLimit]:
        if workspace_id in self._workspace_quotas:
            return {l.resource: l for l in self._workspace_quotas[workspace_id].limits}
        # Return default limits
        return {l.resource: l for l in self.DEFAULT_LIMITS}

    # -------------------------------------------------------------------------
    # In-memory counters
    # -------------------------------------------------------------------------

    def _get_fixed_count(self, workspace_id: str, resource: str) -> int:
        if self._in_memory:
            return self._counters.setdefault(workspace_id, {}).get(resource, 0)
        if self._redis:
            key = self._redis_key(workspace_id, resource, "quota_fixed")
            val = self._redis.get(key)
            return int(val) if val else 0
        return 0

    def _incr_fixed(self, workspace_id: str, resource: str, cost: int) -> None:
        if self._in_memory:
            self._counters.setdefault(workspace_id, {})[resource] = (
                self._get_fixed_count(workspace_id, resource) + cost
            )
        if self._redis:
            key = self._redis_key(workspace_id, resource, "quota_fixed")
            self._redis.incrby(key, cost)

    def _get_sliding_count(
        self, workspace_id: str, resource: str, window_seconds: int
    ) -> int:
        now = time.time()
        window_start = now - window_seconds

        if self._in_memory:
            key = (workspace_id, resource)
            entries = self._sliding_entries.setdefault(key, [])
            # Filter old entries
            entries[:] = [(t, c) for t, c in entries if t > window_start]
            return sum(c for _, c in entries)

        if self._redis:
            key = self._redis_key(workspace_id, resource, "quota_sliding")
            self._redis.zremrangebyscore(key, 0, window_start)
            return self._redis.zcard(key)
        return 0

    def _add_sliding(
        self, workspace_id: str, resource: str, cost: int, window_seconds: int
    ) -> None:
        now = time.time()

        if self._in_memory:
            key = (workspace_id, resource)
            entries = self._sliding_entries.setdefault(key, [])
            entries.append((now, cost))
            # Trim old
            window_start = now - window_seconds
            entries[:] = [(t, c) for t, c in entries if t > window_start]
            return

        if self._redis:
            key = self._redis_key(workspace_id, resource, "quota_sliding")
            request_id = f"{now}:{cost}"
            self._redis.zadd(key, {request_id: now})
            self._redis.expire(key, window_seconds * 2)

    # sliding entries for in-memory mode
    _sliding_entries: dict[tuple[str, str], list[tuple[float, int]]] = {}
