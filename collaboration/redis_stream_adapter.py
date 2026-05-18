"""
Redis Stream Channel Adapter for hermes-agent-collab.

Provides event persistence and断线重连 support via Redis Streams.
Supports consumer groups for horizontal scaling.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator

import redis.asyncio as redis

from .config import CollabConfig
from .hook_manager import ChannelAdapter, HookEvent


@dataclass
class EventWithMeta:
    """Event with Redis Stream metadata."""
    event_id: str  # Redis Stream entry ID: timestamp-sequence (e.g., "12345678900000-0")
    event: HookEvent
    timestamp: datetime


class RedisStreamAdapter(ChannelAdapter):
    """
    Redis Stream adapter for event persistence and fan-out.

    Uses XADD/XREAD/XREADGROUP for event publishing and consumption.
    Supports consumer groups for multi-instance horizontal scaling.
    """

    def __init__(self, config: CollabConfig | None = None):
        self.config = config or CollabConfig()
        self._client: redis.Redis | None = None
        self._stream_key = self.config.REDIS_STREAM_KEY
        self._maxlen = self.config.REDIS_STREAM_MAXLEN

    async def _get_client(self) -> redis.Redis:
        """Lazy Redis client initialization."""
        if self._client is None:
            self._client = redis.Redis(
                host=self.config.REDIS_HOST,
                port=self.config.REDIS_PORT,
                db=self.config.REDIS_DB,
                password=self.config.REDIS_PASSWORD,
                decode_responses=False,  # We handle encoding
            )
        return self._client

    async def connect(self) -> None:
        """Initialize Redis connection."""
        client = await self._get_client()
        await client.ping()

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def publish(self, event: HookEvent) -> str:
        """
        Publish event to Redis Stream.

        Returns the Redis Stream entry ID.
        """
        client = await self._get_client()
        event_data = self._serialize_event(event)
        # XADD collab.events MAXLEN ~ 10000 * entry_id payload
        event_id = await client.xadd(
            self._stream_key,
            {"data": event_data},
            maxlen=self._maxlen,
            approximate=True,
        )
        return event_id.decode("utf-8") if isinstance(event_id, bytes) else event_id

    async def read_since(
        self,
        event_id: str | None = None,
        count: int = 100,
    ) -> list[EventWithMeta]:
        """
        Read events from Stream since given event_id.

        If event_id is None, reads from beginning.
        If event_id is "$", reads new events only (blocking).

        Returns list of EventWithMeta sorted by event_id.
        """
        client = await self._get_client()

        if event_id is None:
            # Read from beginning
            streams = {self._stream_key: "0"}
        elif event_id == "$":
            # No historical reads, caller will use blocking read
            return []
        else:
            # Read from event_id + 1 (exclusive)
            streams = {self._stream_key: event_id}

        try:
            result = await client.xread(streams=streams, count=count)
        except redis.ResponseError as e:
            if "NOGROUP" in str(e):
                # Consumer group doesn't exist yet
                return []
            raise

        events = []
        if not result:
            return events

        # result format: [(stream_key, [(event_id, {field: value, ...}), ...])]
        for stream_key, entries in result:
            for entry_id, fields in entries:
                entry_id_str = entry_id.decode("utf-8") if isinstance(entry_id, bytes) else entry_id
                data = fields.get(b"data") or fields.get("data")
                if data:
                    data_str = data.decode("utf-8") if isinstance(data, bytes) else data
                    event = self._deserialize_event(data_str)
                    if event:
                        # Parse timestamp from event_id (format: timestamp-sequence)
                        try:
                            ts_part = entry_id_str.split("-")[0]
                            ts_ms = int(ts_part) / 1000.0
                            timestamp = datetime.fromtimestamp(ts_ms)
                        except (ValueError, IndexError):
                            timestamp = datetime.utcnow()

                        events.append(EventWithMeta(
                            event_id=entry_id_str,
                            event=event,
                            timestamp=timestamp,
                        ))

        return events

    async def read_blocking(
        self,
        event_id: str = "$",
        timeout_ms: int = 30000,
    ) -> list[EventWithMeta]:
        """
        Blocking read for new events.

        Reads events after the given event_id (or $ for new only).
        Blocks for timeout_ms if no new events.
        """
        client = await self._get_client()
        streams = {self._stream_key: event_id}

        try:
            result = await client.xread(streams=streams, count=100, block=timeout_ms)
        except redis.ResponseError as e:
            if "NOGROUP" in str(e):
                return []
            raise

        events = []
        if not result:
            return events

        for stream_key, entries in result:
            for entry_id, fields in entries:
                entry_id_str = entry_id.decode("utf-8") if isinstance(entry_id, bytes) else entry_id
                data = fields.get(b"data") or fields.get("data")
                if data:
                    data_str = data.decode("utf-8") if isinstance(data, bytes) else data
                    event = self._deserialize_event(data_str)
                    if event:
                        try:
                            ts_part = entry_id_str.split("-")[0]
                            ts_ms = int(ts_part) / 1000.0
                            timestamp = datetime.fromtimestamp(ts_ms)
                        except (ValueError, IndexError):
                            timestamp = datetime.utcnow()

                        events.append(EventWithMeta(
                            event_id=entry_id_str,
                            event=event,
                            timestamp=timestamp,
                        ))

        return events

    async def create_consumer_group(self, group_name: str) -> bool:
        """
        Create consumer group for this stream.

        Uses $ (latest) as start ID so new consumers only get new events.
        Use create_consumer_group_with_start(start_id) to read from beginning.
        """
        client = await self._get_client()
        try:
            await client.xgroup_create(
                self._stream_key,
                group_name,
                id="$",
                mkstream=True,
            )
            return True
        except redis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                # Group already exists
                return True
            raise

    async def create_consumer_group_from_beginning(self, group_name: str) -> bool:
        """Create consumer group that reads all historical events."""
        client = await self._get_client()
        try:
            await client.xgroup_create(
                self._stream_key,
                group_name,
                id="0",
                mkstream=True,
            )
            return True
        except redis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                return True
            raise

    async def read_group(
        self,
        group_name: str,
        consumer_name: str,
        event_id: str = ">",
        count: int = 100,
        block_ms: int | None = None,
    ) -> list[EventWithMeta]:
        """
        Read events as a consumer group member.

        event_id=">" reads new messages only (non-blocking for existing).
        event_id="0" reads all pending (unacknowledged) messages.
        """
        client = await self._get_client()

        try:
            if block_ms:
                result = await client.xreadgroup(
                    groupname=group_name,
                    consumername=consumer_name,
                    streams={self._stream_key: event_id},
                    count=count,
                    block=block_ms,
                )
            else:
                result = await client.xreadgroup(
                    groupname=group_name,
                    consumername=consumer_name,
                    streams={self._stream_key: event_id},
                    count=count,
                )
        except redis.ResponseError as e:
            if "NOGROUP" in str(e):
                return []
            raise

        events = []
        if not result:
            return events

        for stream_key, entries in result:
            for entry_id, fields in entries:
                entry_id_str = entry_id.decode("utf-8") if isinstance(entry_id, bytes) else entry_id
                data = fields.get(b"data") or fields.get("data")
                if data:
                    data_str = data.decode("utf-8") if isinstance(data, bytes) else data
                    event = self._deserialize_event(data_str)
                    if event:
                        try:
                            ts_part = entry_id_str.split("-")[0]
                            ts_ms = int(ts_part) / 1000.0
                            timestamp = datetime.fromtimestamp(ts_ms)
                        except (ValueError, IndexError):
                            timestamp = datetime.utcnow()

                        events.append(EventWithMeta(
                            event_id=entry_id_str,
                            event=event,
                            timestamp=timestamp,
                        ))

        return events

    async def acknowledge(self, event_ids: list[str]) -> int:
        """
        Acknowledge processed events.

        Returns number of events acknowledged.
        """
        if not event_ids:
            return 0

        client = await self._get_client()
        # Get consumer group name from config or use default
        group_name = getattr(self.config, "REDIS_CONSUMER_GROUP", "collab-consumers")

        try:
            acknowledged = await client.xack(self._stream_key, group_name, *event_ids)
            return acknowledged
        except redis.ResponseError:
            return 0

    async def pending_messages(
        self,
        group_name: str,
        count: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Get pending messages for consumer group.

        Returns list of XPENDING info dicts.
        """
        client = await self._get_client()

        try:
            pending = await client.xpending(self._stream_key, group_name, count=count)
        except redis.ResponseError:
            return []

        if not pending or pending == (0, None, None, []):
            return []

        # pending format: (min_id, max_id, count, [(consumer, pending_count, idle_time, last_delivery_ids)])
        result = []
        if len(pending) >= 3:
            _, _, total_count, entries = pending
            for consumer, msg_count, idle_time, msg_ids in entries:
                result.append({
                    "consumer": consumer,
                    "message_count": msg_count,
                    "idle_time_ms": idle_time,
                    "last_delivery_ids": msg_ids,
                })

        return result

    async def get_stream_info(self) -> dict[str, Any]:
        """Get Stream info for monitoring."""
        client = await self._get_client()

        try:
            info = await client.xinfo_stream(self._stream_key)
            return dict(info) if info else {}
        except redis.ResponseError:
            return {"length": 0, "first_entry": None, "last_entry": None}

    def _serialize_event(self, event: HookEvent) -> str:
        """Serialize HookEvent to JSON string."""
        payload = {
            "event_id": str(uuid.uuid4()),
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
            # Try to parse enum value
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
_stream_adapter: RedisStreamAdapter | None = None


def get_redis_stream_adapter(config: CollabConfig | None = None) -> RedisStreamAdapter:
    """Get singleton RedisStreamAdapter instance."""
    global _stream_adapter
    if _stream_adapter is None:
        _stream_adapter = RedisStreamAdapter(config)
    return _stream_adapter
