"""Agent registry for the collaboration module.

Manages Agent profiles within a workspace: registration, status updates,
and heartbeat tracking for online/offline detection.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from collaboration.events import Event, EventType, get_event_bus
from collaboration.models import Agent, AgentRole, AgentStatus
from collaboration.storage import HERMES_HOME, JsonFileStore

_log = logging.getLogger(__name__)

# Heartbeat timeout in seconds — an agent is considered offline if no heartbeat
# is received within this window.
HEARTBEAT_TIMEOUT = 30


class AgentRegistry:
    """Manages Agent profiles in a workspace.

    All mutating methods emit events via the collaboration event bus.
    """

    def __init__(self, workspace_id: str = None, base_path: str = None):
        if base_path:
            self._base_path = Path(base_path).expanduser()
        else:
            self._base_path = None
        self.workspace_id = workspace_id
        self._ensure_ws_files()
        self._store = JsonFileStore.for_agents(self._ws_root / workspace_id)
        self._bus = get_event_bus()
        self._heartbeats: dict[str, float] = {}  # agent_id -> last beat time

    @property
    def _ws_root(self) -> Path:
        return (self._base_path or HERMES_HOME) / "workspaces"

    def _ensure_ws_files(self) -> None:
        """Ensure workspace directory and JSON files exist."""
        if self.workspace_id is None:
            return
        ws_path = self._ws_root / self.workspace_id
        ws_path.mkdir(parents=True, exist_ok=True)
        for filename in ["tasks.json", "agents.json", "skills.json", "workspace.json", "config.json"]:
            fp = ws_path / filename
            if not fp.exists():
                fp.write_text("[]" if filename != "config.json" else "{}")

    # ─── CLI compatibility aliases ───────────────────────────────────────────

    def register_agent(self, name: str, role: str, description: str = "", skills: list = None, workspace_id: str = None) -> Agent:
        """Register agent (CLI compatibility)."""
        return self.register(name=name, role=role, capabilities=skills or [])

    def list_agents(self, workspace_id: str = None, status: str = None, role: str = None) -> list[Agent]:
        """List agents (CLI compatibility)."""
        agents = self.list()
        if status:
            agents = [a for a in agents if a.status.value == status]
        if role:
            agents = [a for a in agents if a.role.value == role]
        return agents

    def get_agent(self, agent_id: str) -> Agent | None:
        """Get agent (CLI compatibility)."""
        return self.get(agent_id)

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
        return agent

    def get(self, agent_id: str) -> Agent | None:
        return self._store.get(agent_id)

    def list(self) -> list[Agent]:
        return self._store.list()

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
