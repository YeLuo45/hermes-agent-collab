"""Prometheus Metrics Plugin for hermes-agent-collab.

Bridges lifecycle hook events to Prometheus metrics.
Subscribes to task/agent/hook events and records corresponding metrics.
"""
from __future__ import annotations

from typing import Any

from collaboration.models import HookEvent, Plugin
from collaboration.metrics import MetricsRegistry


class MetricsPlugin(Plugin):
    """Built-in plugin that bridges hook events to Prometheus metrics.

    Handles: task created/completed/failed, agent registered/status_changed,
    hook emitted/failed, and API request events.
    """

    def __init__(self):
        super().__init__(
            plugin_id="builtin:metrics",
            name="Prometheus Metrics",
            description="Exposes hermes-agent-collab metrics as Prometheus /metrics endpoint",
            version="1.0.0",
            enabled=True,
            hook_handlers={
                HookEvent.TASK_CREATED: ["_on_task_created"],
                HookEvent.TASK_COMPLETED: ["_on_task_completed"],
                HookEvent.TASK_FAILED: ["_on_task_failed"],
                HookEvent.TASK_STATUS_CHANGED: ["_on_task_status_changed"],
                HookEvent.AGENT_REGISTERED: ["_on_agent_registered"],
                HookEvent.AGENT_STATUS_CHANGED: ["_on_agent_status_changed"],
                HookEvent.HOOK_EMITTED: ["_on_hook_emitted"],
                HookEvent.HOOK_FAILED: ["_on_hook_failed"],
            },
        )
        self._metrics = MetricsRegistry.get_instance()
        self._metrics.emit_metrics()  # ensure all metrics registered

    # ─── Task handlers ────────────────────────────────────────────────────────

    def _on_task_created(self, payload: dict[str, Any]) -> None:
        complexity = str(payload.get("complexity", "normal"))
        self._metrics.task_created(complexity)

    def _on_task_completed(self, payload: dict[str, Any]) -> None:
        complexity = str(payload.get("complexity", "normal"))
        duration = payload.get("duration")
        self._metrics.task_completed(complexity, duration)

    def _on_task_failed(self, payload: dict[str, Any]) -> None:
        complexity = str(payload.get("complexity", "normal"))
        self._metrics.task_failed(complexity)

    def _on_task_status_changed(self, payload: dict[str, Any]) -> None:
        status = str(payload.get("status", ""))
        delta = int(payload.get("delta", 1))
        if status:
            self._metrics.task_in_flight(status, delta)

    # ─── Agent handlers ───────────────────────────────────────────────────────

    def _on_agent_registered(self, payload: dict[str, Any]) -> None:
        role = str(payload.get("role", "unknown"))
        self._metrics.agent_registered(role)

    def _on_agent_status_changed(self, payload: dict[str, Any]) -> None:
        role = str(payload.get("role", "unknown"))
        status = str(payload.get("status", "unknown"))
        self._metrics.agent_status_change(role, status)

    # ─── Hook handlers ───────────────────────────────────────────────────────

    def _on_hook_emitted(self, payload: dict[str, Any]) -> None:
        event = str(payload.get("event", ""))
        duration = payload.get("duration")
        if event:
            self._metrics.hook_emitted(event)
        if duration is not None:
            if event:
                self._metrics.hook_duration(event, duration)

    def _on_hook_failed(self, payload: dict[str, Any]) -> None:
        event = str(payload.get("event", ""))
        if event:
            self._metrics.hook_failed(event)
