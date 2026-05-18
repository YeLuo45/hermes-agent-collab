"""Agent registry for the collaboration module.

Manages Agent profiles within a workspace: registration, status updates,
and heartbeat tracking for online/offline detection.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Tuple

from collaboration.events import Event, EventType, get_event_bus
from collaboration.models import Agent, AgentRole, AgentStatus
from collaboration.plugin_system import HookEvent, emit_hook
from collaboration.storage import JsonFileStore, ensure_workspace_files

_log = logging.getLogger(__name__)

# Heartbeat timeout in seconds — an agent is considered offline if no heartbeat
# is received within this window.
HEARTBEAT_TIMEOUT = 30


class AgentRegistry:
    """Manages Agent profiles in a workspace.

    All mutating methods emit events via the collaboration event bus.
    """

    def __init__(self, workspace_id: str):
        self.workspace_id = workspace_id
        ws_path = ensure_workspace_files(workspace_id)
        self._store = JsonFileStore.for_agents(ws_path)
        self._bus = get_event_bus()
        self._heartbeats: dict[str, float] = {}  # agent_id -> last beat time

    # ─── CRUD ─────────────────────────────────────────────────────────────────

    def register(self, name: str, role: AgentRole | str, capabilities: list[str] | None = None, avatar: str | None = None) -> Agent:
        """Register a new agent in the workspace."""
        if isinstance(role, str):
            role = AgentRole(role)
        agent = Agent.new(name=name, role=role, capabilities=capabilities or [])
        agent.avatar = avatar
        agent.status = AgentStatus.IDLE
        agent = self._store.upsert(agent)
        self._bus.emit_sync(Event(
            EventType.AGENT_REGISTERED,
            workspace_id=self.workspace_id,
            payload=agent.to_dict(),
        ))
        # Plugin hook: agent.registered
        emit_hook(HookEvent.AGENT_REGISTERED, {
            "agent_id": agent.agent_id,
            "name": agent.name,
            "role": agent.role.value if hasattr(agent.role, "value") else str(agent.role),
            "capabilities": agent.capabilities,
            "workspace_id": self.workspace_id,
        }, workspace_id=self.workspace_id)
        return agent

    def get(self, agent_id: str) -> Agent | None:
        return self._store.get(agent_id)

    def list(self) -> list[Agent]:
        """List all registered agents."""
        return self._store.list()

    def find_by_capability(
        self,
        capability: str,
        min_confidence: float = 0.0,
    ) -> list[tuple[Agent, float]]:
        """Find agents that have a given capability.

        Returns list of (agent, confidence_score) sorted by confidence descending.
        Confidence is 1.0 for exact match, 0.5 for partial match.
        """
        cap_lower = capability.lower()
        results: list[tuple[Agent, float]] = []

        for agent in self._store.list():
            if not agent.capabilities:
                continue

            agent_caps_lower = [c.lower() for c in agent.capabilities]

            if cap_lower in agent_caps_lower:
                results.append((agent, 1.0))
            elif any(cap_lower in ac or ac in cap_lower for ac in agent_caps_lower):
                results.append((agent, 0.5))

        results.sort(key=lambda x: x[1], reverse=True)
        return [(a, s) for a, s in results if s >= min_confidence]

    def update(self, agent_id: str, **fields) -> Agent:
        """Update mutable agent fields."""
        agent = self._store.get(agent_id)
        if not agent:
            raise KeyError(f"Agent {agent_id} not found")
        for key, value in fields.items():
            if hasattr(agent, key) and key not in ("agent_id",):
                setattr(agent, key, value)
        agent.updated_at = datetime.now(timezone.utc).isoformat()
        agent = self._store.upsert(agent)
        return agent

    def unregister(self, agent_id: str) -> bool:
        """Remove an agent from the registry."""
        ok = self._store.delete(agent_id)
        if ok:
            self._bus.emit_sync(Event(
                EventType.AGENT_UNREGISTERED,
                workspace_id=self.workspace_id,
                payload={"agent_id": agent_id},
            ))
        return ok

    # ─── Status management ─────────────────────────────────────────────────────

    def set_status(self, agent_id: str, status: AgentStatus | str) -> Agent:
        """Update agent status (idle, working, blocked, offline)."""
        if isinstance(status, str):
            status = AgentStatus(status)
        agent = self._store.get(agent_id)
        if not agent:
            raise KeyError(f"Agent {agent_id} not found")
        agent.status = status
        agent.updated_at = datetime.now(timezone.utc).isoformat()
        agent = self._store.upsert(agent)
        self._bus.emit_sync(Event(
            EventType.AGENT_STATUS_CHANGED,
            workspace_id=self.workspace_id,
            payload=agent.to_dict(),
        ))
        return agent

    def heartbeat(self, agent_id: str) -> Agent:
        """Record a heartbeat for an agent, marking them online."""
        self._heartbeats[agent_id] = datetime.now(timezone.utc).timestamp()
        agent = self._store.get(agent_id)
        if agent and agent.status == AgentStatus.OFFLINE:
            return self.set_status(agent_id, AgentStatus.IDLE)
        return agent

    async def mark_stale_offline(self):
        """Mark agents with expired heartbeats as offline.

        Run this periodically (e.g., every HEARTBEAT_TIMEOUT seconds).
        """
        now = datetime.now(timezone.utc).timestamp()
        for agent in self.list():
            if agent.status != AgentStatus.OFFLINE:
                last_beat = self._heartbeats.get(agent.agent_id, 0)
                if now - last_beat > HEARTBEAT_TIMEOUT:
                    self.set_status(agent.agent_id, AgentStatus.OFFLINE)
