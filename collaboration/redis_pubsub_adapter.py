"""
Redis Pub/Sub Channel Adapter for hermes-agent-collab.

Provides low-latency single-session event broadcasting via Redis Pub/Sub.
For multi-subscriber fan-out with message persistence, use RedisStreamAdapter.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, AsyncIterator

import redis.asyncio as redis

from .config import CollabConfig
from .hook_manager import ChannelAdapter, HookEvent


class RedisPubSubAdapter(ChannelAdapter):
    """
    Redis Pub/Sub adapter for low-latency session broadcasting.

    Each session gets its own channel: collab:{session_id}:events
    Channels are ephemeral — no message persistence.
    """

    def __init__(self, config: CollabConfig | None = None):
        self.config = config or CollabConfig()
        self._client: redis.Redis | None = None
        self._pubsub: redis.client.PubSub | None = None
        self._channel_prefix = self.config.REDIS_PUBSUB_PREFIX
        self._subscription_task: asyncio.Task | None = None
        self._message_queue: asyncio.Queue[HookEvent] | None = None

    def get_channel(self, session_id: str) -> str:
        """Get Redis channel name for a session."""
        return f"{self._channel_prefix}:{session_id}:events"

    async def _get_client(self) -> redis.Redis:
        """Lazy Redis client initialization."""
        if self._client is None:
            self._client = redis.Redis(
                host=self.config.REDIS_HOST,
                port=self.config.REDIS_PORT,
                db=self.config.REDIS_DB,
                password=self.config.REDIS_PASSWORD,
                decode_responses=False,
            )
        return self._client

    async def connect(self) -> None:
        """Initialize Redis connection."""
        client = await self._get_client()
        await client.ping()

    async def disconnect(self) -> None:
        """Close Redis connection and cancel subscription tasks."""
        if self._subscription_task:
            self._subscription_task.cancel()
            try:
                await self._subscription_task
            except asyncio.CancelledError:
                pass
            self._subscription_task = None

        if self._pubsub:
            await self._pubsub.close()
            self._pubsub = None

        if self._client:
            await self._client.aclose()
            self._client = None

    async def publish(self, event: HookEvent, session_id: str) -> int:
        """
        Publish event to session's Redis Pub/Sub channel.

        Returns number of subscribers that received the message.
        """
        client = await self._get_client()
        channel = self.get_channel(session_id)
        message = self._serialize_event(event)
        return await client.publish(channel, message)

    async def publish_broadcast(self, event: HookEvent) -> int:
        """
        Publish event to all sessions via pattern subscription.

        Note: This is a best-effort broadcast. For guaranteed delivery
        to all subscribers, use StreamAdapter with fan-out.
        """
        client = await self._get_client()
        # Publish to a global channel that all subscribers listen to
        global_channel = f"{self._channel_prefix}:broadcast:events"
        message = self._serialize_event(event)
        return await client.publish(global_channel, message)

    async def subscribe(self, session_id: str) -> AsyncIterator[HookEvent]:
        """
        Subscribe to session's Redis Pub/Sub channel.

        Returns an async iterator that yields HookEvents as they arrive.
        The subscription runs in the background.

        Usage:
            async for event in adapter.subscribe(session_id):
                print(event)
        """
        client = await self._get_client()
        channel = self.get_channel(session_id)

        pubsub = client.pubsub()
        await pubsub.subscribe(channel)

        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = message["data"]
                    data_str = data.decode("utf-8") if isinstance(data, bytes) else data
                    event = self._deserialize_event(data_str)
                    if event:
                        yield event
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()

    async def subscribe_pattern(self, pattern: str = None) -> AsyncIterator[tuple[str, HookEvent]]:
        """
        Subscribe to channels matching a pattern.

        Yields (channel, event) tuples.

        Usage:
            async for channel, event in adapter.subscribe_pattern("collab:*:events"):
                print(f"{channel}: {event}")
        """
        if pattern is None:
            pattern = f"{self._channel_prefix}:*:events"

        client = await self._get_client()
        pubsub = client.pubsub()
        await pubsub.psubscribe(pattern)

        try:
            async for message in pubsub.listen():
                if message["type"] == "pmessage":
                    channel = message["channel"].decode("utf-8") if isinstance(message["channel"], bytes) else message["channel"]
                    data = message["data"]
                    data_str = data.decode("utf-8") if isinstance(data, bytes) else data
                    event = self._deserialize_event(data_str)
                    if event:
                        yield channel, event
        finally:
            await pubsub.punsubscribe(pattern)
            await pubsub.close()

    def _serialize_event(self, event: HookEvent) -> str:
        """Serialize HookEvent to JSON string."""
        payload = {
            "event_type": event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type),
            "source": event.source,
            "timestamp": event.timestamp.isoformat() if event.timestamp else datetime.utcnow().isoformat(),
            "data": event.data,
        }
        return json.dumps(payload, default=str)

    def _deserialize_event(self, data: str) -> HookEvent | None:
        """Deserialize JSON string to HookEvent."""
        try:
            payload = json.loads(data)
            from .models import HookEvent, HookEventType

            event_type_str = payload.get("event_type", "")
            try:
                event_type = HookEventType(event_type_str)
            except (ValueError, TypeError):
                event_type = HookEventType.CUSTOM

            timestamp_str = payload.get("timestamp")
            if timestamp_str:
                try:
                    timestamp = datetime.fromisoformat(timestamp_str)
                except ValueError:
                    timestamp = datetime.utcnow()
            else:
                timestamp = datetime.utcnow()

            return HookEvent(
                event_type=event_type,
                source=payload.get("source", "unknown"),
                timestamp=timestamp,
                data=payload.get("data", {}),
            )
        except (json.JSONDecodeError, KeyError, TypeError):
            return None


# Singleton instance
_pubsub_adapter: RedisPubSubAdapter | None = None


def get_redis_pubsub_adapter(config: CollabConfig | None = None) -> RedisPubSubAdapter:
    """Get singleton RedisPubSubAdapter instance."""
    global _pubsub_adapter
    if _pubsub_adapter is None:
        _pubsub_adapter = RedisPubSubAdapter(config)
    return _pubsub_adapter
