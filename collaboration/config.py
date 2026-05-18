"""
Configuration for hermes-agent-collab.

Loads configuration from environment variables with sensible defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class CollabConfig:
    """
    Central configuration for hermes-agent-collab.

    All values can be overridden via environment variables.
    """

    # === Server ===
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False

    # === Redis ===
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str | None = None
    REDIS_STREAM_KEY: str = "collab.events"
    REDIS_STREAM_MAXLEN: int = 10000
    REDIS_PUBSUB_PREFIX: str = "collab"
    REDIS_CONSUMER_GROUP: str = "collab-consumers"

    # === Channel Adapters ===
    # List of enabled channel adapters: ["redis_stream", "redis_pubsub", "sse"]
    CHANNEL_ADAPTERS: list[str] = None  # None means all available

    # === SSE ===
    SSE_HEARTBEAT_INTERVAL: int = 30  # seconds

    # === Auth ===
    API_KEY_HEADER: str = "X-API-Key"
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_MINUTES: int = 60 * 24  # 24 hours

    # === Storage ===
    STORAGE_BACKEND: str = "memory"  # "memory", "sqlite", "postgres"
    SQLITE_DB_PATH: str = "collab.db"
    SQLITE_WAL_MODE: bool = True

    # PostgreSQL (used when STORAGE_BACKEND=postgres)
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "hermes_collab"
    POSTGRES_USER: str = "hermes"
    POSTGRES_PASSWORD: str = "hermes"
    POSTGRES_POOL_SIZE: int = 10
    POSTGRES_CONNECTION_STRING: str | None = None  # Overrides above if set

    # === Monitoring ===
    METRICS_ENABLED: bool = True

    def __post_init__(self):
        if self.CHANNEL_ADAPTERS is None:
            self.CHANNEL_ADAPTERS = ["redis_stream", "redis_pubsub", "sse"]

        # Load from environment variables
        self.HOST = os.getenv("COLLAB_HOST", self.HOST)
        self.PORT = int(os.getenv("COLLAB_PORT", str(self.PORT)))
        self.DEBUG = os.getenv("COLLAB_DEBUG", str(self.DEBUG)).lower() in ("true", "1", "yes")

        # Redis
        self.REDIS_HOST = os.getenv("REDIS_HOST", self.REDIS_HOST)
        self.REDIS_PORT = int(os.getenv("REDIS_PORT", str(self.REDIS_PORT)))
        self.REDIS_DB = int(os.getenv("REDIS_DB", str(self.REDIS_DB)))
        self.REDIS_PASSWORD = os.getenv("REDIS_PASSWORD") or None
        self.REDIS_STREAM_KEY = os.getenv("REDIS_STREAM_KEY", self.REDIS_STREAM_KEY)
        self.REDIS_STREAM_MAXLEN = int(os.getenv("REDIS_STREAM_MAXLEN", str(self.REDIS_STREAM_MAXLEN)))
        self.REDIS_PUBSUB_PREFIX = os.getenv("REDIS_PUBSUB_PREFIX", self.REDIS_PUBSUB_PREFIX)
        self.REDIS_CONSUMER_GROUP = os.getenv("REDIS_CONSUMER_GROUP", self.REDIS_CONSUMER_GROUP)

        # Channel adapters
        adapters_env = os.getenv("CHANNEL_ADAPTERS")
        if adapters_env:
            self.CHANNEL_ADAPTERS = [a.strip() for a in adapters_env.split(",")]

        # Auth
        self.API_KEY_HEADER = os.getenv("API_KEY_HEADER", self.API_KEY_HEADER)
        self.JWT_SECRET = os.getenv("JWT_SECRET", self.JWT_SECRET)
        self.JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", self.JWT_ALGORITHM)
        jwt_exp = os.getenv("JWT_EXPIRATION_MINUTES")
        if jwt_exp:
            self.JWT_EXPIRATION_MINUTES = int(jwt_exp)

        # Storage
        self.STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", self.STORAGE_BACKEND)
        self.SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", self.SQLITE_DB_PATH)

        # PostgreSQL
        self.POSTGRES_HOST = os.getenv("POSTGRES_HOST", self.POSTGRES_HOST)
        self.POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", str(self.POSTGRES_PORT)))
        self.POSTGRES_DB = os.getenv("POSTGRES_DB", self.POSTGRES_DB)
        self.POSTGRES_USER = os.getenv("POSTGRES_USER", self.POSTGRES_USER)
        self.POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", self.POSTGRES_PASSWORD)
        pg_pool = os.getenv("POSTGRES_POOL_SIZE")
        if pg_pool:
            self.POSTGRES_POOL_SIZE = int(pg_pool)
        self.POSTGRES_CONNECTION_STRING = os.getenv("POSTGRES_CONNECTION_STRING") or None

        # Monitoring
        metrics_env = os.getenv("METRICS_ENABLED")
        if metrics_env is not None:
            self.METRICS_ENABLED = metrics_env.lower() in ("true", "1", "yes")


# Global singleton
_config: CollabConfig | None = None


def get_config() -> CollabConfig:
    """Get global CollabConfig singleton."""
    global _config
    if _config is None:
        _config = CollabConfig()
    return _config
