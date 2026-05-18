"""ruflo-inspired Hook/Plugin Architecture for hermes-agent-collab.

PluginRegistry: central registry for lifecycle hooks and plugins.
Supports global and workspace-scoped registries.
"""

from __future__ import annotations

import threading
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable

try:
    from .models import HookEvent, Plugin
except ImportError:
    from collaboration.models import HookEvent, Plugin

HookHandler = Callable[[dict[str, Any]], Any | None]

# Global registry (no workspace scope)
_global_registry: "PluginRegistry | None" = None
_global_lock = threading.Lock()

# Per-workspace registries
_workspace_registries: dict[str, PluginRegistry] = {}
_workspace_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_registry(workspace_id: str = None) -> "PluginRegistry":
    """Get global or workspace-scoped registry."""
    if workspace_id is None:
        with _global_lock:
            global _global_registry
            if _global_registry is None:
                _global_registry = PluginRegistry()
            return _global_registry
    else:
        with _workspace_lock:
            if workspace_id not in _workspace_registries:
                _workspace_registries[workspace_id] = PluginRegistry(workspace_id)
            return _workspace_registries[workspace_id]


def emit_hook(
    event: HookEvent,
    payload: dict[str, Any],
    workspace_id: str = None,
) -> list[Any]:
    """Convenience function to emit a hook event to the appropriate registry."""
    registry = get_registry(workspace_id)
    return registry.emit(event, payload)


class PluginRegistry:
    """Central registry for hooks and plugins.

    Plugins subscribe handlers to lifecycle events (HookEvent).
    When emit() is called, all registered handlers for that event fire in order.
    """

    def __init__(self, workspace_id: str = None):
        self._workspace_id = workspace_id
        # event -> list of (handler_id, plugin_id, handler_fn)
        self._handlers: dict[HookEvent, list[tuple[str, str, HookHandler]]] = defaultdict(list)
        self._plugins: dict[str, Plugin] = {}
        self._lock = threading.RLock()

    # ─── Plugin Management ───────────────────────────────────────────────────

    def register_plugin(self, plugin: Plugin) -> None:
        """Register a plugin and attach its handlers."""
        with self._lock:
            plugin.updated_at = _now_iso()
            if not plugin.created_at:
                plugin.created_at = _now_iso()
            self._plugins[plugin.plugin_id] = plugin

            # Attach handlers declared in hook_handlers
            # Note: actual handler functions must be registered separately via subscribe
            for event in plugin.hook_handlers:
                handler_ids = plugin.hook_handlers[event]
                for hid in handler_ids:
                    # Just record that this handler_id belongs to this plugin;
                    # the actual callable is registered via subscribe()
                    pass

    def unregister_plugin(self, plugin_id: str) -> list[HookEvent]:
        """Remove plugin and all its handlers. Returns list of affected event types."""
        removed_events = []
        with self._lock:
            if plugin_id not in self._plugins:
                return removed_events

            # Remove all handlers belonging to this plugin
            for event, handlers in list(self._handlers.items()):
                original_len = len(handlers)
                self._handlers[event] = [
                    (hid, pid, fn) for hid, pid, fn in handlers if pid != plugin_id
                ]
                if len(self._handlers[event]) < original_len:
                    removed_events.append(event)

            del self._plugins[plugin_id]
            return removed_events

    def list_plugins(self) -> list[Plugin]:
        """List all registered plugins."""
        with self._lock:
            return list(self._plugins.values())

    def get_plugin(self, plugin_id: str) -> Plugin | None:
        """Get plugin by ID."""
        with self._lock:
            return self._plugins.get(plugin_id)

    def enable_plugin(self, plugin_id: str) -> bool:
        """Enable a plugin."""
        with self._lock:
            plugin = self._plugins.get(plugin_id)
            if not plugin:
                return False
            plugin.enabled = True
            plugin.updated_at = _now_iso()
            return True

    def disable_plugin(self, plugin_id: str) -> bool:
        """Disable a plugin (handlers remain registered but skipped on emit)."""
        with self._lock:
            plugin = self._plugins.get(plugin_id)
            if not plugin:
                return False
            plugin.enabled = False
            plugin.updated_at = _now_iso()
            return True

    # ─── Subscription ────────────────────────────────────────────────────────

    def subscribe(
        self,
        event: HookEvent,
        handler: HookHandler,
        plugin_id: str = "system",
    ) -> str:
        """Subscribe a handler to an event. Returns handler_id."""
        handler_id = f"h_{uuid.uuid4().hex[:12]}"
        with self._lock:
            self._handlers[event].append((handler_id, plugin_id, handler))
        return handler_id

    def unsubscribe(self, event: HookEvent, handler_id: str) -> bool:
        """Remove a specific handler by ID. Returns True if found and removed."""
        with self._lock:
            handlers = self._handlers.get(event, [])
            for i, (hid, pid, fn) in enumerate(handlers):
                if hid == handler_id:
                    del handlers[i]
                    return True
            return False

    # ─── Emission ────────────────────────────────────────────────────────────

    def emit(self, event: HookEvent, payload: dict[str, Any]) -> list[Any]:
        """Fire all handlers for event. Returns list of non-None results."""
        results = []
        with self._lock:
            # Snapshot handlers under lock to avoid mutation during iteration
            handlers = list(self._handlers.get(event, []))
            plugins_snapshot = dict(self._plugins)

        for handler_id, plugin_id, handler_fn in handlers:
            plugin = plugins_snapshot.get(plugin_id)
            # Skip if plugin is disabled
            if plugin and not plugin.enabled:
                continue
            try:
                result = handler_fn(payload)
                if result is not None:
                    results.append(result)
            except Exception:
                # Swallow handler exceptions to avoid breaking other handlers
                pass

        return results

    # ─── Query ───────────────────────────────────────────────────────────────

    def get_subscribers(self, event: HookEvent) -> list[str]:
        """Return list of plugin IDs subscribed to this event."""
        with self._lock:
            return list({pid for _, pid, _ in self._handlers.get(event, [])})

    def hook_count(self) -> dict[HookEvent, int]:
        """Return count of handlers per event type."""
        with self._lock:
            return {e: len(hs) for e, hs in self._handlers.items()}


# ─── Built-in Plugins ────────────────────────────────────────────────────────


class TaskMetricsPlugin(Plugin):
    """Built-in plugin that tracks task completion metrics.

    Tracks: created, completed, failed counts and per-task durations.
    """

    def __init__(self):
        super().__init__(
            plugin_id="builtin:task_metrics",
            name="Task Metrics",
            description="Tracks task completion times and success rates",
            version="1.0.0",
            enabled=True,
            hook_handlers={
                HookEvent.TASK_CREATED: ["_on_task_created"],
                HookEvent.TASK_COMPLETED: ["_on_task_completed"],
                HookEvent.TASK_FAILED: ["_on_task_failed"],
            },
        )
        self._metrics = {
            "created": 0,
            "completed": 0,
            "failed": 0,
            "durations": [],  # list of duration floats in seconds
            "by_complexity": {"simple": 0, "normal": 0, "complex": 0},
        }

    def _on_task_created(self, payload: dict[str, Any]):
        self._metrics["created"] += 1
        complexity = payload.get("complexity", "normal")
        if complexity in self._metrics["by_complexity"]:
            self._metrics["by_complexity"][complexity] += 1

    def _on_task_completed(self, payload: dict[str, Any]):
        self._metrics["completed"] += 1
        if "duration" in payload:
            self._metrics["durations"].append(payload["duration"])

    def _on_task_failed(self, payload: dict[str, Any]):
        self._metrics["failed"] += 1

    def get_metrics(self) -> dict[str, Any]:
        """Return a copy of current metrics."""
        import copy
        return copy.deepcopy(self._metrics)


class AgentMetricsPlugin(Plugin):
    """Built-in plugin that tracks agent activity."""

    def __init__(self):
        super().__init__(
            plugin_id="builtin:agent_metrics",
            name="Agent Metrics",
            description="Tracks agent registration and status changes",
            version="1.0.0",
            enabled=True,
            hook_handlers={
                HookEvent.AGENT_REGISTERED: ["_on_agent_registered"],
                HookEvent.AGENT_STATUS_CHANGED: ["_on_agent_status_changed"],
            },
        )
        self._metrics = {
            "registered": 0,
            "status_changes": 0,
            "by_role": {},
        }

    def _on_agent_registered(self, payload: dict[str, Any]):
        self._metrics["registered"] += 1
        role = payload.get("role", "unknown")
        self._metrics["by_role"][role] = self._metrics["by_role"].get(role, 0) + 1

    def _on_agent_status_changed(self, payload: dict[str, Any]):
        self._metrics["status_changes"] += 1

    def get_metrics(self) -> dict[str, Any]:
        import copy
        return copy.deepcopy(self._metrics)