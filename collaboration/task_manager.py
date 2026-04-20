"""
Task Manager for Hermes Agent Team Collaboration.
Manages task lifecycle from creation to completion.

This module re-exports the canonical TaskManager from task.py
and provides CLI-compatible method signatures for backward compatibility.
"""

try:
    from .task import TaskManager as _TaskManager
    from .task import TaskTransitionError
    from .models import Task, TaskStatus, Priority
except ImportError:
    from collaboration.task import TaskManager as _TaskManager
    from collaboration.task import TaskTransitionError
    from collaboration.models import Task, TaskStatus, Priority


class TaskManager(_TaskManager):
    """CLI-compatible TaskManager wrapper.

    Inherits all methods from task.TaskManager.
    Provides backward-compatible aliases for CLI use.
    """
    # Aliases for CLI compatibility
    def create_task(self, title: str, description: str = "", creator: str | None = None,
                    workspace_id=None, owner_id=None, assignee_id=None,
                    priority=None, depends_on: list[str] | None = None,
                    skills_required: list[str] | None = None):
        return self.create(
            title=title,
            description=description,
            creator=creator or owner_id,
            priority=priority,
            depends_on=depends_on,
        )

    def list_tasks(self, workspace_id=None, status=None, priority=None, assignee_id=None):
        tasks = self.list()
        if status:
            tasks = [t for t in tasks if t.status.value == status]
        if priority:
            tasks = [t for t in tasks if t.priority.value == priority]
        if assignee_id:
            tasks = [t for t in tasks if t.assignee == assignee_id]
        return tasks

    def get_task(self, task_id: str):
        return self.get(task_id)

    def start_task(self, task_id: str, agent_id: str | None = None):
        return self.claim(task_id, agent_id)

    def complete_task(self, task_id: str, result: str = ""):
        task = self.get(task_id)
        if task:
            task.result = result
            return self.update(task_id, status="completed", result=result)
        return None

    def fail_task(self, task_id: str, error: str):
        task = self.get(task_id)
        if task:
            return self.update(task_id, status="failed", blocked_reason=error)
        return None

    def block_task(self, task_id: str, blockers: list[str]):
        return self.update(task_id, status="blocked", blocked_reason=", ".join(blockers))

    def unblock_task(self, task_id: str):
        return self.update(task_id, status="pending", blocked_reason=None)
