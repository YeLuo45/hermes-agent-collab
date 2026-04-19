"""Event bus for the collaboration module.

Provides an in-process pub/sub system that WebSocket broadcasters subscribe to
so that any component (task manager, agent registry, etc.) can emit events
without knowing about WebSocket connections.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine

_log = logging.getLogger(__name__)


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


class Event:
    """Immutable event payload sent over WebSocket."""

    def __init__(
        self,
        event_type: EventType | str,
        workspace_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ):
        self.event_type = EventType(event_type) if isinstance(event_type, str) else event_type
        self.workspace_id = workspace_id
        self.payload = payload or {}
        self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event_type.value,
            "workspace_id": self.workspace_id,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }


# Global singleton
_event_bus: "EventBus | None" = None


def get_event_bus() -> "EventBus":
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


# Re-export EventType for convenience
__all__ = ["Event", "EventBus", "EventType", "get_event_bus"]


class EventBus:
    """Singleton pub/sub event bus.

    Subscribers register async callbacks. When emit() is called, every
    subscriber whose filter matches receives the event.

    Thread-safe for use across asyncio tasks.
    """

    def __init__(self):
        # List of subscriber entries.
        # Async entry: (filters: set[str], workspace_id: str | None, callback: Coroutine)
        # Sync entry:  (filters: set[str], workspace_id: str | None, callback, "_sync" marker)
        self._subscribers: list[tuple[Any, ...]] = []
        self._lock = asyncio.Lock()
        self._ws_broadcast: Callable | None = None

    def set_ws_broadcast(self, func: Callable):
        """Set a callback for WebSocket broadcasting of events."""
        self._ws_broadcast = func

    async def subscribe(
        self,
        callback: Callable[[Event], Coroutine[Any, Any, None]],
        event_types: set[str] | None = None,
        workspace_id: str | None = None,
    ):
        """Register an async callback.

        Args:
            callback: async function invoked with Event on match.
            event_types: if set, only these event types trigger the callback.
                         If None, all events trigger the callback.
            workspace_id: if set, only events from this workspace trigger.
                         If None, events from all workspaces trigger.
        """
        filters = set(event_types) if event_types else set()
        async with self._lock:
            self._subscribers.append((filters, workspace_id, callback))

    def subscribe_sync(
        self,
        callback: Callable[[Event], None],
        event_types: set[str] | None = None,
        workspace_id: str | None = None,
    ):
        """Register a synchronous callback (wrapped in asyncio)."""
        async def _wrapper(event: Event):
            callback(event)
        # Store sync flag in a unique marker
        self._subscribers.append((set(event_types) if event_types else set(), workspace_id, _wrapper, "_sync"))

    async def unsubscribe(self, callback: Callable[[Event], Coroutine[Any, Any, None]]):
        async with self._lock:
            self._subscribers = [
                (filters, ws_id, cb, *rest)
                for (filters, ws_id, cb, *rest) in self._subscribers
                if cb != callback
            ]

    async def emit(self, event: Event):
        """Publish an event to all matching subscribers."""
        # WebSocket broadcast if configured
        if self._ws_broadcast:
            try:
                await self._ws_broadcast(event)
            except Exception:
                pass

        async with self._lock:
            subscribers = list(self._subscribers)

        for sub in subscribers:
            filters, ws_id, cb, *rest = sub
            sync_marker = rest[0] if rest else None

            # Check workspace filter
            if ws_id is not None and event.workspace_id != ws_id:
                continue

            # Check event type filter
            if filters and event.event_type.value not in filters:
                continue

            try:
                if sync_marker == "_sync":
                    cb(event)
                else:
                    await cb(event)
            except Exception:
                _log.exception("Event subscriber raised: %s", cb)

    def emit_sync(self, event: Event):
        """Synchronous emit for non-async contexts (creates a new event loop if needed)."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.emit(event))
        except RuntimeError:
            # No running loop — create a temporary one
            asyncio.run(self.emit(event))
