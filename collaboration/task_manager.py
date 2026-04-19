"""
Task Manager for Hermes Agent Team Collaboration.
Manages task lifecycle from creation to completion.
"""

import json
import uuid
from pathlib import Path
from typing import Optional

try:
    from .models import Task, TaskStatus, Priority
    from .storage import JsonFileStore
except ImportError:
    from collaboration.models import Task, TaskStatus, Priority
    from collaboration.storage import JsonFileStore


class TaskManager:
    """Manages task lifecycle and workflow."""
    
    def __init__(self, workspace_id: str = None):
        if workspace_id:
            from collaboration.storage import ensure_workspace_files
            ws_path = ensure_workspace_files(workspace_id)
            self._workspace_id = workspace_id
            self.store = JsonFileStore.for_tasks(ws_path)
        else:
            from collaboration.storage import HERMES_HOME
            self._workspace_id = None
            self.base_path = HERMES_HOME / "collab"
            self.base_path.mkdir(parents=True, exist_ok=True)
            self.store = JsonFileStore.for_tasks(self.base_path)
    
    def create_task(
        self,
        title: str,
        description: str,
        workspace_id: str,
        owner_id: str = None,
        assignee_id: str = None,
        priority: Priority = Priority.MEDIUM,
        skills_required: list[str] = None,
        blocked_by: list[str] = None,
        parent_task_id: str = None,
        due_at: str = None,
        metadata: dict = None
    ) -> Task:
        """Create a new task."""
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        task = Task(
            task_id=task_id,
            title=title,
            description=description,
            workspace_id=workspace_id,
            owner_id=owner_id,
            assignee_id=assignee_id,
            priority=priority,
            skills_required=skills_required or [],
            blocked_by=blocked_by or [],
            parent_task_id=parent_task_id,
            due_at=due_at,
            metadata=metadata or {}
        )
        
        self.store.upsert(task.to_dict())
        return task
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID."""
        data = self.store.get(task_id)
        if data:
            return Task.from_dict(data)
        return None
    
    def update_task(
        self,
        task_id: str,
        title: str = None,
        description: str = None,
        priority: Priority = None,
        assignee_id: str = None,
        skills_required: list[str] = None,
        due_at: str = None,
        metadata: dict = None
    ) -> Optional[Task]:
        """Update task properties."""
        task = self.get_task(task_id)
        if not task:
            return None
        
        if title is not None:
            task.title = title
        if description is not None:
            task.description = description
        if priority is not None:
            task.priority = priority
        if assignee_id is not None:
            task.assignee_id = assignee_id
        if skills_required is not None:
            task.skills_required = skills_required
        if due_at is not None:
            task.due_at = due_at
        if metadata is not None:
            task.metadata.update(metadata)
        
        self.store.upsert(task.to_dict())
        return task
    
    def delete_task(self, task_id: str) -> bool:
        """Delete a task."""
        return self.store.delete(task_id)
    
    def start_task(self, task_id: str, agent_id: str) -> Optional[Task]:
        """Start a task (assigns to agent)."""
        task = self.get_task(task_id)
        if not task:
            return None
        
        if task.status == TaskStatus.BLOCKED:
            return None  # Cannot start blocked task
        
        task.start(agent_id)
        self.store.upsert(task.to_dict())
        return task
    
    def complete_task(self, task_id: str, result: dict = None) -> Optional[Task]:
        """Mark task as completed."""
        task = self.get_task(task_id)
        if not task:
            return None
        
        task.complete(result)
        self.store.upsert(task.to_dict())
        
        # Unblock dependent tasks
        self._unblock_dependent_tasks(task_id)
        
        return task
    
    def fail_task(self, task_id: str, error: str) -> Optional[Task]:
        """Mark task as failed."""
        task = self.get_task(task_id)
        if not task:
            return None
        
        task.fail(error)
        self.store.upsert(task.to_dict())
        return task
    
    def cancel_task(self, task_id: str) -> Optional[Task]:
        """Cancel a task."""
        task = self.get_task(task_id)
        if not task:
            return None
        
        task.status = TaskStatus.CANCELLED
        self.store.upsert(task.to_dict())
        return task
    
    def block_task(self, task_id: str, blocking_task_ids: list[str]) -> Optional[Task]:
        """Block a task."""
        task = self.get_task(task_id)
        if not task:
            return None
        
        task.block(blocking_task_ids)
        self.store.upsert(task.to_dict())
        return task
    
    def unblock_task(self, task_id: str) -> Optional[Task]:
        """Unblock a task."""
        task = self.get_task(task_id)
        if not task:
            return None
        
        task.unblock()
        self.store.upsert(task.to_dict())
        return task
    
    def _unblock_dependent_tasks(self, completed_task_id: str) -> None:
        """Unblock tasks that were blocked by the completed task."""
        all_tasks = self.store.list()
        for data in all_tasks:
            if completed_task_id in data.get("blocked_by", []):
                task = Task.from_dict(data)
                if completed_task_id in task.blocked_by:
                    task.blocked_by.remove(completed_task_id)
                    if task.status == TaskStatus.BLOCKED and not task.blocked_by:
                        task.status = TaskStatus.PENDING
                    self.store.upsert(task.to_dict())
    
    def list_tasks(
        self,
        workspace_id: str = None,
        status: TaskStatus = None,
        priority: Priority = None,
        assignee_id: str = None,
        owner_id: str = None
    ) -> list[Task]:
        """List tasks with optional filtering."""
        tasks = self.store.list()
        result = []
        for data in tasks:
            task = Task.from_dict(data)
            if workspace_id and task.workspace_id != workspace_id:
                continue
            if status and task.status != status:
                continue
            if priority and task.priority != priority:
                continue
            if assignee_id and task.assignee_id != assignee_id:
                continue
            if owner_id and task.owner_id != owner_id:
                continue
            result.append(task)
        return result
    
    def get_tasks_by_status(self, status: TaskStatus) -> list[Task]:
        """Get all tasks with a specific status."""
        return self.list_tasks(status=status)
    
    def get_tasks_by_assignee(self, assignee_id: str) -> list[Task]:
        """Get all tasks assigned to an agent."""
        return self.list_tasks(assignee_id=assignee_id)
    
    def get_tasks_by_workspace(self, workspace_id: str) -> list[Task]:
        """Get all tasks in a workspace."""
        return self.list_tasks(workspace_id=workspace_id)
    
    def get_blocked_tasks(self) -> list[Task]:
        """Get all blocked tasks."""
        return self.list_tasks(status=TaskStatus.BLOCKED)
    
    def get_pending_tasks(self) -> list[Task]:
        """Get all pending tasks."""
        return self.list_tasks(status=TaskStatus.PENDING)
    
    def get_in_progress_tasks(self) -> list[Task]:
        """Get all in-progress tasks."""
        return self.list_tasks(status=TaskStatus.IN_PROGRESS)
    
    def get_completed_tasks(
        self,
        workspace_id: str = None,
        limit: int = 100
    ) -> list[Task]:
        """Get recently completed tasks."""
        tasks = self.list_tasks(workspace_id=workspace_id, status=TaskStatus.COMPLETED)
        # Sort by completion time descending
        tasks.sort(key=lambda t: t.completed_at or "", reverse=True)
        return tasks[:limit]
    
    def search_tasks(
        self,
        query: str,
        workspace_id: str = None
    ) -> list[Task]:
        """Search tasks by title or description."""
        tasks = self.list_tasks(workspace_id=workspace_id)
        query_lower = query.lower()
        return [
            task for task in tasks
            if query_lower in task.title.lower() or query_lower in task.description.lower()
        ]
    
    def get_subtasks(self, parent_task_id: str) -> list[Task]:
        """Get all subtasks of a parent task."""
        tasks = self.store.list()
        return [
            Task.from_dict(data) 
            for data in tasks 
            if data.get("parent_task_id") == parent_task_id
        ]
    
    def match_skills(self, task_id: str, agent_skills: list[str]) -> list[str]:
        """Match agent skills against task requirements."""
        task = self.get_task(task_id)
        if not task:
            return []
        
        required = set(task.skills_required)
        available = set(agent_skills)
        matched = list(required & available)
        
        # Update task with matched skills
        if matched != task.skills_matched:
            task.skills_matched = matched
            self.store.upsert(task.to_dict())
        
        return matched
    
    def get_task_stats(self, workspace_id: str = None) -> dict:
        """Get task statistics."""
        tasks = self.list_tasks(workspace_id=workspace_id)
        stats = {
            "total": len(tasks),
            "by_status": {},
            "by_priority": {},
            "completion_rate": 0.0
        }
        
        status_counts = {}
        priority_counts = {}
        completed = 0
        
        for task in tasks:
            status_key = task.status.value if isinstance(task.status, TaskStatus) else task.status
            status_counts[status_key] = status_counts.get(status_key, 0) + 1
            
            priority_key = task.priority.value if isinstance(task.priority, Priority) else task.priority
            priority_counts[priority_key] = priority_counts.get(priority_key, 0) + 1
            
            if task.status == TaskStatus.COMPLETED:
                completed += 1
        
        stats["by_status"] = status_counts
        stats["by_priority"] = priority_counts
        if tasks:
            stats["completion_rate"] = completed / len(tasks)
        
        return stats
