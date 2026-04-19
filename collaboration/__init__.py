"""Collaboration module for Hermes Agent team coordination.

Phase 1: Data models + workspace CRUD + agent registry + JSON storage
Phase 2: Task lifecycle management + WebSocket real-time service

Key exports:
- Models: Agent, Task, Skill, Workspace (and enums)
- Storage: JsonFileStore, StorageLock
- Managers: WorkspaceManager, TaskManager, AgentRegistry
- Events: EventBus, Event, EventType
- WebSocket: ws_router (FastAPI), standalone_server()
"""

__version__ = "1.0.0"

from collaboration.agent_registry import AgentRegistry
from collaboration.events import Event, EventBus, EventType, get_event_bus
from collaboration.models import (
    Agent,
    AgentRole,
    AgentStatus,
    Priority,
    Skill,
    SkillLevel,
    Task,
    TaskStatus,
    Workspace,
)
from collaboration.storage import (
    HERMES_HOME,
    WORKSPACES_DIR,
    CURRENT_WS_FILE,
    JsonFileStore,
    StorageLock,
    ensure_workspace_files,
    get_current_workspace_id,
    get_workspace_path,
    set_current_workspace_id,
)
from collaboration.skill_system import SkillSystem
from collaboration.monitor import RuntimeMonitor
from collaboration.task import TaskManager, TaskTransitionError
from collaboration.workspace import WorkspaceManager
from collaboration.websocket_server import (
    standalone_server,
    ws_rooms_summary,
    ws_router,
)

__all__ = [
    # Models
    "Agent",
    "AgentRole",
    "AgentStatus",
    "Priority",
    "Skill",
    "SkillLevel",
    "Task",
    "TaskStatus",
    "Workspace",
    # Storage
    "JsonFileStore",
    "StorageLock",
    "HERMES_HOME",
    "WORKSPACES_DIR",
    "CURRENT_WS_FILE",
    "ensure_workspace_files",
    "get_current_workspace_id",
    "get_workspace_path",
    "set_current_workspace_id",
    # Managers
    "AgentRegistry",
    "TaskManager",
    "TaskTransitionError",
    "WorkspaceManager",
    "SkillSystem",
    "RuntimeMonitor",
    "__version__",
    # Events
    "Event",
    "EventBus",
    "EventType",
    "get_event_bus",
    # WebSocket
    "standalone_server",
    "ws_rooms_summary",
    "ws_router",
]
