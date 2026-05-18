"""
Immutable append-only audit logger.
Records all significant operations in JSONL format for compliance and security auditing.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Actor:
    type: str           # "agent" | "user" | "system"
    id: str
    workspace_id: str = ""


@dataclass
class Target:
    type: str           # "task" | "agent" | "workspace" | "config" | "secret"
    id: str


@dataclass
class AuditEvent:
    event_id: str
    timestamp: str       # ISO8601
    actor: Actor
    action: str          # e.g. "task.created", "agent.registered"
    target: Target
    changes: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "actor": asdict(self.actor),
            "action": self.action,
            "target": asdict(self.target),
            "changes": self.changes,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Audit Logger
# ---------------------------------------------------------------------------

class AuditLogger:
    """
    Append-only audit log writer (JSONL format).

    Features:
    - Append-only (file opened in 'a' mode, no read/modify)
    - Per-workspace, per-day log files: audit-{workspace_id}-{YYYYMMDD}.jsonl
    - SHA-256 chain hash for tamper detection (optional)
    - Query by workspace, actor, action, time range

    Usage:
        logger = AuditLogger()
        event = AuditLogger.event(
            actor=Actor(type="agent", id="a1", workspace_id="ws1"),
            action="task.created",
            target=Target(type="task", id="t1"),
            changes={"before": {}, "after": {"status": "pending"}},
        )
        logger.log(event)
    """

    DEFAULT_LOG_DIR = Path("~/.hermes/audit").expanduser()
    MAX_FILE_SIZE_MB = 100
    DEFAULT_ROTATION = "daily"   # "daily" | "size" | "none"

    def __init__(
        self,
        log_dir: str | Path | None = None,
        rotation: str = DEFAULT_ROTATION,
        enable_hash_chain: bool = True,
    ):
        self._log_dir = Path(log_dir or self.DEFAULT_LOG_DIR)
        self._rotation = rotation
        self._enable_hash_chain = enable_hash_chain
        self._last_hash: dict[str, str] = {}  # workspace_id -> last hash
        self._lock = __import__("threading").Lock()
        self._log_dir.mkdir(parents=True, exist_ok=True)

    # ---- Event factory ----

    @staticmethod
    def event(
        actor: Actor,
        action: str,
        target: Target,
        changes: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEvent:
        return AuditEvent(
            event_id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc).isoformat(),
            actor=actor,
            action=action,
            target=target,
            changes=changes or {},
            metadata=metadata or {},
        )

    # ---- Path helpers ----

    def _log_path(self, workspace_id: str, date: str | None = None) -> Path:
        """Get log file path for workspace + date."""
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y%m%d")
        # Sanitize workspace_id for filesystem safety
        safe_ws = workspace_id.replace("/", "_").replace("\\", "_")
        return self._log_dir / f"audit-{safe_ws}-{date}.jsonl"

    def _current_date(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%d")

    # ---- Hash chain ----

    def _compute_hash(self, record: dict[str, Any], prev_hash: str) -> str:
        """Compute SHA-256 chain hash for a record."""
        content = json.dumps(record, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256((prev_hash + content).encode()).hexdigest()

    # ---- Write ----

    def log(self, event: AuditEvent) -> str:
        """
        Write an audit event to the append-only log.

        Returns the event_id.

        Raises:
            OSError: If the log file cannot be written.
        """
        with self._lock:
            ws_id = event.actor.workspace_id or "global"
            log_path = self._log_path(ws_id)
            record = event.to_dict()

            # Chain hash
            if self._enable_hash_chain:
                prev = self._last_hash.get(ws_id, "0" * 64)
                record["_hash"] = self._compute_hash(record, prev)
                self._last_hash[ws_id] = record["_hash"]

            # Check rotation
            if self._rotation == "size" and log_path.exists():
                size_mb = log_path.stat().st_size / (1024 * 1024)
                if size_mb >= self.MAX_FILE_SIZE_MB:
                    date = self._current_date()
                    log_path = self._log_dir / f"audit-{ws_id}-{date}-{uuid.uuid4().hex[:8]}.jsonl"

            # Append write
            try:
                with open(log_path, "a", encoding="utf-8") as f:
                    line = json.dumps(record, ensure_ascii=False) + "\n"
                    f.write(line)
            except OSError as e:
                _log.error("Audit log write failed: %s", e)
                raise

            _log.debug("Audit event logged: %s %s", event.event_id, event.action)
            return event.event_id

    # ---- Query ----

    def query(
        self,
        workspace_id: str | None = None,
        actor_id: str | None = None,
        action: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        """
        Query audit log entries with filters.

        Args:
            workspace_id: Filter by workspace
            actor_id: Filter by actor ID
            action: Filter by action (exact or prefix)
            start_time: Filter events after this time
            end_time: Filter events before this time
            limit: Maximum entries to return (default 100)

        Returns:
            List of matching AuditEvent objects (newest first)
        """
        results: list[tuple[datetime, AuditEvent]] = []
        seen_ids: set[str] = set()

        # Determine date range to scan
        if start_time and end_time:
            dates = _date_range(start_time, end_time)
        elif workspace_id:
            # Scan last 30 days if no time range
            dates = _date_range(
                datetime.now(timezone.utc),
                datetime.now(timezone.utc),
                days_back=30,
            )
        else:
            # Global audit — scan all files
            dates = None
            scan_files = list(self._log_dir.glob("audit-*.jsonl"))

        if dates is not None:
            ws_pattern = workspace_id.replace("/", "_") if workspace_id else "*"
            scan_files = [
                self._log_dir / f"audit-{ws_pattern}-{d}.jsonl"
                for d in dates
            ]

        for log_file in sorted(scan_files, key=lambda p: p.name, reverse=True):
            if not log_file.exists():
                continue
            if limit > 0 and len(results) >= limit:
                break

            try:
                # Handle .gz files
                open_fn = gzip.open if str(log_file).endswith(".gz") else open
                with open_fn(log_file, "rt", encoding="utf-8") as f:
                    for line in f:
                        if limit > 0 and len(results) >= limit:
                            break
                        try:
                            record = json.loads(line)
                            event = self._record_to_event(record)
                            if event is None:
                                continue
                            if not self._matches_filters(
                                event,
                                workspace_id=workspace_id,
                                actor_id=actor_id,
                                action=action,
                                start_time=start_time,
                                end_time=end_time,
                            ):
                                continue
                            if event.event_id in seen_ids:
                                continue
                            seen_ids.add(event.event_id)
                            ts = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
                            results.append((ts, event))
                        except json.JSONDecodeError:
                            continue
            except OSError as e:
                _log.warning("Could not read audit log %s: %s", log_file, e)
                continue

        # Sort newest first
        results.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in results[:limit]]

    def _record_to_event(self, record: dict) -> AuditEvent | None:
        try:
            actor_data = record.get("actor", {})
            target_data = record.get("target", {})
            return AuditEvent(
                event_id=record.get("event_id", ""),
                timestamp=record.get("timestamp", ""),
                actor=Actor(
                    type=actor_data.get("type", "unknown"),
                    id=actor_data.get("id", ""),
                    workspace_id=actor_data.get("workspace_id", ""),
                ),
                action=record.get("action", ""),
                target=Target(
                    type=target_data.get("type", "unknown"),
                    id=target_data.get("id", ""),
                ),
                changes=record.get("changes", {}),
                metadata=record.get("metadata", {}),
            )
        except Exception:
            return None

    def _matches_filters(
        self,
        event: AuditEvent,
        workspace_id: str | None,
        actor_id: str | None,
        action: str | None,
        start_time: datetime | None,
        end_time: datetime | None,
    ) -> bool:
        if workspace_id and event.actor.workspace_id != workspace_id:
            return False
        if actor_id and event.actor.id != actor_id:
            return False
        if action:
            if not event.action.startswith(action):
                return False
        if start_time or end_time:
            ts = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
            if start_time and ts < start_time:
                return False
            if end_time and ts > end_time:
                return False
        return True

    # ---- Utility ----

    def list_workspaces(self) -> list[str]:
        """Return list of workspace IDs with audit logs."""
        files = self._log_dir.glob("audit-*.jsonl")
        ws_ids: set[str] = set()
        for f in files:
            # Parse audit-{workspace_id}-{date}.jsonl
            name = f.name
            parts = name.split("-")
            if len(parts) >= 3:
                ws_ids.add(parts[1])
        return sorted(ws_ids)

    def verify_integrity(self, workspace_id: str, date: str | None = None) -> bool:
        """
        Verify hash chain integrity for a workspace/date.
        Returns True if all hashes are valid, False if tampering detected.
        """
        log_path = self._log_path(workspace_id, date)
        if not log_path.exists():
            return True  # No file = nothing to verify

        prev_hash = "0" * 64
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    record = json.loads(line)
                    stored_hash = record.get("_hash", "")
                    computed = self._compute_hash(
                        {k: v for k, v in record.items() if k != "_hash"},
                        prev_hash,
                    )
                    if stored_hash and stored_hash != computed:
                        _log.error("Hash chain broken at event %s", record.get("event_id"))
                        return False
                    prev_hash = stored_hash or computed
        except Exception as e:
            _log.error("Integrity check failed: %s", e)
            return False
        return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _date_range(start: datetime, end: datetime, days_back: int = 30) -> list[str]:
    """Generate list of YYYYMMDD strings."""
    if days_back:
        from datetime import timedelta
        end_dt = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(days=days_back)
    else:
        start_dt = start
        end_dt = end
    result = []
    current = start_dt
    from datetime import timedelta
    while current <= end_dt:
        result.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return result
