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
    pass
