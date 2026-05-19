"""
Redis Cache Layer for hermes-agent-collab.
Provides distributed caching, session sharing, rate limiting, and distributed locking.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any, Optional

try:
    import redis
except ImportError:
    redis = None


# ---------------------------------------------------------------------------
# In-Memory Fallback Cache
# ---------------------------------------------------------------------------

class DictCache:
    """Thread-safe in-memory cache fallback when Redis is unavailable."""

    def __init__(self):
        self._data: dict[str, str] = {}
        self._expiry: dict[str, float] = {}
        self._lock = threading.RLock()

    def get(self, key: str) -> str | None:
        with self._lock:
            if key in self._data:
                if key in self._expiry and time.time() > self._expiry[key]:
                    del self._data[key]
                    del self._expiry[key]
                    return None
                return self._data[key]
        return None

    def set(self, key: str, value: str, ttl: int | None = None) -> bool:
        with self._lock:
            self._data[key] = value
            if ttl is not None:
                self._expiry[key] = time.time() + ttl
            elif key in self._expiry:
                del self._expiry[key]
        return True

    def delete(self, key: str) -> bool:
        with self._lock:
            if key in self._data:
                del self._data[key]
            if key in self._expiry:
                del self._expiry[key]
        return True

    def exists(self, key: str) -> bool:
        with self._lock:
            return key in self._data

    def expire(self, key: str, ttl: int) -> bool:
        with self._lock:
            if key in self._data:
                self._expiry[key] = time.time() + ttl
                return True
        return False

    def ttl(self, key: str) -> int:
        with self._lock:
            if key in self._expiry:
                remaining = self._expiry[key] - time.time()
                return int(remaining) if remaining > 0 else -2
        return -1

    def incr(self, key: str, amount: int = 1) -> int:
        with self._lock:
            current = self._data.get(key, "0")
            try:
                new_val = int(current) + amount
            except ValueError:
                new_val = amount
            self._data[key] = str(new_val)
            return new_val

    def decr(self, key: str, amount: int = 1) -> int:
        return self.incr(key, -amount)

    def hget(self, name: str, key: str) -> str | None:
        with self._lock:
            full_key = f"{name}:{key}"
            return self.get(full_key)

    def hset(self, name: str, key: str, value: str) -> int:
        with self._lock:
            full_key = f"{name}:{key}"
            self.set(full_key, value)
            return 1

    def hgetall(self, name: str) -> dict[str, str]:
        with self._lock:
            prefix = f"{name}:"
            result = {}
            for k, v in self._data.items():
                if k.startswith(prefix):
                    result[k[len(prefix):]] = v
            return result

    def hdel(self, name: str, *keys: str) -> int:
        count = 0
        with self._lock:
            for k in keys:
                full_key = f"{name}:{k}"
                if full_key in self._data:
                    del self._data[full_key]
                    count += 1
        return count

    def lpush(self, name: str, *values: str) -> int:
        with self._lock:
            full_key = f"list:{name}"
            existing = self._data.get(full_key, "")
            items = existing.split("|") if existing else []
            for v in reversed(values):
                items.insert(0, v)
            self._data[full_key] = "|".join(items)
            return len(items)

    def rpush(self, name: str, *values: str) -> int:
        with self._lock:
            full_key = f"list:{name}"
            existing = self._data.get(full_key, "")
            items = existing.split("|") if existing else []
            items.extend(values)
            self._data[full_key] = "|".join(items)
            return len(items)

    def lrange(self, name: str, start: int, end: int) -> list[str]:
        with self._lock:
            full_key = f"list:{name}"
            existing = self._data.get(full_key, "")
            items = existing.split("|") if existing else []
            return items[start:end + 1] if end >= 0 else items[start:]

    def sadd(self, name: str, *values: str) -> int:
        with self._lock:
            full_key = f"set:{name}"
            existing = self._data.get(full_key, "")
            members = set(existing.split("|")) if existing else set()
            original_len = len(members)
            members.update(values)
            self._data[full_key] = "|".join(sorted(members))
            return len(members) - original_len

    def smembers(self, name: str) -> set[str]:
        with self._lock:
            full_key = f"set:{name}"
            existing = self._data.get(full_key, "")
            return set(existing.split("|")) if existing else set()

    def zadd(self, name: str, mapping: dict[str, float]) -> int:
        with self._lock:
            full_key = f"zset:{name}"
            existing = self._data.get(full_key, "")
            items = {}
            if existing:
                for pair in existing.split("|"):
                    if ":" in pair:
                        k, s = pair.rsplit(":", 1)
                        try:
                            items[k] = float(s)
                        except ValueError:
                            pass
            original_len = len(items)
            items.update(mapping)
            encoded = "|".join(f"{k}:{v}" for k, v in items.items())
            self._data[full_key] = encoded
            return len(items) - original_len

    def zrangebyscore(self, name: str, min_val: float, max_val: float) -> list[str]:
        with self._lock:
            full_key = f"zset:{name}"
            existing = self._data.get(full_key, "")
            if not existing:
                return []
            result = []
            for pair in existing.split("|"):
                if ":" in pair:
                    k, s = pair.rsplit(":", 1)
                    try:
                        score = float(s)
                        if min_val <= score <= max_val:
                            result.append(k)
                    except ValueError:
                        pass
            return result

    def ping(self) -> bool:
        return True

    def keys(self, pattern: str = "*") -> list[str]:
        with self._lock:
            if pattern == "*":
                return list(self._data.keys())
            # Simple glob matching
            import fnmatch
            return fnmatch.filter(self._data.keys(), pattern)

    def clear(self):
        with self._lock:
            self._data.clear()
            self._expiry.clear()


# ---------------------------------------------------------------------------
# Redis Cache
# ---------------------------------------------------------------------------

class RedisCache:
    """
    Redis-backed distributed cache.
    Falls back to DictCache when Redis is unavailable.
    """

    KEY_PREFIX = "hermes"

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self._redis_url = redis_url
        self._redis: Any = None
        self._lock = threading.Lock()
        self._fallback = DictCache()
        self._connected = False
        self._connect_lock = threading.Lock()

    def _prefix_key(self, key: str) -> str:
        return f"{self.KEY_PREFIX}:{key}"

    def connect(self) -> bool:
        """Establish Redis connection."""
        if redis is None:
            return False
        with self._connect_lock:
            if self._connected:
                return True
            try:
                self._redis = redis.from_url(
                    self._redis_url,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                )
                self._redis.ping()
                self._connected = True
                return True
            except Exception:
                self._redis = None
                self._connected = False
                return False

    def disconnect(self):
        """Close Redis connection."""
        with self._connect_lock:
            if self._redis:
                try:
                    self._redis.close()
                except Exception:
                    pass
                self._redis = None
                self._connected = False

    def _use_fallback(self) -> bool:
        """Return True if Redis is unavailable."""
        if not self._connected and redis is not None:
            self.connect()
        return not self._connected or self._redis is None

    def get(self, key: str) -> str | None:
        with self._lock:
            if self._use_fallback():
                return self._fallback.get(key)
            try:
                return self._redis.get(self._prefix_key(key))
            except Exception:
                return self._fallback.get(key)

    def set(self, key: str, value: str, ttl: int | None = None) -> bool:
        with self._lock:
            if self._use_fallback():
                return self._fallback.set(key, value, ttl)
            try:
                pkey = self._prefix_key(key)
                if ttl:
                    self._redis.setex(pkey, ttl, value)
                else:
                    self._redis.set(pkey, value)
                return True
            except Exception:
                return self._fallback.set(key, value, ttl)

    def delete(self, key: str) -> bool:
        with self._lock:
            if self._use_fallback():
                return self._fallback.delete(key)
            try:
                return bool(self._redis.delete(self._prefix_key(key)))
            except Exception:
                return self._fallback.delete(key)

    def exists(self, key: str) -> bool:
        with self._lock:
            if self._use_fallback():
                return self._fallback.exists(key)
            try:
                return bool(self._redis.exists(self._prefix_key(key)))
            except Exception:
                return self._fallback.exists(key)

    def expire(self, key: str, ttl: int) -> bool:
        with self._lock:
            if self._use_fallback():
                return self._fallback.expire(key, ttl)
            try:
                return bool(self._redis.expire(self._prefix_key(key), ttl))
            except Exception:
                return self._fallback.expire(key, ttl)

    def ttl(self, key: str) -> int:
        with self._lock:
            if self._use_fallback():
                return self._fallback.ttl(key)
            try:
                return int(self._redis.ttl(self._prefix_key(key)))
            except Exception:
                return self._fallback.ttl(key)

    def incr(self, key: str, amount: int = 1) -> int:
        with self._lock:
            if self._use_fallback():
                return self._fallback.incr(key, amount)
            try:
                return int(self._redis.incrby(self._prefix_key(key), amount))
            except Exception:
                return self._fallback.incr(key, amount)

    def decr(self, key: str, amount: int = 1) -> int:
        return self.incr(key, -amount)

    def hget(self, name: str, key: str) -> str | None:
        with self._lock:
            if self._use_fallback():
                return self._fallback.hget(name, key)
            try:
                return self._redis.hget(self._prefix_key(name), key)
            except Exception:
                return self._fallback.hget(name, key)

    def hset(self, name: str, key: str, value: str) -> int:
        with self._lock:
            if self._use_fallback():
                return self._fallback.hset(name, key, value)
            try:
                return int(self._redis.hset(self._prefix_key(name), key, value))
            except Exception:
                return self._fallback.hset(name, key, value)

    def hgetall(self, name: str) -> dict[str, str]:
        with self._lock:
            if self._use_fallback():
                return self._fallback.hgetall(name)
            try:
                return dict(self._redis.hgetall(self._prefix_key(name)))
            except Exception:
                return self._fallback.hgetall(name)

    def hdel(self, name: str, *keys: str) -> int:
        with self._lock:
            if self._use_fallback():
                return self._fallback.hdel(name, *keys)
            try:
                return int(self._redis.hdel(self._prefix_key(name), *keys))
            except Exception:
                return self._fallback.hdel(name, *keys)

    def lpush(self, name: str, *values: str) -> int:
        with self._lock:
            if self._use_fallback():
                return self._fallback.lpush(name, *values)
            try:
                return int(self._redis.lpush(self._prefix_key(name), *values))
            except Exception:
                return self._fallback.lpush(name, *values)

    def rpush(self, name: str, *values: str) -> int:
        with self._lock:
            if self._use_fallback():
                return self._fallback.rpush(name, *values)
            try:
                return int(self._redis.rpush(self._prefix_key(name), *values))
            except Exception:
                return self._fallback.rpush(name, *values)

    def lrange(self, name: str, start: int, end: int) -> list[str]:
        with self._lock:
            if self._use_fallback():
                return self._fallback.lrange(name, start, end)
            try:
                return self._redis.lrange(self._prefix_key(name), start, end)
            except Exception:
                return self._fallback.lrange(name, start, end)

    def sadd(self, name: str, *values: str) -> int:
        with self._lock:
            if self._use_fallback():
                return self._fallback.sadd(name, *values)
            try:
                return int(self._redis.sadd(self._prefix_key(name), *values))
            except Exception:
                return self._fallback.sadd(name, *values)

    def smembers(self, name: str) -> set[str]:
        with self._lock:
            if self._use_fallback():
                return self._fallback.smembers(name)
            try:
                return set(self._redis.smembers(self._prefix_key(name)))
            except Exception:
                return self._fallback.smembers(name)

    def zadd(self, name: str, mapping: dict[str, float]) -> int:
        with self._lock:
            if self._use_fallback():
                return self._fallback.zadd(name, mapping)
            try:
                return int(self._redis.zadd(self._prefix_key(name), mapping))
            except Exception:
                return self._fallback.zadd(name, mapping)

    def zrangebyscore(self, name: str, min_val: float, max_val: float) -> list[str]:
        with self._lock:
            if self._use_fallback():
                return self._fallback.zrangebyscore(name, min_val, max_val)
            try:
                return self._redis.zrangebyscore(
                    self._prefix_key(name), min_val, max_val
                )
            except Exception:
                return self._fallback.zrangebyscore(name, min_val, max_val)

    def ping(self) -> bool:
        with self._lock:
            if self._use_fallback():
                return self._fallback.ping()
            try:
                return bool(self._redis.ping())
            except Exception:
                return False

    def keys(self, pattern: str = "*") -> list[str]:
        """List keys matching pattern. Uses fallback for simplicity."""
        with self._lock:
            if self._use_fallback():
                return self._fallback.keys(pattern)
            try:
                full_pattern = self._prefix_key(pattern)
                keys = self._redis.keys(full_pattern)
                prefix = self._prefix_key("")
                return [k[len(prefix):] for k in keys]
            except Exception:
                return self._fallback.keys(pattern)

    def clear(self):
        """Clear all keys with prefix."""
        with self._lock:
            if self._use_fallback():
                self._fallback.clear()
                return
            try:
                keys = self.keys()
                if keys:
                    self._redis.delete(*[self._prefix_key(k) for k in keys])
            except Exception:
                self._fallback.clear()

    def get_stats(self) -> dict:
        """Get cache statistics."""
        with self._lock:
            return {
                "backend": "redis" if self._connected and self._redis else "dict",
                "connected": self._connected,
                "redis_url": self._redis_url,
            }


# ---------------------------------------------------------------------------
# Cache Layer (High-level API)
# ---------------------------------------------------------------------------

class CacheLayer:
    """
    High-level caching facade.
    Wraps RedisCache with domain-specific methods.
    """

    def __init__(self, cache: RedisCache):
        self._cache = cache

    # --- Agent caching ---
    def get_agent(self, agent_id: str) -> dict | None:
        val = self._cache.get(f"agent:{agent_id}")
        if val:
            try:
                return json.loads(val)
            except json.JSONDecodeError:
                return None
        return None

    def set_agent(self, agent_id: str, data: dict, ttl: int = 300) -> bool:
        return self._cache.set(f"agent:{agent_id}", json.dumps(data), ttl)

    def invalidate_agent(self, agent_id: str) -> bool:
        return self._cache.delete(f"agent:{agent_id}")

    # --- Task caching ---
    def get_task(self, task_id: str) -> dict | None:
        val = self._cache.get(f"task:{task_id}")
        if val:
            try:
                return json.loads(val)
            except json.JSONDecodeError:
                return None
        return None

    def set_task(self, task_id: str, data: dict, ttl: int = 60) -> bool:
        return self._cache.set(f"task:{task_id}", json.dumps(data), ttl)

    def invalidate_task(self, task_id: str) -> bool:
        return self._cache.delete(f"task:{task_id}")

    # --- Config caching ---
    def get_config(self, workspace_id: str) -> dict | None:
        val = self._cache.get(f"config:{workspace_id}")
        if val:
            try:
                return json.loads(val)
            except json.JSONDecodeError:
                return None
        return None

    def set_config(self, workspace_id: str, data: dict, ttl: int = 3600) -> bool:
        return self._cache.set(f"config:{workspace_id}", json.dumps(data), ttl)

    def invalidate_config(self, workspace_id: str) -> bool:
        return self._cache.delete(f"config:{workspace_id}")

    # --- Template caching ---
    def get_template(self, template_id: str) -> dict | None:
        val = self._cache.get(f"template:{template_id}")
        if val:
            try:
                return json.loads(val)
            except json.JSONDecodeError:
                return None
        return None

    def set_template(self, template_id: str, data: dict, ttl: int = 1800) -> bool:
        return self._cache.set(f"template:{template_id}", json.dumps(data), ttl)

    def invalidate_template(self, template_id: str) -> bool:
        return self._cache.delete(f"template:{template_id}")

    # --- Sliding window rate limiting ---
    def rate_limit(
        self, key: str, limit: int, window: int
    ) -> tuple[bool, int, int]:
        """
        Sliding window rate limiter using sorted set.
        Returns (allowed, remaining, reset_in_seconds).
        """
        now = time.time()
        window_key = f"ratelimit:{key}"
        # Remove old entries outside window
        self._cache.zadd(window_key, {f"{now}": now})
        self._cache.zrangebyscore(window_key, 0, now - window)
        # Count current requests in window
        count = len(self._cache.zrangebyscore(window_key, now - window, now))
        if count >= limit:
            oldest = self._cache.zrangebyscore(window_key, now - window, now)
            if oldest:
                oldest_ts = float(oldest[0].split(":")[0]) if ":" in oldest[0] else float(oldest[0])
                reset_in = int(oldest_ts + window - now)
            else:
                reset_in = window
            return False, 0, max(1, reset_in)
        # Add new request
        req_id = f"{now}:{uuid.uuid4().hex[:8]}"
        self._cache.zadd(window_key, {req_id: now})
        self._cache.expire(window_key, window * 2)
        remaining = limit - count - 1
        return True, remaining, window

    # --- Distributed locking ---
    def acquire_lock(
        self, resource: str, timeout: int = 10, lease: int = 30
    ) -> str | None:
        """
        Acquire a distributed lock.
        Returns lock token if acquired, None otherwise.
        """
        lock_key = f"lock:{resource}"
        token = uuid.uuid4().hex
        # Try to set if not exists (NX)
        if self._cache.hset("locks", lock_key, token):
            self._cache.expire(lock_key, lease)
            return token
        return None

    def release_lock(self, resource: str, token: str) -> bool:
        """Release a distributed lock using token."""
        lock_key = f"lock:{resource}"
        current = self._cache.hget("locks", lock_key)
        if current == token:
            self._cache.hdel("locks", lock_key)
            return True
        return False

    def extend_lock(self, resource: str, token: str, ttl: int) -> bool:
        """Extend lock TTL."""
        lock_key = f"lock:{resource}"
        current = self._cache.hget("locks", lock_key)
        if current == token:
            self._cache.expire(lock_key, ttl)
            return True
        return False


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_redis_cache: RedisCache | None = None
_cache_layer: CacheLayer | None = None


def get_redis_cache() -> RedisCache:
    """Get the global RedisCache instance."""
    global _redis_cache
    if _redis_cache is None:
        _redis_cache = RedisCache()
    return _redis_cache


def get_cache_layer() -> CacheLayer:
    """Get the global CacheLayer instance."""
    global _cache_layer
    if _cache_layer is None:
        _cache_layer = CacheLayer(get_redis_cache())
    return _cache_layer
