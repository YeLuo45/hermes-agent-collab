"""
Real-time collaborative editing sessions with WebSocket support and Operational Transformation.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_log = __import__("logging").getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Participant:
    user_id: str
    name: str = ""
    color: str = "#3B82F6"
    cursor_position: dict[str, Any] = field(default_factory=dict)
    selection: dict[str, Any] | None = None
    joined_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_active: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class Operation:
    op_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = ""
    version: int = 0
    op_type: str = "replace"  # insert | delete | replace
    path: str = ""  # JSON path, e.g. "tasks/0/title"
    value: Any = None
    old_value: Any = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "op_id": self.op_id,
            "user_id": self.user_id,
            "version": self.version,
            "op_type": self.op_type,
            "path": self.path,
            "value": self.value,
            "old_value": self.old_value,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Operation:
        return cls(
            op_id=d.get("op_id", str(uuid.uuid4())),
            user_id=d.get("user_id", ""),
            version=d.get("version", 0),
            op_type=d.get("op_type", "replace"),
            path=d.get("path", ""),
            value=d.get("value"),
            old_value=d.get("old_value"),
            timestamp=d.get("timestamp", datetime.now(timezone.utc).isoformat()),
        )


# Default cursor colors for participants
CURSOR_COLORS = [
    "#EF4444", "#F97316", "#EAB308", "#22C55E",
    "#06B6D4", "#3B82F6", "#8B5CF6", "#EC4899",
]


@dataclass
class CollabEditSession:
    """A real-time collaborative editing session for a resource."""
    session_id: str
    resource_type: str  # "task" | "strategy" | "workflow"
    resource_id: str
    version: int = 0
    participants: dict[str, Participant] = field(default_factory=dict)
    operations: list[Operation] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_activity: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    is_closed: bool = False
    _color_idx: int = 0

    def join(self, user_id: str, name: str = "") -> Participant:
        """Join the session. Returns the assigned Participant."""
        if user_id in self.participants:
            p = self.participants[user_id]
            p.last_active = datetime.now(timezone.utc).isoformat()
            return p

        color = CURSOR_COLORS[self._color_idx % len(CURSOR_COLORS)]
        self._color_idx += 1

        participant = Participant(
            user_id=user_id,
            name=name or user_id,
            color=color,
        )
        self.participants[user_id] = participant
        self.touch()
        _log.info("User %s joined session %s", user_id, self.session_id)
        return participant

    def leave(self, user_id: str) -> bool:
        """Remove a participant. Returns True if they were in the session."""
        if user_id in self.participants:
            del self.participants[user_id]
            self.touch()
            _log.info("User %s left session %s", user_id, self.session_id)
            return True
        return False

    def apply_operation(self, op: Operation) -> tuple[Operation, list[str]]:
        """
        Apply an operation to this session.
        Returns (transformed_op, affected_user_ids) for broadcast.
        """
        op.version = self.version + 1
        op.timestamp = datetime.now(timezone.utc).isoformat()
        self.operations.append(op)
        self.version += 1
        self.touch()

        # Determine affected users (all except op author)
        affected = [
            uid for uid in self.participants
            if uid != op.user_id
        ]
        return op, affected

    def get_state(self) -> dict[str, Any]:
        """Get full session state for sync."""
        return {
            "session_id": self.session_id,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "version": self.version,
            "participants": {
                uid: {
                    "user_id": p.user_id,
                    "name": p.name,
                    "color": p.color,
                    "cursor_position": p.cursor_position,
                    "selection": p.selection,
                    "joined_at": p.joined_at,
                    "last_active": p.last_active,
                }
                for uid, p in self.participants.items()
            },
            "is_closed": self.is_closed,
            "created_at": self.created_at,
        }

    def get_operations_since(self, from_version: int) -> list[Operation]:
        """Get operations after a given version for client sync."""
        return [op for op in self.operations if op.version > from_version]

    def update_cursor(self, user_id: str, cursor_position: dict[str, Any],
                      selection: dict[str, Any] | None = None) -> bool:
        """Update a participant's cursor position."""
        if user_id not in self.participants:
            return False
        p = self.participants[user_id]
        p.cursor_position = cursor_position
        p.selection = selection
        p.last_active = datetime.now(timezone.utc).isoformat()
        return True

    def touch(self) -> None:
        self.last_activity = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "version": self.version,
            "participants": {
                uid: {
                    "user_id": p.user_id,
                    "name": p.name,
                    "color": p.color,
                    "cursor_position": p.cursor_position,
                    "selection": p.selection,
                    "joined_at": p.joined_at,
                    "last_active": p.last_active,
                }
                for uid, p in self.participants.items()
            },
            "operations": [op.to_dict() for op in self.operations[-100:]],  # last 100
            "created_at": self.created_at,
            "last_activity": self.last_activity,
            "is_closed": self.is_closed,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CollabEditSession:
        participants = {}
        for uid, pd in d.get("participants", {}).items():
            participants[uid] = Participant(
                user_id=pd["user_id"],
                name=pd.get("name", ""),
                color=pd.get("color", "#3B82F6"),
                cursor_position=pd.get("cursor_position", {}),
                selection=pd.get("selection"),
                joined_at=pd.get("joined_at", datetime.now(timezone.utc).isoformat()),
                last_active=pd.get("last_active", datetime.now(timezone.utc).isoformat()),
            )
        operations = [Operation.from_dict(op) for op in d.get("operations", [])]
        return cls(
            session_id=d["session_id"],
            resource_type=d["resource_type"],
            resource_id=d["resource_id"],
            version=d.get("version", 0),
            participants=participants,
            operations=operations,
            created_at=d.get("created_at", datetime.now(timezone.utc).isoformat()),
            last_activity=d.get("last_activity", datetime.now(timezone.utc).isoformat()),
            is_closed=d.get("is_closed", False),
        )


# ---------------------------------------------------------------------------
# Session Manager
# ---------------------------------------------------------------------------

class CollabEditSessionManager:
    """
    Manages all active collaborative editing sessions.
    Sessions are stored in ~/.hermes/collab/sessions/
    """

    SESSION_TIMEOUT_SECONDS = 30 * 60  # 30 minutes

    def __init__(self, sessions_dir: str | Path | None = None):
        self._dir = Path(sessions_dir or Path("~/.hermes/collab/sessions").expanduser())
        self._dir.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, CollabEditSession] = {}
        self._lock = threading.Lock()
        self._cleanup_thread: threading.Thread | None = None
        self._start_cleanup()

    def _session_path(self, session_id: str) -> Path:
        return self._dir / f"{session_id}.json"

    def _start_cleanup(self) -> None:
        def run():
            while True:
                import time
                time.sleep(300)  # every 5 min
                self._cleanup_stale()

        t = threading.Thread(target=run, daemon=True)
        t.start()
        self._cleanup_thread = t

    def _cleanup_stale(self) -> None:
        from datetime import datetime, timedelta, timezone as tz
        cutoff = datetime.now(tz.utc) - timedelta(seconds=self.SESSION_TIMEOUT_SECONDS)
        with self._lock:
            stale = [
                sid for sid, sess in self._sessions.items()
                if datetime.fromisoformat(sess.last_activity) < cutoff
            ]
            for sid in stale:
                self._save_session(self._sessions[sid])
                del self._sessions[sid]
                _log.info("Session %s timed out", sid)

    def _save_session(self, session: CollabEditSession) -> None:
        path = self._session_path(session.session_id)
        with open(path, "w") as f:
            json.dump(session.to_dict(), f, indent=2)

    def _load_session(self, session_id: str) -> CollabEditSession | None:
        path = self._session_path(session_id)
        if not path.exists():
            return None
        try:
            with open(path) as f:
                return CollabEditSession.from_dict(json.load(f))
        except (json.JSONDecodeError, KeyError, OSError):
            return None

    def get_or_create(
        self,
        resource_type: str,
        resource_id: str,
        user_id: str,
        name: str = "",
    ) -> CollabEditSession:
        """
        Get existing session for resource or create new one.
        Creates a new session and auto-joins the creator.
        """
        # Search existing sessions for this resource
        key = f"{resource_type}:{resource_id}"
        with self._lock:
            for sid, sess in self._sessions.items():
                if not sess.is_closed and sess.resource_type == resource_type and sess.resource_id == resource_id:
                    sess.join(user_id, name)
                    self._save_session(sess)
                    return sess

            # Load from disk
            for path in self._dir.glob("*.json"):
                try:
                    sess = CollabEditSession.from_dict(json.loads(path.read_text()))
                    if (not sess.is_closed and sess.resource_type == resource_type
                            and sess.resource_id == resource_id):
                        self._sessions[sess.session_id] = sess
                        sess.join(user_id, name)
                        self._save_session(sess)
                        return sess
                except (json.JSONDecodeError, KeyError, OSError):
                    pass

            # Create new session
            session_id = str(uuid.uuid4())
            session = CollabEditSession(
                session_id=session_id,
                resource_type=resource_type,
                resource_id=resource_id,
            )
            session.join(user_id, name)
            self._sessions[session_id] = session
            self._save_session(session)
            _log.info("Created new collab session %s for %s/%s", session_id, resource_type, resource_id)
            return session

    def get(self, session_id: str) -> CollabEditSession | None:
        """Get a session by ID."""
        with self._lock:
            if session_id in self._sessions:
                return self._sessions[session_id]
            # Try disk
            sess = self._load_session(session_id)
            if sess:
                self._sessions[session_id] = sess
            return sess

    def apply_operation(self, session_id: str, op: Operation) -> CollabEditSession | None:
        """Apply an operation to a session."""
        session = self.get(session_id)
        if session is None or session.is_closed:
            return None
        session.apply_operation(op)
        self._save_session(session)
        return session

    def leave(self, session_id: str, user_id: str) -> bool:
        """Remove user from session. Returns True if session still has participants."""
        session = self.get(session_id)
        if session is None:
            return False
        session.leave(user_id)
        if not session.participants:
            session.is_closed = True
        self._save_session(session)
        return len(session.participants) > 0

    def list_active(self) -> list[dict[str, Any]]:
        """List all active sessions."""
        with self._lock:
            return [
                {
                    "session_id": s.session_id,
                    "resource_type": s.resource_type,
                    "resource_id": s.resource_id,
                    "participant_count": len(s.participants),
                    "version": s.version,
                    "last_activity": s.last_activity,
                }
                for s in self._sessions.values()
                if not s.is_closed
            ]

    def update_cursor(
        self,
        session_id: str,
        user_id: str,
        cursor_position: dict[str, Any],
        selection: dict[str, Any] | None = None,
    ) -> bool:
        """Update cursor position."""
        session = self.get(session_id)
        if session is None:
            return False
        ok = session.update_cursor(user_id, cursor_position, selection)
        if ok:
            self._save_session(session)
        return ok

    def close_session(self, session_id: str) -> bool:
        """Manually close a session."""
        session = self.get(session_id)
        if session is None:
            return False
        session.is_closed = True
        self._save_session(session)
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
        return True
