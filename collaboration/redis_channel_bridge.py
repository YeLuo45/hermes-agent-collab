"""
Redis Channel Bridge — connects Redis Stream/PubSub adapters to the SSE delivery layer.

Provides read_since() for SSE断线重连, and publish() for routing events from
the HookManager to Redis Stream + PubSub simultaneously.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from .config import CollabConfig, get_config
from .redis_stream_adapter import RedisStreamAdapter, get_redis_stream_adapter

if TYPE_CHECKING:
    from .hook_manager import HookEvent

_log = logging.getLogger(__name__)

# Singleton
_bridge: RedisChannelBridge | None = None


class RedisChannelBridge:
    """
    Bridges Redis Stream/PubSub adapters to the SSE channel layer.

    Provides:
    - publish(event): writes to Redis Stream + optionally to session PubSub channels
    - read_since(event_id, session_id): reads from Stream for SSE reconnect recovery
    - connect(session_id): subscribe to session's PubSub channel for real-time delivery
    """

    def __init__(self, config: CollabConfig | None = None):
        self.config = config or get_config()
        self._stream: RedisStreamAdapter | None = None
        self._pubsub_tasks: dict[str, asyncio.Task] = {}
        self._pubsub_queues: dict[str, asyncio.Queue] = {}

    @property
    def stream(self) -> RedisStreamAdapter:
        if self._stream is None:
            self._stream = get_redis_stream_adapter(self.config)
        return self._stream

    async def connect(self) -> None:
        """Initialize Redis connections."""
        await self.stream.connect()
        _log.info("RedisChannelBridge connected")

    async def disconnect(self) -> None:
        """Close Redis connections and cancel PubSub tasks."""
        for task in self._pubsub_tasks.values():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._pubsub_tasks.clear()

        if self._stream:
            await self.stream.disconnect()
            self._stream = None
        _log.info("RedisChannelBridge disconnected")

    async def publish(self, event: "HookEvent") -> str:
        """
        Publish event to Redis Stream.

        Returns the Redis Stream entry ID.
        """
        return await self.stream.publish(event)

    async def read_since(self, event_id: str | None = None, count: int = 100):
        """
        Read events from Stream since given event_id.

        For SSE reconnect: pass last received event_id.
        Returns list of EventWithMeta.
        """
        return await self.stream.read_since(event_id=event_id, count=count)

    async def health_check(self) -> bool:
        """Check Redis connectivity."""
        try:
            await self.stream.connect()
            return True
        except Exception:
            return False


def get_redis_channel_bridge(config: CollabConfig | None = None) -> RedisChannelBridge:
    """Get singleton RedisChannelBridge."""
    global _bridge
    if _bridge is None:
        _bridge = RedisChannelBridge(config)
    return _bridge
