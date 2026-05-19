"""
Rate Limit Manager for hermes-agent-collab.
Provides sliding window rate limiting, quota management, and policy-based access control.
"""

from __future__ import annotations

import json
import time
import threading
import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Any

from collaboration.cache_manager import get_cache_layer


class LimitType(str, Enum):
    SLIDING_WINDOW = "sliding_window"
    FIXED_WINDOW = "fixed_window"
    TOKEN_BUCKET = "token_bucket"


class TargetType(str, Enum):
    GLOBAL = "global"
    WORKSPACE = "workspace"
    API_KEY = "api_key"
    AGENT = "agent"


@dataclass
class RateLimitPolicy:
    policy_id: str
    name: str
    description: str = ""
    dimensions: str = "global"  # global | workspace | api_key | agent
    limit_type: str = "sliding_window"
    requests_per_window: int = 100
    window_seconds: int = 60
    burst_limit: int = 0
    scopes: list[str] = field(default_factory=lambda: ["*"])
    enabled: bool = True
    priority: int = 0  # Higher = checked first
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> RateLimitPolicy:
        # Filter unknown fields
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


@dataclass
class QuotaUsage:
    workspace_id: Optional[str] = None
    api_key_id: Optional[str] = None
    agent_id: Optional[str] = None
    policy_id: str = ""
    used_count: int = 0
    window_start: float = 0.0
    last_request_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "workspace_id": self.workspace_id,
            "api_key_id": self.api_key_id,
            "agent_id": self.agent_id,
            "policy_id": self.policy_id,
            "used_count": self.used_count,
            "window_start": self.window_start,
            "last_request_at": self.last_request_at,
        }


@dataclass
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    reset_at: float
    retry_after_seconds: int = 0
    policy_id: str = ""
    scope: str = ""

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "limit": self.limit,
            "remaining": max(0, self.remaining),
            "reset_at": self.reset_at,
            "retry_after_seconds": self.retry_after_seconds,
            "policy_id": self.policy_id,
            "scope": self.scope,
        }


class RateLimitManager:
    """
    Sliding window rate limiter using Redis sorted sets.
    Supports multi-dimensional policies (workspace, api_key, agent, global).
    """

    def __init__(self):
        self._policies: dict[str, RateLimitPolicy] = {}
        self._policy_assignments: dict[str, list[str]] = {}  # target_key -> [policy_ids]
        self._policies_lock = threading.RLock()
        self._cache = get_cache_layer()
        self._policies_ttl = 60.0  # Refresh policies every 60s
        self._last_refresh = 0.0
        self._default_policies: list[RateLimitPolicy] = []

    # ─── Policy Management ────────────────────────────────────────────────────

    def _now(self) -> float:
        return time.time()

    def _default_policy_id(self, target_type: str, target_id: str, scope: str) -> str:
        raw = f"{target_type}:{target_id}:{scope}"
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    def _target_key(self, target_type: str, target_id: str) -> str:
        return f"{target_type}:{target_id}"

    def _scope_key(self, target_type: str, target_id: str, policy_id: str, scope: str) -> str:
        return f"rl:{target_type}:{target_id}:{policy_id}:{scope}"

    def _ensure_default_policies(self):
        """Create default policies if none exist."""
        if self._default_policies:
            return

        self._default_policies = [
            RateLimitPolicy(
                policy_id="default_global",
                name="Default Global",
                description="Default 100 req/min global limit",
                dimensions="global",
                requests_per_window=100,
                window_seconds=60,
                scopes=["*"],
                priority=0,
            ),
            RateLimitPolicy(
                policy_id="default_workspace",
                name="Default Workspace",
                description="Default 60 req/min per workspace",
                dimensions="workspace",
                requests_per_window=60,
                window_seconds=60,
                scopes=["*"],
                priority=0,
            ),
            RateLimitPolicy(
                policy_id="default_api_key",
                name="Default API Key",
                description="Default 120 req/min per API key",
                dimensions="api_key",
                requests_per_window=120,
                window_seconds=60,
                scopes=["*"],
                priority=0,
            ),
        ]

    def _refresh_policies_if_needed(self):
        """Reload policies from cache if TTL expired."""
        if self._now() - self._last_refresh < self._policies_ttl:
            return
        self._load_policies()

    def _load_policies(self):
        """Load all policies from cache."""
        try:
            raw = self._cache.get("ratelimit:policies")
            if raw:
                data = json.loads(raw)
                with self._policies_lock:
                    for p_data in data.get("policies", []):
                        p = RateLimitPolicy.from_dict(p_data)
                        self._policies[p.policy_id] = p
                    self._policy_assignments = data.get("assignments", {})
            else:
                self._ensure_default_policies()
                self._save_policies()
        except Exception:
            self._ensure_default_policies()
        self._last_refresh = self._now()

    def _save_policies(self):
        """Persist policies to cache."""
        with self._policies_lock:
            data = {
                "policies": [p.to_dict() for p in self._policies.values()],
                "assignments": self._policy_assignments,
            }
            self._cache.set("ratelimit:policies", json.dumps(data), ttl=300)

    # ─── Public API ──────────────────────────────────────────────────────────

    def create_policy(self, policy: RateLimitPolicy) -> RateLimitPolicy:
        """Create a new rate limit policy."""
        self._refresh_policies_if_needed()
        policy.policy_id = policy.policy_id or hashlib.md5(
            f"{policy.name}{self._now()}".encode()
        ).hexdigest()[:12]
        policy.created_at = datetime.now(timezone.utc).isoformat()
        policy.updated_at = policy.created_at

        with self._policies_lock:
            self._policies[policy.policy_id] = policy

        self._save_policies()
        return policy

    def get_policy(self, policy_id: str) -> Optional[RateLimitPolicy]:
        """Get a policy by ID."""
        self._refresh_policies_if_needed()
        return self._policies.get(policy_id)

    def list_policies(self) -> list[RateLimitPolicy]:
        """List all policies."""
        self._refresh_policies_if_needed()
        with self._policies_lock:
            return list(self._policies.values())

    def update_policy(self, policy_id: str, updates: dict) -> Optional[RateLimitPolicy]:
        """Update an existing policy."""
        self._refresh_policies_if_needed()
        with self._policies_lock:
            if policy_id not in self._policies:
                return None
            policy = self._policies[policy_id]
            for key, value in updates.items():
                if hasattr(policy, key) and key not in ("policy_id", "created_at"):
                    setattr(policy, key, value)
            policy.updated_at = datetime.now(timezone.utc).isoformat()
            self._policies[policy_id] = policy
        self._save_policies()
        return policy

    def delete_policy(self, policy_id: str) -> bool:
        """Delete a policy."""
        self._refresh_policies_if_needed()
        with self._policies_lock:
            if policy_id in self._policies:
                del self._policies[policy_id]
                # Remove all assignments
                for target_key in list(self._policy_assignments.keys()):
                    if policy_id in self._policy_assignments[target_key]:
                        self._policy_assignments[target_key].remove(policy_id)
                self._save_policies()
                return True
        return False

    def assign_policy(
        self, target_type: str, target_id: str, policy_id: str
    ) -> bool:
        """Assign a policy to a workspace/api_key/agent."""
        self._refresh_policies_if_needed()
        if policy_id not in self._policies:
            return False

        target_key = self._target_key(target_type, target_id)
        with self._policies_lock:
            if target_key not in self._policy_assignments:
                self._policy_assignments[target_key] = []
            if policy_id not in self._policy_assignments[target_key]:
                self._policy_assignments[target_key].append(policy_id)
        self._save_policies()
        return True

    def unassign_policy(
        self, target_type: str, target_id: str, policy_id: str
    ) -> bool:
        """Remove a policy assignment."""
        self._refresh_policies_if_needed()
        target_key = self._target_key(target_type, target_id)
        with self._policies_lock:
            if target_key in self._policy_assignments:
                if policy_id in self._policy_assignments[target_key]:
                    self._policy_assignments[target_key].remove(policy_id)
                    self._save_policies()
                    return True
        return False

    def get_assigned_policies(self, target_type: str, target_id: str) -> list[RateLimitPolicy]:
        """Get all policies assigned to a target."""
        self._refresh_policies_if_needed()
        target_key = self._target_key(target_type, target_id)
        with self._policies_lock:
            policy_ids = self._policy_assignments.get(target_key, [])
            result = []
            for pid in policy_ids:
                if pid in self._policies:
                    result.append(self._policies[pid])
        return result

    # ─── Rate Limit Checking ──────────────────────────────────────────────────

    def _scope_matches(self, policy_scope: str, request_scope: str) -> bool:
        """Check if a policy scope matches the request scope."""
        if policy_scope == "*":
            return True
        if policy_scope == request_scope:
            return True
        # Wildcard suffix matching
        if policy_scope.endswith("/*"):
            prefix = policy_scope[:-1]
            if request_scope.startswith(prefix):
                return True
        return False

    def _get_matching_policies(
        self,
        target_type: str,
        target_id: str,
        scope: str,
    ) -> list[tuple[RateLimitPolicy, str]]:
        """
        Get all policies that match the given target and scope.
        Returns list of (policy, matched_scope) sorted by priority (highest first).
        """
        self._refresh_policies_if_needed()

        # Build list of candidate policies: global + specific
        candidates: list[RateLimitPolicy] = []

        # Add global policies
        with self._policies_lock:
            for p in self._policies.values():
                if p.enabled and p.dimensions == "global":
                    candidates.append(p)

        # Add target-specific policies
        target_key = self._target_key(target_type, target_id)
        with self._policies_lock:
            policy_ids = self._policy_assignments.get(target_key, [])
            for pid in policy_ids:
                if pid in self._policies:
                    p = self._policies[pid]
                    if p.enabled and p.dimensions == target_type:
                        candidates.append(p)

        # Sort by priority (descending)
        candidates.sort(key=lambda p: p.priority, reverse=True)

        # Filter by scope match
        matched = []
        for p in candidates:
            for ps in p.scopes:
                if self._scope_matches(ps, scope):
                    matched.append((p, ps))
                    break

        return matched

    def check_and_consume(
        self,
        target_type: str,
        target_id: str,
        scope: str,
    ) -> RateLimitDecision:
        """
        Check if request is allowed under rate limits and consume a slot if so.
        Uses sliding window algorithm via Redis sorted sets.
        """
        matched_policies = self._get_matching_policies(target_type, target_id, scope)

        if not matched_policies:
            # No policy matches — allow by default
            return RateLimitDecision(
                allowed=True,
                limit=0,
                remaining=0,
                reset_at=self._now() + 60,
                policy_id="",
                scope=scope,
            )

        now = self._now()
        worst_decision: Optional[RateLimitDecision] = None

        for policy, _ in matched_policies:
            sk = self._scope_key(target_type, target_id, policy.policy_id, scope)

            if policy.limit_type == "sliding_window":
                decision = self._check_sliding_window(sk, policy, now)
            elif policy.limit_type == "fixed_window":
                decision = self._check_fixed_window(sk, policy, now)
            elif policy.limit_type == "token_bucket":
                decision = self._check_token_bucket(sk, policy, now)
            else:
                decision = RateLimitDecision(
                    allowed=True,
                    limit=policy.requests_per_window,
                    remaining=policy.requests_per_window,
                    reset_at=now + policy.window_seconds,
                    policy_id=policy.policy_id,
                    scope=scope,
                )

            if not decision.allowed:
                return decision  # Fast fail

            # Track worst (most restrictive) decision
            if worst_decision is None or decision.remaining < worst_decision.remaining:
                worst_decision = decision

        return worst_decision or RateLimitDecision(
            allowed=True,
            limit=0,
            remaining=0,
            reset_at=now + 60,
            scope=scope,
        )

    def _check_sliding_window(
        self, scope_key: str, policy: RateLimitPolicy, now: float
    ) -> RateLimitDecision:
        """Sliding window counter using Redis sorted set."""
        try:
            cache = self._cache
            ws_key = f"{scope_key}:window"
            window_start = now - policy.window_seconds

            # Remove old entries
            cache.zremrangebyscore(ws_key, 0, window_start)

            # Count current entries
            current_count = cache.zcard(ws_key)

            if current_count >= policy.requests_per_window:
                # Find oldest entry to calculate reset time
                oldest = cache.zrange(ws_key, 0, 0, withscores=True)
                if oldest:
                    reset_at = oldest[0][1] + policy.window_seconds
                else:
                    reset_at = now + policy.window_seconds

                retry_after = max(1, int(reset_at - now))
                return RateLimitDecision(
                    allowed=False,
                    limit=policy.requests_per_window,
                    remaining=0,
                    reset_at=reset_at,
                    retry_after_seconds=retry_after,
                    policy_id=policy.policy_id,
                    scope=scope_key,
                )

            # Add current request
            cache.zadd(ws_key, {str(now): now})
            cache.expire(ws_key, policy.window_seconds + 1)

            remaining = policy.requests_per_window - current_count - 1
            reset_at = now + policy.window_seconds

            return RateLimitDecision(
                allowed=True,
                limit=policy.requests_per_window,
                remaining=remaining,
                reset_at=reset_at,
                policy_id=policy.policy_id,
                scope=scope_key,
            )

        except Exception:
            # On error, allow request (fail open)
            return RateLimitDecision(
                allowed=True,
                limit=policy.requests_per_window,
                remaining=policy.requests_per_window,
                reset_at=now + policy.window_seconds,
                policy_id=policy.policy_id,
                scope=scope_key,
            )

    def _check_fixed_window(
        self, scope_key: str, policy: RateLimitPolicy, now: float
    ) -> RateLimitDecision:
        """Fixed window counter using Redis string + expiry."""
        try:
            cache = self._cache
            window_num = int(now / policy.window_seconds)
            window_key = f"{scope_key}:fw:{window_num}"

            current = cache.get(window_key) or "0"
            count = int(current)

            if count >= policy.requests_per_window:
                next_window = (window_num + 1) * policy.window_seconds
                retry_after = max(1, int(next_window - now))
                return RateLimitDecision(
                    allowed=False,
                    limit=policy.requests_per_window,
                    remaining=0,
                    reset_at=next_window,
                    retry_after_seconds=retry_after,
                    policy_id=policy.policy_id,
                    scope=scope_key,
                )

            cache.set(window_key, str(count + 1), ttl=policy.window_seconds * 2 + 1)

            return RateLimitDecision(
                allowed=True,
                limit=policy.requests_per_window,
                remaining=policy.requests_per_window - count - 1,
                reset_at=(window_num + 1) * policy.window_seconds,
                policy_id=policy.policy_id,
                scope=scope_key,
            )

        except Exception:
            return RateLimitDecision(
                allowed=True,
                limit=policy.requests_per_window,
                remaining=policy.requests_per_window,
                reset_at=now + policy.window_seconds,
                policy_id=policy.policy_id,
                scope=scope_key,
            )

    def _check_token_bucket(
        self, scope_key: str, policy: RateLimitPolicy, now: float
    ) -> RateLimitDecision:
        """
        Token bucket algorithm.
        Tokens are refilled at (requests_per_window / window_seconds) per second.
        """
        try:
            cache = self._cache
            bucket_key = f"{scope_key}:tb"

            raw = cache.get(bucket_key)
            if raw:
                bucket_data = json.loads(raw)
                tokens = bucket_data["tokens"]
                last_refill = bucket_data["last_refill"]
            else:
                tokens = float(policy.requests_per_window)
                last_refill = now

            # Refill tokens
            elapsed = now - last_refill
            refill_rate = policy.requests_per_window / policy.window_seconds
            tokens = min(policy.requests_per_window, tokens + elapsed * refill_rate)
            last_refill = now

            if tokens < 1:
                # Calculate time until next token
                retry_after = int((1 - tokens) / refill_rate) + 1
                bucket_data = {
                    "tokens": tokens,
                    "last_refill": last_refill,
                }
                cache.set(bucket_key, json.dumps(bucket_data), ttl=policy.window_seconds * 2)
                reset_at = now + retry_after
                return RateLimitDecision(
                    allowed=False,
                    limit=policy.requests_per_window,
                    remaining=0,
                    reset_at=reset_at,
                    retry_after_seconds=retry_after,
                    policy_id=policy.policy_id,
                    scope=scope_key,
                )

            # Consume one token
            tokens -= 1
            bucket_data = {
                "tokens": tokens,
                "last_refill": last_refill,
            }
            cache.set(bucket_key, json.dumps(bucket_data), ttl=policy.window_seconds * 2)

            reset_at = now + policy.window_seconds
            return RateLimitDecision(
                allowed=True,
                limit=policy.requests_per_window,
                remaining=int(tokens),
                reset_at=reset_at,
                policy_id=policy.policy_id,
                scope=scope_key,
            )

        except Exception:
            return RateLimitDecision(
                allowed=True,
                limit=policy.requests_per_window,
                remaining=policy.requests_per_window,
                reset_at=now + policy.window_seconds,
                policy_id=policy.policy_id,
                scope=scope_key,
            )

    def get_usage(
        self,
        target_type: str,
        target_id: str,
        policy_id: Optional[str] = None,
    ) -> list[dict]:
        """Get current usage for a target's assigned policies."""
        self._refresh_policies_if_needed()
        target_key = self._target_key(target_type, target_id)
        result = []

        with self._policies_lock:
            policy_ids = self._policy_assignments.get(target_key, [])

        for pid in policy_ids:
            policy = self._policies.get(pid)
            if not policy or (policy_id and policy.policy_id != policy_id):
                continue

            for scope in policy.scopes:
                sk = self._scope_key(target_type, target_id, pid, scope)
                now = self._now()

                if policy.limit_type == "sliding_window":
                    ws_key = f"{sk}:window"
                    try:
                        current_count = self._cache.zcard(ws_key)
                        window_start = now - policy.window_seconds
                        self._cache.zremrangebyscore(ws_key, 0, window_start)
                        current_count = self._cache.zcard(ws_key)
                    except Exception:
                        current_count = 0
                elif policy.limit_type == "fixed_window":
                    window_num = int(now / policy.window_seconds)
                    window_key = f"{sk}:fw:{window_num}"
                    try:
                        current = self._cache.get(window_key) or "0"
                        current_count = int(current)
                    except Exception:
                        current_count = 0
                elif policy.limit_type == "token_bucket":
                    bucket_key = f"{sk}:tb"
                    try:
                        raw = self._cache.get(bucket_key)
                        if raw:
                            current_count = policy.requests_per_window - int(
                                json.loads(raw).get("tokens", policy.requests_per_window)
                            )
                        else:
                            current_count = 0
                    except Exception:
                        current_count = 0
                else:
                    current_count = 0

                result.append({
                    "policy_id": pid,
                    "policy_name": policy.name,
                    "scope": scope,
                    "limit": policy.requests_per_window,
                    "used": current_count,
                    "remaining": max(0, policy.requests_per_window - current_count),
                    "limit_type": policy.limit_type,
                    "window_seconds": policy.window_seconds,
                    "target_type": target_type,
                    "target_id": target_id,
                })

        return result

    def get_stats(self) -> dict:
        """Get global rate limit statistics."""
        self._refresh_policies_if_needed()
        with self._policies_lock:
            all_policies = list(self._policies.values())
            enabled = [p for p in all_policies if p.enabled]
            disabled = [p for p in all_policies if not p.enabled]

            total_assignments = sum(
                len(v) for v in self._policy_assignments.values()
            )

            return {
                "total_policies": len(all_policies),
                "enabled_policies": len(enabled),
                "disabled_policies": len(disabled),
                "total_assignments": total_assignments,
                "dimensions": {
                    dim: len([p for p in all_policies if p.dimensions == dim])
                    for dim in ("global", "workspace", "api_key", "agent")
                },
            }


# ─── Global Singleton ────────────────────────────────────────────────────────

_manager: Optional[RateLimitManager] = None
_manager_lock = threading.Lock()


def get_rate_limit_manager() -> RateLimitManager:
    """Get or create the global RateLimitManager singleton."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = RateLimitManager()
    return _manager
