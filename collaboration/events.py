"""nanobot-inspired AsyncMessageBus + Channel Adapter architecture.

重构自 events.py，将 EventBus 升级为 AsyncMessageBus，
支持多 Channel Adapter 接入（WebSocket/SSE/HTTP Webhook）。
"""

import asyncio
import json
import logging
import threading
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Coroutine

_log = logging.getLogger(__name__)

COLLAB_BASE = Path("~/.hermes/collab").expanduser()
COLLAB_BASE.mkdir(parents=True, exist_ok=True)


class EventType(str, Enum):
    # Task events
    TASK_CREATED = "task.created"
    TASK_UPDATED = "task.updated"
    TASK_DELETED = "task.deleted"
    # Agent events
    AGENT_REGISTERED = "agent.registered"
    AGENT_STATUS_CHANGED = "agent.status_changed"
    AGENT_UNREGISTERED = "agent.unregistered"
    # Workspace events
    WORKSPACE_CREATED = "workspace.created"
    WORKSPACE_DELETED = "workspace.deleted"
    # Skill events
    SKILL_CREATED = "skill.created"
    SKILL_UPDATED = "skill.updated"
    # Orchestration events
    ORCHESTRATION_CREATED = "orchestration.created"
    ORCHESTRATION_PLAN_READY = "orchestration.plan_ready"
    ORCHESTRATION_USER_CONFIRMED = "orchestration.user_confirmed"
    ORCHESTRATION_COMPLETED = "orchestration.completed"
    ORCHESTRATION_FAILED = "orchestration.failed"
    SUBTASK_STARTING = "subtask.starting"
    SUBTASK_STARTED = "subtask.started"
    SUBTASK_COMPLETED = "subtask.completed"
    SUBTASK_REJECTED = "subtask.rejected"
    SUBTASK_RETRY = "subtask.retry"
    REVIEW_CREATED = "review.created"


@dataclass
class Event:
    """Immutable event payload."""
    event_type: EventType | str
    workspace_id: str | None = None
    payload: dict[str, Any] | None = None
    _timestamp: str = field(default="", repr=False)

    def __post_init__(self):
        if not self._timestamp:
            self._timestamp = datetime.now(timezone.utc).isoformat()

    @property
    def timestamp(self) -> str:
        return self._timestamp

    def to_dict(self) -> dict[str, Any]:
        et = self.event_type.value if isinstance(self.event_type, EventType) else self.event_type
        return {
            "event": et,
            "workspace_id": self.workspace_id,
            "payload": self.payload or {},
            "timestamp": self._timestamp,
        }


# ─── Dead Letter Store ─────────────────────────────────────────────────────────

DEAD_LETTER_PATH = COLLAB_BASE / "dead_letters.json"
METRICS_PATH = COLLAB_BASE / "metrics.json"
_QUEUE_LOCK = threading.Lock()

# Global metrics
_metrics = {
    "messages_sent": 0,
    "messages_dropped": 0,
    "messages_dead_lettered": 0,
    "retries": 0,
}


def _read_dead_letters() -> list[dict]:
    if not DEAD_LETTER_PATH.exists():
        return []
    try:
        with open(DEAD_LETTER_PATH) as f:
            return json.load(f)
    except Exception:
        return []


def _write_dead_letter(entry: dict):
    with _QUEUE_LOCK:
        letters = _read_dead_letters()
        letters.append(entry)
        # Keep last 100
        letters = letters[-100:]
        with open(DEAD_LETTER_PATH, "w") as f:
            json.dump(letters, f)


def _increment_metric(key: str, delta: int = 1):
    with _QUEUE_LOCK:
        _metrics[key] = _metrics.get(key, 0) + delta
        # Persist metrics
        try:
            with open(METRICS_PATH, "w") as f:
                json.dump(_metrics, f)
        except Exception:
            pass


# ─── Channel Adapter ABC ───────────────────────────────────────────────────────

class ChannelAdapter(ABC):
    """nanobot-style Channel Adapter abstract base class."""

    name: str = "base"

    @abstractmethod
    async def publish(self, event: Event) -> bool:
        """Publish event to this channel. Return True if successful."""
        ...

    @abstractmethod
    async def subscribe(self, handler: Callable[[Event], Coroutine[Any, Any, None]] | None = None, event_types: set[str] | None = None):
        """Subscribe to events. If handler is None, just mark as active."""
        ...

    @abstractmethod
    async def start(self) -> None:
        """Start the channel (e.g., open connections)."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop the channel (e.g., close connections)."""
        ...

    async def health_check(self) -> bool:
        return True


# ─── WebSocket Channel Adapter ─────────────────────────────────────────────────

class WebSocketChannelAdapter(ChannelAdapter):
    """WebSocket channel adapter wrapping existing websocket_server broadcast."""

    name = "websocket"

    def __init__(self):
        self._handlers: list[Callable] = []
        self._ws_rooms: dict[str, set] = defaultdict(set)
        self._ws_lock = asyncio.Lock()
        self._active = False

    async def publish(self, event: Event) -> bool:
        if not event.workspace_id or event.workspace_id not in self._ws_rooms:
            return True  # No subscribers, not an error
        msg = json.dumps(event.to_dict(), default=str)
        dead = set()
        async with self._ws_lock:
            for ws in list(self._ws_rooms.get(event.workspace_id, [])):
                try:
                    await ws.send_text(msg)
                except Exception:
                    dead.add(ws)
            for ws in dead:
                self._ws_rooms[event.workspace_id].discard(ws)
        return True

    async def subscribe(self, handler: Callable[[Event], Coroutine[Any, Any, None]] | None = None, event_types: set[str] | None = None):
        if handler:
            self._handlers.append(handler)

    async def start(self) -> None:
        self._active = True
        _log.info("WebSocketChannelAdapter started")

    async def stop(self) -> None:
        self._active = False
        self._ws_rooms.clear()
        _log.info("WebSocketChannelAdapter stopped")

    async def add_client(self, ws, workspace_id: str):
        async with self._ws_lock:
            self._ws_rooms[workspace_id].add(ws)

    async def remove_client(self, ws, workspace_id: str):
        async with self._ws_lock:
            self._ws_rooms[workspace_id].discard(ws)
            if not self._ws_rooms[workspace_id]:
                del self._ws_rooms[workspace_id]


# ─── SSE Channel Adapter ───────────────────────────────────────────────────────

class SSEChannelAdapter(ChannelAdapter):
    """SSE channel adapter for Server-Sent Events."""

    name = "sse"

    def __init__(self):
        self._clients: dict[str, list] = defaultdict(list)
        self._client_lock = asyncio.Lock()
        self._active = False

    async def publish(self, event: Event) -> bool:
        if not event.workspace_id:
            return True
        msg = f"data: {json.dumps(event.to_dict(), default=str)}\n\n"
        dead = []
        async with self._client_lock:
            clients = list(self._clients.get(event.workspace_id, []))
        for client in clients:
            try:
                await client(msg)
            except Exception:
                dead.append(client)
        if dead:
            async with self._client_lock:
                self._clients[event.workspace_id] = [
                    c for c in self._clients.get(event.workspace_id, []) if c not in dead
                ]
        return True

    async def subscribe(self, handler: Callable[[Event], Coroutine[Any, Any, None]] | None = None, event_types: set[str] | None = None):
        pass

    async def start(self) -> None:
        self._active = True
        _log.info("SSEChannelAdapter started")

    async def stop(self) -> None:
        self._active = False
        self._clients.clear()
        _log.info("SSEChannelAdapter stopped")

    async def add_client(self, send_fn, workspace_id: str):
        async with self._client_lock:
            self._clients[workspace_id].append(send_fn)

    async def remove_client(self, send_fn, workspace_id: str):
        async with self._client_lock:
            self._clients[workspace_id] = [c for c in self._clients.get(workspace_id, []) if c != send_fn]


# ─── HTTP Webhook Adapter ──────────────────────────────────────────────────────

class HTTPWebhookAdapter(ChannelAdapter):
    """HTTP Webhook adapter — sends events to external HTTP endpoints (nanobot-style)."""

    name = "http_webhook"

    def __init__(self):
        self._endpoints: dict[str, list[str]] = defaultdict(list)  # event_type -> url list
        self._lock = asyncio.Lock()
        self._active = False

    async def publish(self, event: Event) -> bool:
        et = event.event_type.value if isinstance(event.event_type, EventType) else event.event_type
        if et not in self._endpoints:
            return True

        urls = list(self._endpoints[et])
        payload = event.to_dict()
        success = True

        for url in urls:
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        if resp.status >= 400:
                            _log.warning(f"Webhook {url} returned {resp.status}")
                            success = False
            except Exception as e:
                _log.warning(f"Webhook publish failed for {url}: {e}")
                success = False

        return success

    async def subscribe(self, handler: Callable[[Event], Coroutine[Any, Any, None]] | None = None, event_types: set[str] | None = None):
        pass

    async def start(self) -> None:
        self._active = True
        _log.info("HTTPWebhookAdapter started")

    async def stop(self) -> None:
        self._active = False
        _log.info("HTTPWebhookAdapter stopped")

    def register_webhook(self, event_type: str, url: str):
        """Register a webhook endpoint for an event type."""
        with _QUEUE_LOCK:
            if event_type not in self._endpoints:
                self._endpoints[event_type] = []
            if url not in self._endpoints[event_type]:
                self._endpoints[event_type].append(url)

    def unregister_webhook(self, event_type: str, url: str):
        if event_type in self._endpoints:
            self._endpoints[event_type] = [u for u in self._endpoints[event_type] if u != url]


# ─── Channel Registry ──────────────────────────────────────────────────────────

class ChannelRegistry:
    """nanobot-style Channel Registry managing multiple adapters."""

    def __init__(self):
        self._channels: dict[str, ChannelAdapter] = {}
        self._lock = asyncio.Lock()

    def register(self, adapter: ChannelAdapter):
        self._channels[adapter.name] = adapter
        _log.info(f"Channel registered: {adapter.name}")

    def unregister(self, name: str):
        self._channels.pop(name, None)

    def get(self, name: str) -> ChannelAdapter | None:
        return self._channels.get(name)

    async def publish_all(self, event: Event) -> dict[str, bool]:
        results = {}
        async with self._lock:
            channels = list(self._channels.values())
        for ch in channels:
            try:
                results[ch.name] = await ch.publish(event)
            except Exception as e:
                _log.exception(f"Channel {ch.name} publish error: {e}")
                results[ch.name] = False
        return results

    async def start_all(self):
        async with self._lock:
            channels = list(self._channels.values())
        for ch in channels:
            try:
                await ch.start()
            except Exception as e:
                _log.exception(f"Channel {ch.name} start error: {e}")

    async def stop_all(self):
        async with self._lock:
            channels = list(self._channels.values())
        for ch in channels:
            try:
                await ch.stop()
            except Exception as e:
                _log.exception(f"Channel {ch.name} stop error: {e}")


# ─── AsyncMessageBus ──────────────────────────────────────────────────────────

@dataclass
class DeadLetterEntry:
    event: dict
    error: str
    attempts: int
    first_failure: str
    last_failure: str


class AsyncMessageBus:
    """nanobot-inspired AsyncMessageBus.

    核心特性：
    - asyncio 原生并发
    - Channel Adapter 模式
    - 消息队列缓冲
    - 指数退避重试
    - Dead Letter 处理
    """

    MAX_QUEUE_SIZE = 1000
    MAX_RETRIES = 3
    RETRY_BASE_DELAY = 0.1  # seconds

    def __init__(self):
        self._subscribers: list[tuple[set[str] | None, str | None, Callable, str | None]] = []
        self._lock = asyncio.Lock()
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self.MAX_QUEUE_SIZE)
        self._channel_registry = ChannelRegistry()
        self._ws_adapter = WebSocketChannelAdapter()
        self._sse_adapter = SSEChannelAdapter()
        self._http_adapter = HTTPWebhookAdapter()
        self._channel_registry.register(self._ws_adapter)
        self._channel_registry.register(self._sse_adapter)
        self._channel_registry.register(self._http_adapter)
        self._worker_task: asyncio.Task | None = None
        self._running = False

    @property
    def ws(self) -> WebSocketChannelAdapter:
        return self._ws_adapter

    @property
    def sse(self) -> SSEChannelAdapter:
        return self._sse_adapter

    @property
    def http(self) -> HTTPWebhookAdapter:
        return self._http_adapter

    @property
    def channels(self) -> ChannelRegistry:
        return self._channel_registry

    def set_channel_registry(self, registry: ChannelRegistry):
        """Allow external registry injection (e.g., from server.py)."""
        self._channel_registry = registry

    # ── Pub/Sub ────────────────────────────────────────────────────────────────

    async def subscribe(
        self,
        callback: Callable[[Event], Coroutine[Any, Any, None] | None],
        event_types: set[str] | None = None,
        workspace_id: str | None = None,
    ):
        async with self._lock:
            self._subscribers.append((set(event_types) if event_types else None, workspace_id, callback, None))

    def subscribe_sync(
        self,
        callback: Callable[[Event], None],
        event_types: set[str] | None = None,
        workspace_id: str | None = None,
    ):
        async def _wrapper(event: Event):
            callback(event)
        self._subscribers.append((set(event_types) if event_types else None, workspace_id, _wrapper, "_sync"))

    async def unsubscribe(self, callback: Callable):
        async with self._lock:
            self._subscribers = [
                (ft, ws, cb, *rest) for ft, ws, cb, *rest in self._subscribers if cb != callback
            ]

    # ── Emit with retry + dead-letter ─────────────────────────────────────────

    async def emit(self, event: Event):
        """Emit event to all subscribers and channels, with retry logic."""
        _increment_metric("messages_sent")

        # Enqueue to worker for background processing
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            _increment_metric("messages_dropped")
            _log.warning(f"Queue full, dropping event: {event.event_type}")
            return

        if not self._running:
            await self._process_event(event)

    async def _process_event(self, event: Event):
        """Process a single event: retry + dispatch to subscribers and channels."""
        for attempt in range(1, self.MAX_RETRIES + 1):
            results = await self._channel_registry.publish_all(event)
            success = all(results.values())

            if success:
                # Dispatch to in-process subscribers
                await self._dispatch_to_subscribers(event)
                return

            if attempt < self.MAX_RETRIES:
                _increment_metric("retries")
                delay = self.RETRY_BASE_DELAY * (2 ** (attempt - 1))
                await asyncio.sleep(delay)

        # Dead-letter after all retries exhausted
        _increment_metric("messages_dead_lettered")
        dead_letter = {
            "event": event.to_dict(),
            "error": "All retry attempts failed",
            "attempts": self.MAX_RETRIES,
            "first_failure": event.timestamp,
            "last_failure": datetime.now(timezone.utc).isoformat(),
        }
        _write_dead_letter(dead_letter)
        _log.error(f"Dead-lettered event after {self.MAX_RETRIES} retries: {event.event_type}")

    async def _dispatch_to_subscribers(self, event: Event):
        async with self._lock:
            subscribers = list(self._subscribers)

        for filters, ws_id, cb, *rest in subscribers:
            sync_marker = rest[0] if rest else None

            if ws_id is not None and event.workspace_id != ws_id:
                continue
            et_val = event.event_type.value if isinstance(event.event_type, EventType) else event.event_type
            if filters and et_val not in filters:
                continue

            try:
                if sync_marker == "_sync":
                    cb(event)
                else:
                    await cb(event)
            except Exception:
                _log.exception(f"Subscriber callback error: {cb}")

    # ── Background worker ─────────────────────────────────────────────────────

    async def start(self):
        """Start the background queue worker."""
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._worker_loop())
        await self._channel_registry.start_all()
        _log.info("AsyncMessageBus started")

    async def stop(self):
        """Stop the background worker and all channels."""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        await self._channel_registry.stop_all()
        _log.info("AsyncMessageBus stopped")

    async def _worker_loop(self):
        """Background worker that drains the queue."""
        while self._running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                await self._process_event(event)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception:
                _log.exception("Worker loop error")

    # ── Backward-compatible helpers (delegated to channels) ──────────────────

    async def emit_agent_registered(self, agent_id: str, workspace_id: str, agent_data: dict):
        await self.emit(Event(EventType.AGENT_REGISTERED, workspace_id=workspace_id, payload={"agent_id": agent_id, **agent_data}))

    async def emit_agent_status_changed(self, agent_id: str, workspace_id: str, old_status: str, new_status: str):
        await self.emit(Event(EventType.AGENT_STATUS_CHANGED, workspace_id=workspace_id, payload={"agent_id": agent_id, "old_status": old_status, "new_status": new_status}))

    async def emit_skill_created(self, skill_id: str, workspace_id: str, skill_data: dict):
        await self.emit(Event(EventType.SKILL_CREATED, workspace_id=workspace_id, payload={"skill_id": skill_id, **skill_data}))

    async def emit_task_created(self, task_id: str, workspace_id: str, task_data: dict):
        await self.emit(Event(EventType.TASK_CREATED, workspace_id=workspace_id, payload={"task_id": task_id, **task_data}))

    async def emit_task_updated(self, task_id: str, workspace_id: str, task_data: dict):
        await self.emit(Event(EventType.TASK_UPDATED, workspace_id=workspace_id, payload={"task_id": task_id, **task_data}))

    async def emit_task_completed(self, task_id: str, workspace_id: str, task_data: dict):
        await self.emit(Event(EventType.TASK_COMPLETED, workspace_id=workspace_id, payload={"task_id": task_id, **task_data}))

    async def emit_task_failed(self, task_id: str, workspace_id: str, task_data: dict):
        await self.emit(Event(EventType.TASK_FAILED, workspace_id=workspace_id, payload={"task_id": task_id, **task_data}))

    # ── Dead-letter access ─────────────────────────────────────────────────

    def get_dead_letters(self) -> list[dict]:
        """Return all dead-letter entries from storage."""
        return _read_dead_letters()

    def clear_dead_letters(self):
        """Clear all dead-letter entries."""
        with _QUEUE_LOCK:
            try:
                with open(DEAD_LETTER_PATH, "w") as f:
                    json.dump([], f)
            except Exception:
                pass

    # ── Metrics ────────────────────────────────────────────────────────────

    def get_metrics(self) -> dict:
        """Return message bus metrics."""
        return {
            "messages_sent": _metrics.get("messages_sent", 0),
            "messages_failed": _metrics.get("messages_dead_lettered", 0),
            "retries": _metrics.get("retries", 0),
            "queue_size": self._queue.qsize(),
            "subscribers": len(self._subscribers),
            "adapters": len(self._channel_registry._channels),
        }

    # ── Backward-compat ────────────────────────────────────────────────────

    def set_ws_broadcast(self, func: Callable):
        """Set a WebSocket broadcast callback (backward compat — no-op in new arch)."""
        pass


# ─── Global singleton ──────────────────────────────────────────────────────────

_message_bus: "AsyncMessageBus | None" = None


def get_message_bus() -> "AsyncMessageBus":
    global _message_bus
    if _message_bus is None:
        _message_bus = AsyncMessageBus()
    return _message_bus


# Backward-compat alias
def get_event_bus() -> "AsyncMessageBus":
    return get_message_bus()


__all__ = [
    "Event", "EventType", "AsyncMessageBus", "EventBus",
    "ChannelAdapter", "WebSocketChannelAdapter", "SSEChannelAdapter", "HTTPWebhookAdapter",
    "ChannelRegistry", "DeadLetterEntry",
    "get_message_bus", "get_event_bus",
    "DEAD_LETTER_PATH", "METRICS_PATH", "_metrics",
]