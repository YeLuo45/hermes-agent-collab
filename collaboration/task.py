"""Task lifecycle manager for the collaboration module.

Implements the full task state machine defined in the PRD:
  pending → claimed → in_progress → completed / failed / blocked

Provides CRUD operations that emit events to the collaboration event bus
so WebSocket servers and other listeners stay in sync.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from collaboration.events import Event, EventType, get_event_bus
from collaboration.models import Priority, Task, TaskStatus
from collaboration.storage import HERMES_HOME, JsonFileStore

_log = logging.getLogger(__name__)


class TaskTransitionError(ValueError):
    """Raised when a task state transition is invalid."""
    pass


class TaskManager:
    """Manages task lifecycle within a workspace.

    All mutating methods emit events so listeners (WebSocket, CLI, etc.) stay
    in sync automatically.
    """

    def __init__(self, workspace_id: str, base_path: str | None = None):
        if base_path:
            self._base_path = Path(base_path).expanduser()
        else:
            self._base_path = None
        self.workspace_id = workspace_id
        self._ensure_ws_files()
        self._store = JsonFileStore.for_tasks(self._ws_root / workspace_id)
        self._bus = get_event_bus()

    @property
    def _ws_root(self) -> Path:
        return (self._base_path or HERMES_HOME) / "workspaces"

    def _ensure_ws_files(self) -> None:
        """Ensure workspace directory and JSON files exist."""
        ws_path = self._ws_root / self.workspace_id
        ws_path.mkdir(parents=True, exist_ok=True)
        for filename in ["tasks.json", "agents.json", "skills.json", "workspace.json", "config.json"]:
            fp = ws_path / filename
            if not fp.exists():
                fp.write_text("[]" if filename != "config.json" else "{}")

    # ─── CRUD ─────────────────────────────────────────────────────────────────

    def create(
        self,
        title: str,
        description: str = "",
        creator: str | None = None,
        priority: Priority | str = Priority.MEDIUM,
        depends_on: list[str] | None = None,
    ) -> Task:
        """Create a new task and emit task.created."""
        if isinstance(priority, str):
            priority = Priority(priority)
        task = Task.new(
            title=title,
            description=description,
            creator=creator,
            workspace_id=self.workspace_id,
        )
        task.priority = priority
        if depends_on:
            task.depends_on = depends_on

        # Validate no circular dependency
        if depends_on:
            self._validate_dependencies(task)

        task = self._store.upsert(task)
        self._bus.emit_sync(Event(
            EventType.TASK_CREATED,
            workspace_id=self.workspace_id,
            payload=task.to_dict(),
        ))
        return task

    def get(self, task_id: str) -> Task | None:
        """Get a task by ID."""
        return self._store.get(task_id)

    def list(self) -> list[Task]:
        """List all tasks in the workspace, sorted by priority then created_at."""
        tasks = self._store.list()
        priority_order = {Priority.CRITICAL: 0, Priority.HIGH: 1, Priority.MEDIUM: 2, Priority.LOW: 3}
        return sorted(
            tasks,
            key=lambda t: (
                priority_order.get(t.priority if isinstance(t.priority, Priority) else Priority(t.priority), 3),
                t.created_at,
            ),
        )

    def update(self, task_id: str, **fields) -> Task:
        """Update mutable fields on a task."""
        task = self._store.get(task_id)
        if not task:
            raise KeyError(f"Task {task_id} not found")

        for key, value in fields.items():
            if hasattr(task, key) and key not in ("task_id",):
                setattr(task, key, value)

        task.updated_at = datetime.now(timezone.utc).isoformat()
        task = self._store.upsert(task)
        self._bus.emit_sync(Event(
            EventType.TASK_UPDATED,
            workspace_id=self.workspace_id,
            payload=task.to_dict(),
        ))
        return task

    def delete(self, task_id: str) -> bool:
        """Delete a task by ID."""
        ok = self._store.delete(task_id)
        if ok:
            self._bus.emit_sync(Event(
                EventType.TASK_DELETED,
                workspace_id=self.workspace_id,
                payload={"task_id": task_id},
            ))
        return ok

    # ─── State transitions ─────────────────────────────────────────────────────

    def claim(self, task_id: str, agent_id: str) -> Task:
        """Agent claims a pending task → status becomes claimed."""
        task = self._store.get(task_id)
        if not task:
            raise KeyError(f"Task {task_id} not found")

        if task.status != TaskStatus.PENDING:
            raise TaskTransitionError(
                f"Cannot claim task in {task.status} state. "
                f"Only pending tasks can be claimed."
            )

        task.status = TaskStatus.CLAIMED
        task.assignee = agent_id
        task.updated_at = datetime.now(timezone.utc).isoformat()
        task = self._store.upsert(task)
        self._bus.emit_sync(Event(
            EventType.TASK_UPDATED,
            workspace_id=self.workspace_id,
            payload=task.to_dict(),
        ))
        return task

    def start(self, task_id: str) -> Task:
        """Start work on a claimed task → status becomes in_progress."""
        task = self._store.get(task_id)
        if not task:
            raise KeyError(f"Task {task_id} not found")

        if task.status != TaskStatus.CLAIMED:
            raise TaskTransitionError(
                f"Cannot start task in {task.status} state. "
                f"Only claimed tasks can be started."
            )

        task.status = TaskStatus.IN_PROGRESS
        task.updated_at = datetime.now(timezone.utc).isoformat()
        task = self._store.upsert(task)
        self._bus.emit_sync(Event(
            EventType.TASK_UPDATED,
            workspace_id=self.workspace_id,
            payload=task.to_dict(),
        ))
        return task

    def complete(self, task_id: str) -> Task:
        """Mark a task as completed."""
        task = self._store.get(task_id)
        if not task:
            raise KeyError(f"Task {task_id} not found")

        if not task.can_transition_to(TaskStatus.COMPLETED):
            raise TaskTransitionError(
                f"Cannot complete task in {task.status} state."
            )

        task.status = TaskStatus.COMPLETED
        task.updated_at = datetime.now(timezone.utc).isoformat()
        task = self._store.upsert(task)
        self._bus.emit_sync(Event(
            EventType.TASK_UPDATED,
            workspace_id=self.workspace_id,
            payload=task.to_dict(),
        ))
        return task

    def fail(self, task_id: str, reason: str | None = None) -> Task:
        """Mark a task as failed."""
        task = self._store.get(task_id)
        if not task:
            raise KeyError(f"Task {task_id} not found")

        if not task.can_transition_to(TaskStatus.FAILED):
            raise TaskTransitionError(
                f"Cannot fail task in {task.status} state."
            )

        task.status = TaskStatus.FAILED
        task.updated_at = datetime.now(timezone.utc).isoformat()
        task = self._store.upsert(task)
        self._bus.emit_sync(Event(
            EventType.TASK_UPDATED,
            workspace_id=self.workspace_id,
            payload=task.to_dict(),
        ))
        return task

    def block(self, task_id: str, reason: str) -> Task:
        """Block a task with a reason."""
        task = self._store.get(task_id)
        if not task:
            raise KeyError(f"Task {task_id} not found")

        if not task.can_transition_to(TaskStatus.BLOCKED):
            raise TaskTransitionError(
                f"Cannot block task in {task.status} state."
            )

        task.status = TaskStatus.BLOCKED
        task.blocked_reason = reason
        task.updated_at = datetime.now(timezone.utc).isoformat()
        task = self._store.upsert(task)
        self._bus.emit_sync(Event(
            EventType.TASK_UPDATED,
            workspace_id=self.workspace_id,
            payload=task.to_dict(),
        ))
        return task

    def unblock(self, task_id: str) -> Task:
        """Unblock a blocked task, returning it to pending."""
        task = self._store.get(task_id)
        if not task:
            raise KeyError(f"Task {task_id} not found")

        if task.status != TaskStatus.BLOCKED:
            raise TaskTransitionError(
                f"Task {task_id} is not blocked."
            )

        task.status = TaskStatus.PENDING
        task.blocked_reason = None
        task.updated_at = datetime.now(timezone.utc).isoformat()
        task = self._store.upsert(task)
        self._bus.emit_sync(Event(
            EventType.TASK_UPDATED,
            workspace_id=self.workspace_id,
            payload=task.to_dict(),
        ))
        return task

    def set_status(self, task_id: str, new_status: TaskStatus | str) -> Task:
        """Set task status directly (validates via can_transition_to)."""
        if isinstance(new_status, str):
            new_status = TaskStatus(new_status)
        task = self._store.get(task_id)
        if not task:
            raise KeyError(f"Task {task_id} not found")

        if not task.can_transition_to(new_status):
            raise TaskTransitionError(
                f"Invalid transition: {task.status} → {new_status}"
            )

        task.status = new_status
        task.updated_at = datetime.now(timezone.utc).isoformat()
        task = self._store.upsert(task)
        self._bus.emit_sync(Event(
            EventType.TASK_UPDATED,
            workspace_id=self.workspace_id,
            payload=task.to_dict(),
        ))
        return task

    def assign(self, task_id: str, agent_id: str | None) -> Task:
        """Assign or unassign a task."""
        task = self._store.get(task_id)
        if not task:
            raise KeyError(f"Task {task_id} not found")
        task.assignee = agent_id
        task.updated_at = datetime.now(timezone.utc).isoformat()
        task = self._store.upsert(task)
        self._bus.emit_sync(Event(
            EventType.TASK_UPDATED,
            workspace_id=self.workspace_id,
            payload=task.to_dict(),
        ))
        return task

    # ─── Helpers ─────────────────────────────────────────────────────────────

    def _validate_dependencies(self, task: Task):
        """Check that depends_on IDs exist and don't create a cycle."""
        if not task.depends_on:
            return
        visited: set[str] = set()

        def has_cycle(dep_id: str) -> bool:
            if dep_id in visited:
                return True
            visited.add(dep_id)
            dep = self._store.get(dep_id)
            if dep and dep.depends_on:
                for next_id in dep.depends_on:
                    if has_cycle(next_id):
                        return True
            return False

        for dep_id in task.depends_on:
            if has_cycle(dep_id):
                raise TaskTransitionError(
                    f"Circular dependency detected involving task {dep_id}"
                )
