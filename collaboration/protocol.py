"""generic-agent-inspired Multi-Agent Collaboration Protocol.

Provides structured messaging, task distribution, capability matching,
and session management between agents.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .models import (
        AgentMessage, AgentSession, TaskDistribution, CapabilityMatchResult,
        MessageType, MessageStatus, SessionStatus, DelegationPolicy,
        DELEGATION_BROADCAST, DELEGATION_CAPABILITY_MATCH,
    )
    from .plugin_system import HookEvent, emit_hook
    from .storage import ensure_workspace_files, for_messages, for_sessions
    from .agent_registry import AgentRegistry
except ImportError:
    from collaboration.models import (
        AgentMessage, AgentSession, TaskDistribution, CapabilityMatchResult,
        MessageType, MessageStatus, SessionStatus, DelegationPolicy,
        DELEGATION_BROADCAST, DELEGATION_CAPABILITY_MATCH,
    )
    from collaboration.plugin_system import HookEvent, emit_hook
    from collaboration.storage import ensure_workspace_files, for_messages, for_sessions
    from collaboration.agent_registry import AgentRegistry


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# In-memory index for fast pending-message lookup (backed by SQLite via storage)
_pending_index: dict[str, list[str]] = defaultdict(list)  # agent_id -> [msg_id, ...]
_pending_lock = threading.Lock()


class MultiAgentProtocol:
    """Multi-Agent Collaboration Protocol.

    Handles structured agent-to-agent messaging, task distribution with
    delegation policies, capability matching, and session management.
    """

    def __init__(self, workspace_id: str):
        self.workspace_id = workspace_id
        ws_path = ensure_workspace_files(workspace_id)
        self._msg_store = for_messages(ws_path)
        self._session_store = for_sessions(ws_path)
        self._agent_registry = AgentRegistry(workspace_id)
        self._distributions: dict[str, TaskDistribution] = {}
        self._lock = threading.RLock()

    # ─── Messaging ──────────────────────────────────────────────────────────────

    def send_message(
        self,
        sender_id: str,
        receiver_id: str | None,
        msg_type: MessageType | str,
        payload: dict[str, Any],
        session_id: str | None = None,
        correlation_id: str | None = None,
        ttl_seconds: int = 300,
    ) -> AgentMessage:
        """Send a message from one agent to another (or broadcast).

        Returns the created AgentMessage.
        Emits HookEvent.MESSAGE_SENT.
        """
        msg_id = f"msg_{uuid.uuid4().hex[:12]}"
        if isinstance(msg_type, MessageType):
            msg_type_str = msg_type
        else:
            try:
                msg_type_str = MessageType(msg_type)
            except ValueError:
                msg_type_str = MessageType.REQUEST_TASK

        msg = AgentMessage(
            msg_id=msg_id,
            sender_id=sender_id,
            receiver_id=receiver_id,
            msg_type=msg_type_str,
            payload=payload,
            session_id=session_id,
            correlation_id=correlation_id,
            timestamp=_now_iso(),
            ttl_seconds=ttl_seconds,
            status=MessageStatus.PENDING,
        )

        self._msg_store.upsert(msg.to_dict())

        # Update pending index
        if receiver_id:
            with _pending_lock:
                _pending_index[receiver_id].append(msg_id)
        elif receiver_id is None:
            # Broadcast: add to all agents' pending
            agents = self._agent_registry.list()
            with _pending_lock:
                for agent in agents:
                    _pending_index[agent.agent_id].append(msg_id)

        # Emit hook
        emit_hook(HookEvent.MESSAGE_SENT, {
            "msg_id": msg_id,
            "sender_id": sender_id,
            "receiver_id": receiver_id,
            "msg_type": msg_type_str.value if isinstance(msg_type_str, MessageType) else msg_type_str,
            "session_id": session_id,
            "workspace_id": self.workspace_id,
        }, workspace_id=self.workspace_id)

        return msg

    def acknowledge_message(self, msg_id: str, agent_id: str) -> bool:
        """Mark a message as acknowledged by the receiver."""
        data = self._msg_store.get(msg_id)
        if not data:
            return False

        msg = AgentMessage.from_dict(data)
        if msg.receiver_id != agent_id:
            return False

        msg.status = MessageStatus.ACKed
        self._msg_store.upsert(msg.to_dict())

        # Remove from pending index
        with _pending_lock:
            if agent_id in _pending_index and msg_id in _pending_index[agent_id]:
                _pending_index[agent_id].remove(msg_id)

        emit_hook(HookEvent.MESSAGE_DELIVERED, {
            "msg_id": msg_id,
            "receiver_id": agent_id,
            "workspace_id": self.workspace_id,
        }, workspace_id=self.workspace_id)

        return True

    def get_pending_messages(self, agent_id: str) -> list[AgentMessage]:
        """Get all pending (undelivered) messages for an agent."""
        with _pending_lock:
            msg_ids = list(_pending_index.get(agent_id, []))

        results = []
        expired_ids = []

        for msg_id in msg_ids:
            data = self._msg_store.get(msg_id)
            if not data:
                expired_ids.append(msg_id)
                continue

            msg = AgentMessage.from_dict(data)

            # Check TTL
            try:
                created_at_ts = datetime.fromisoformat(msg.timestamp.replace("Z", "+00:00")).timestamp()
            except (ValueError, AttributeError):
                created_at_ts = 0
            if time.time() - created_at_ts > msg.ttl_seconds:
                expired_ids.append(msg_id)
                msg.status = MessageStatus.EXPIRED
                self._msg_store.upsert(msg.to_dict())
                continue

            if msg.status == MessageStatus.PENDING:
                results.append(msg)
            else:
                expired_ids.append(msg_id)

        # Cleanup expired from index
        with _pending_lock:
            for eid in expired_ids:
                if agent_id in _pending_index and eid in _pending_index[agent_id]:
                    _pending_index[agent_id].remove(eid)

        return results

    # ─── Sessions ─────────────────────────────────────────────────────────────

    def create_session(
        self,
        participants: list[str],
        context: dict[str, Any] | None = None,
    ) -> AgentSession:
        """Create a new collaborative session between agents."""
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        session = AgentSession(
            session_id=session_id,
            participants=participants,
            context=context or {},
            messages=[],
            created_at=_now_iso(),
            updated_at=_now_iso(),
            status=SessionStatus.ACTIVE,
        )

        self._session_store.upsert(session.to_dict())

        emit_hook(HookEvent.SESSION_CREATED, {
            "session_id": session_id,
            "participants": participants,
            "workspace_id": self.workspace_id,
        }, workspace_id=self.workspace_id)

        return session

    def get_session(self, session_id: str) -> AgentSession | None:
        """Get session by ID."""
        data = self._session_store.get(session_id)
        if not data:
            return None
        return AgentSession.from_dict(data)

    def end_session(self, session_id: str) -> bool:
        """End a session."""
        session = self.get_session(session_id)
        if not session:
            return False

        session.status = SessionStatus.ENDED
        session.updated_at = _now_iso()
        self._session_store.upsert(session.to_dict())

        emit_hook(HookEvent.SESSION_ENDED, {
            "session_id": session_id,
            "workspace_id": self.workspace_id,
        }, workspace_id=self.workspace_id)

        return True

    def list_sessions(self, status: SessionStatus | None = None) -> list[AgentSession]:
        """List all sessions, optionally filtered by status."""
        sessions = self._session_store.list()
        result = []
        for s in sessions:
            sess = AgentSession.from_dict(s) if isinstance(s, dict) else s
            if status is None or sess.status == status:
                result.append(sess)
        return result

    # ─── Task Distribution ─────────────────────────────────────────────────────

    def distribute_task(
        self,
        task_id: str,
        description: str,
        policy: DelegationPolicy | None = None,
        required_capabilities: list[str] | None = None,
    ) -> TaskDistribution:
        """Distribute a task to agents based on a delegation policy.

        policy types:
          - "broadcast": send to all available agents
          - "capability_match": match agents by required_capabilities
          - "指定": use explicitly provided candidate list
        """
        policy = policy or DELEGATION_CAPABILITY_MATCH
        distribution_id = f"dist_{uuid.uuid4().hex[:12]}"

        # Determine candidates
        if policy.type == "broadcast":
            agents = self._agent_registry.list()
            candidates = [a.agent_id for a in agents]
        elif policy.type == "capability_match":
            match_result = self.match_capabilities(
                query=description,
                required_capabilities=required_capabilities or [],
                min_confidence=policy.min_confidence,
            )
            candidates = [agent_id for agent_id, _ in match_result.matched_agents]
        else:
            # "指定" — candidates must be set externally via assign_to_agent
            candidates = []

        # Create distribution record
        dist = TaskDistribution(
            distribution_id=distribution_id,
            task_id=task_id,
            delegation_policy=policy,
            candidates=candidates,
            assigned_agents=[],
            created_at=_now_iso(),
            status="pending",
        )

        self._distributions[distribution_id] = dist

        # Emit hook
        emit_hook(HookEvent.TASK_DISTRIBUTED, {
            "distribution_id": distribution_id,
            "task_id": task_id,
            "policy_type": policy.type,
            "candidates": candidates,
            "workspace_id": self.workspace_id,
        }, workspace_id=self.workspace_id)

        return dist

    def assign_to_agent(
        self,
        distribution_id: str,
        agent_id: str,
    ) -> bool:
        """Assign a distributed task to a specific agent."""
        if distribution_id not in self._distributions:
            return False

        dist = self._distributions[distribution_id]
        if agent_id not in dist.candidates and dist.delegation_policy.type != "指定":
            return False

        if agent_id not in dist.assigned_agents:
            dist.assigned_agents.append(agent_id)
            dist.status = "assigned"

        emit_hook(HookEvent.TASK_ASSIGNED, {
            "distribution_id": distribution_id,
            "task_id": dist.task_id,
            "agent_id": agent_id,
            "workspace_id": self.workspace_id,
        }, workspace_id=self.workspace_id)

        return True

    def get_distribution(self, distribution_id: str) -> TaskDistribution | None:
        """Get distribution by ID."""
        return self._distributions.get(distribution_id)

    # ─── Capability Matching ──────────────────────────────────────────────────

    def match_capabilities(
        self,
        query: str,
        required_capabilities: list[str],
        min_confidence: float = 0.5,
    ) -> CapabilityMatchResult:
        """Match agents by their registered capabilities.

        Uses keyword overlap between query + required_capabilities and
        each agent's registered capabilities list.
        Returns matched agents sorted by confidence score.
        """
        agents = self._agent_registry.list()
        query_lower = query.lower()
        scored: list[tuple[str, float]] = []

        for agent in agents:
            score = 0.0
            agent_caps = [c.lower() for c in agent.capabilities]

            # Exact keyword matches
            for cap in required_capabilities:
                cap_lower = cap.lower()
                if cap_lower in agent_caps:
                    score += 0.4
                elif any(cap_lower in ac or ac in cap_lower for ac in agent_caps):
                    score += 0.2

            # Query keyword matches
            for cap in agent_caps:
                if cap in query_lower:
                    score += 0.3

            if score >= min_confidence:
                scored.append((agent.agent_id, round(score, 2)))

        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)

        best = scored[0][0] if scored else None

        result = CapabilityMatchResult(
            query=query,
            matched_agents=scored,
            best_candidate=best,
            match_method="capability_match",
        )

        emit_hook(HookEvent.CAPABILITY_MATCHED, {
            "query": query,
            "matched_count": len(scored),
            "best_candidate": best,
            "workspace_id": self.workspace_id,
        }, workspace_id=self.workspace_id)

        return result

    # ─── Timeout Handling ─────────────────────────────────────────────────────

    def check_timeouts(self) -> list[AgentMessage]:
        """Return all messages that have exceeded their TTL.

        Messages are marked as EXPIRED in storage.
        """
        all_msgs = self._msg_store.list()
        expired = []

        for msg_data in all_msgs:
            if isinstance(msg_data, str):
                continue
            msg = AgentMessage.from_dict(msg_data) if isinstance(msg_data, dict) else msg_data
            if msg.status != MessageStatus.PENDING:
                continue

            try:
                created_ts = datetime.fromisoformat(msg.timestamp.replace("Z", "+00:00")).timestamp()
            except (ValueError, AttributeError):
                created_ts = 0
            if time.time() - created_ts > msg.ttl_seconds:
                msg.status = MessageStatus.EXPIRED
                self._msg_store.upsert(msg.to_dict())
                expired.append(msg)

                # Remove from pending index
                if msg.receiver_id:
                    with _pending_lock:
                        if msg.receiver_id in _pending_index and msg.msg_id in _pending_index[msg.receiver_id]:
                            _pending_index[msg.receiver_id].remove(msg.msg_id)

        return expired

    # ─── Broadcast Helpers ────────────────────────────────────────────────────

    def broadcast_state_sync(
        self,
        sender_id: str,
        state: dict[str, Any],
    ) -> list[AgentMessage]:
        """Broadcast a state sync message to all agents."""
        msg = self.send_message(
            sender_id=sender_id,
            receiver_id=None,  # broadcast
            msg_type=MessageType.STATE_SYNC,
            payload={"state": state},
        )
        return [msg]

    def send_heartbeat(self, agent_id: str) -> AgentMessage:
        """Send a heartbeat from an agent."""
        return self.send_message(
            sender_id=agent_id,
            receiver_id=None,
            msg_type=MessageType.HEARTBEAT,
            payload={},
            ttl_seconds=30,
        )