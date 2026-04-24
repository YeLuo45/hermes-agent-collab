"""
FastAPI Router for Hermes Agent Team Collaboration API.
Provides REST endpoints for workspaces, agents, tasks, skills, and monitoring.
"""

import asyncio
import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

try:
    from .models import (
        Agent, AgentStatus, Task, TaskStatus, Priority,
        Workspace, Skill, SkillCategory, SkillLevel
    )
    from .storage import JsonFileStore
    from .workspace import WorkspaceManager
    from .agent_registry import AgentRegistry
    from .task_manager import TaskManager
    from .skill_system import SkillSystem
    from .monitor import RuntimeMonitor
    from .events import EventBus, EventType, get_event_bus
    from .acp_client import get_acp_client, close_acp_client
except ImportError:
    from collaboration.models import (
        Agent, AgentStatus, Task, TaskStatus, Priority,
        Workspace, Skill, SkillCategory, SkillLevel
    )
    from collaboration.storage import JsonFileStore
    from collaboration.workspace import WorkspaceManager
    from collaboration.agent_registry import AgentRegistry
    from collaboration.task_manager import TaskManager
    from collaboration.skill_system import SkillSystem
    from collaboration.monitor import RuntimeMonitor
    from collaboration.events import EventBus, EventType, get_event_bus
    from collaboration.acp_client import get_acp_client, close_acp_client

_log = logging.getLogger(__name__)

# Base path for collaboration data
COLLAB_BASE = Path("~/.hermes/collab").expanduser()
COLLAB_BASE.mkdir(parents=True, exist_ok=True)

# WorkspaceManager is stateless (no per-workspace state) so one instance suffices
workspace_mgr = WorkspaceManager()
event_bus = get_event_bus()

# Default workspace managers (lazily initialized on first request)
_default_workspace_id: str | None = None
_default_managers: dict | None = None
_managers_lock = threading.Lock()


def _get_default_managers():
    """Get or create managers for the default workspace."""
    global _default_workspace_id, _default_managers
    if _default_managers is not None:
        return _default_managers
    with _managers_lock:
        if _default_managers is not None:
            return _default_managers
        from collaboration.storage import get_current_workspace_id, ensure_workspace_files
        _default_workspace_id = get_current_workspace_id()
        if _default_workspace_id is None:
            ws = workspace_mgr.create_workspace(name="default", owner_id="system")
            _default_workspace_id = ws.workspace_id
        ws_path = ensure_workspace_files(_default_workspace_id)
        _default_managers = {
            "workspace_id": _default_workspace_id,
            "agents": AgentRegistry(_default_workspace_id),
            "tasks": TaskManager(_default_workspace_id),
            "skills": SkillSystem(_default_workspace_id),
        }
    return _default_managers


def _agent_registry():
    return _get_default_managers()["agents"]


def _skill_system():
    return _get_default_managers()["skills"]


def _task_manager():
    return _get_default_managers()["tasks"]


# RuntimeMonitor instance (stateless, no workspace_id needed)
monitor = RuntimeMonitor()


# Backward-compatibility aliases — resolve lazily at call time
@property
def _agent_registry_prop():
    return _get_default_managers()["agents"]


@property
def _skill_system_prop():
    return _get_default_managers()["skills"]


@property
def _task_manager_prop():
    return _get_default_managers()["tasks"]

# Create FastAPI router
router = APIRouter(prefix="/api/collab", tags=["collaboration"])


# =============================================================================
# Request/Response Models
# =============================================================================

class WorkspaceCreate(BaseModel):
    name: str
    owner_id: str
    description: Optional[str] = ""


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class AgentCreate(BaseModel):
    name: str
    role: str
    description: Optional[str] = ""
    skills: Optional[list[str]] = []
    workspace_id: Optional[str] = None


class AgentStatusUpdate(BaseModel):
    status: str  # online, offline, busy, away, error


class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = ""
    workspace_id: str
    owner_id: Optional[str] = None
    assignee_id: Optional[str] = None
    priority: Optional[str] = "medium"
    skills_required: Optional[list[str]] = []
    blocked_by: Optional[list[str]] = []


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    assignee_id: Optional[str] = None
    skills_required: Optional[list[str]] = None


class TaskAction(BaseModel):
    action: str  # start, complete, fail, block, unblock, cancel
    agent_id: Optional[str] = None
    result: Optional[dict] = None
    error: Optional[str] = None
    blockers: Optional[list[str]] = None


class SkillCreate(BaseModel):
    name: str
    category: str
    description: Optional[str] = ""
    config: Optional[dict] = {}


class MessageCreate(BaseModel):
    content: str


# =============================================================================
# Workspace Endpoints
# =============================================================================

@router.get("/")
async def root():
    """API root — list available endpoints."""
    return {
        "service": "Hermes Agent Collaboration API",
        "version": "1.0",
        "endpoints": {
            "workspaces": "/api/collab/workspaces",
            "agents": "/api/collab/agents",
            "tasks": "/api/collab/tasks",
            "skills": "/api/collab/skills",
            "monitor": "/api/collab/monitor/health",
            "websocket": "/api/collab/ws",
        }
    }


@router.get("/workspaces")
async def list_workspaces(owner_id: Optional[str] = None, active_only: bool = True):
    """List all workspaces."""
    workspaces = workspace_mgr.list_workspaces(
        owner_id=owner_id,
        is_active=active_only if active_only else None
    )
    return {"workspaces": [w.to_dict() for w in workspaces]}


@router.post("/workspaces")
async def create_workspace(data: WorkspaceCreate):
    """Create a new workspace."""
    workspace = workspace_mgr.create_workspace(
        name=data.name,
        owner_id=data.owner_id,
        description=data.description or ""
    )
    await event_bus.emit_agent_registered(
        workspace.workspace_id,
        workspace_id=workspace.workspace_id,
        agent_data=workspace.to_dict()
    )
    return workspace.to_dict()


@router.get("/workspaces/{workspace_id}")
async def get_workspace(workspace_id: str):
    """Get workspace details."""
    workspace = workspace_mgr.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace.to_dict()


@router.patch("/workspaces/{workspace_id}")
async def update_workspace(workspace_id: str, data: WorkspaceUpdate):
    """Update workspace properties."""
    workspace = workspace_mgr.update_workspace(
        workspace_id,
        name=data.name,
        description=data.description,
        is_active=data.is_active
    )
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace.to_dict()


@router.delete("/workspaces/{workspace_id}")
async def delete_workspace(workspace_id: str, force: bool = False):
    """Delete a workspace."""
    success = workspace_mgr.delete_workspace(workspace_id, force=force)
    if not success:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete non-empty workspace. Use force=true to archive."
        )
    return {"success": True, "workspace_id": workspace_id}


# =============================================================================
# Agent Endpoints
# =============================================================================

@router.get("/agents")
async def list_agents(
    workspace_id: Optional[str] = None,
    status: Optional[str] = None,
    role: Optional[str] = None
):
    """List agents with optional filtering."""
    agents = _agent_registry().list_agents(
        workspace_id=workspace_id,
        status=AgentStatus(status) if status else None,
        role=role
    )
    return {"agents": [a.to_dict() for a in agents]}


@router.post("/agents")
async def register_agent(data: AgentCreate):
    """Register a new agent."""
    profile = _agent_registry().register_agent(
        name=data.name,
        role=data.role,
        description=data.description or "",
        skills=data.skills or [],
        workspace_id=data.workspace_id
    )
    await event_bus.emit_agent_registered(
        profile.agent_id,
        workspace_id=data.workspace_id,
        agent_data=profile.to_dict()
    )
    return profile.to_dict()


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str):
    """Get agent details."""
    profile = _agent_registry().get_agent(agent_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Agent not found")
    return profile.to_dict()


@router.patch("/agents/{agent_id}/status")
async def update_agent_status(agent_id: str, data: AgentStatusUpdate):
    """Update agent status."""
    old_profile = _agent_registry().get_agent(agent_id)
    if not old_profile:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    old_status = old_profile.status.value if old_profile.status else "unknown"
    new_status = AgentStatus(data.status)
    
    success = _agent_registry().set_status(agent_id, new_status)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to update status")
    
    await event_bus.emit_agent_status_changed(
        agent_id,
        old_status=old_status,
        new_status=data.status,
        workspace_id=old_profile.workspace_id
    )
    
    return {"success": True, "agent_id": agent_id, "status": data.status}


@router.delete("/agents/{agent_id}")
async def unregister_agent(agent_id: str):
    """Unregister an agent."""
    success = _agent_registry().unregister(agent_id)
    if not success:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"success": True, "agent_id": agent_id}


@router.post("/agents/{agent_id}/message")
async def agent_message(agent_id: str, data: MessageCreate):
    """Send a message to an agent — forwards to Hermes AIAgent via ACP protocol.
    
    Uses the running Hermes ACP adapter to process the message, reusing the
    agent's environment (.env credentials) and session state.
    """
    agent = _agent_registry().get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    content = data.content

    try:
        client = await get_acp_client()
        response = await client.send_message(
            content=content,
            session_id=agent_id,  # Use agent_id as session key for state reuse
            timeout=60.0,
        )
        response_content = response.content or "（无响应）"
    except asyncio.TimeoutError:
        response_content = "[Hermes 错误] ACP 调用超时（60秒）"
    except Exception as exc:
        _log.exception("Hermes ACP chat failed")
        response_content = f"[Hermes 错误] {type(exc).__name__}: {exc}"

    return {
        "msg_id": f"resp_{datetime.now().timestamp()}",
        "agent_id": agent_id,
        "role": "assistant",
        "content": response_content,
        "ts": datetime.now().isoformat(),
    }


# =============================================================================
# Task Endpoints
# =============================================================================

@router.get("/tasks")
async def list_tasks(
    workspace_id: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    assignee_id: Optional[str] = None
):
    """List tasks with optional filtering."""
    tasks = _task_manager().list_tasks(
        workspace_id=workspace_id,
        status=TaskStatus(status) if status else None,
        priority=Priority(priority) if priority else None,
        assignee_id=assignee_id
    )
    return {"tasks": [t.to_dict() for t in tasks]}


@router.post("/tasks")
async def create_task(data: TaskCreate):
    """Create a new task."""
    task = _task_manager().create_task(
        title=data.title,
        description=data.description or "",
        workspace_id=data.workspace_id,
        owner_id=data.owner_id,
        assignee_id=data.assignee_id,
        priority=Priority(data.priority) if data.priority else Priority.MEDIUM,
        skills_required=data.skills_required or [],
        blocked_by=data.blocked_by or []
    )
    
    await event_bus.emit_task_created(
        task.task_id,
        workspace_id=data.workspace_id,
        task_data=task.to_dict()
    )
    
    return task.to_dict()


@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """Get task details."""
    task = _task_manager().get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.to_dict()


@router.patch("/tasks/{task_id}")
async def update_task(task_id: str, data: TaskUpdate):
    """Update task properties."""
    task = _task_manager().update_task(
        task_id,
        title=data.title,
        description=data.description,
        priority=Priority(data.priority) if data.priority else None,
        assignee_id=data.assignee_id,
        skills_required=data.skills_required
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    changes = {}
    if data.title:
        changes["title"] = data.title
    if data.description:
        changes["description"] = data.description
    if data.priority:
        changes["priority"] = data.priority
    if data.assignee_id:
        changes["assignee_id"] = data.assignee_id
    
    await event_bus.emit_task_updated(
        task_id,
        workspace_id=task.workspace_id,
        changes=changes
    )
    
    return task.to_dict()


@router.post("/tasks/{task_id}/actions")
async def task_action(task_id: str, data: TaskAction):
    """Perform an action on a task."""
    task = None
    
    if data.action == "start":
        if not data.agent_id:
            raise HTTPException(status_code=400, detail="agent_id required for start")
        task = _task_manager().start_task(task_id, data.agent_id)
        if task:
            _agent_registry().assign_task(data.agent_id, task_id)
    
    elif data.action == "complete":
        task = _task_manager().complete_task(task_id, data.result)
        if task and task.assignee_id:
            _agent_registry().clear_task(task.assignee_id)
    
    elif data.action == "fail":
        task = _task_manager().fail_task(task_id, data.error or "Unknown error")
        if task and task.assignee_id:
            _agent_registry().clear_task(task.assignee_id)
    
    elif data.action == "block":
        if not data.blockers:
            raise HTTPException(status_code=400, detail="blockers required for block")
        task = _task_manager().block_task(task_id, data.blockers)
    
    elif data.action == "unblock":
        task = _task_manager().unblock_task(task_id)
    
    elif data.action == "cancel":
        task = _task_manager().cancel_task(task_id)
    
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {data.action}")
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found or action not allowed")
    
    # Emit appropriate event
    if data.action == "complete":
        await event_bus.emit_task_completed(
            task_id,
            workspace_id=task.workspace_id,
            result=data.result
        )
    elif data.action == "fail":
        await event_bus.emit_task_failed(
            task_id,
            workspace_id=task.workspace_id,
            error=data.error or "Unknown error"
        )
    
    return task.to_dict()


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str):
    """Delete a task."""
    success = _task_manager().delete_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"success": True, "task_id": task_id}


@router.get("/tasks/{task_id}/subtasks")
async def get_subtasks(task_id: str):
    """Get subtasks of a task."""
    subtasks = _task_manager().get_subtasks(task_id)
    return {"tasks": [t.to_dict() for t in subtasks]}


@router.get("/workspaces/{workspace_id}/tasks")
async def get_workspace_tasks(workspace_id: str):
    """Get all tasks in a workspace."""
    tasks = _task_manager().get_tasks_by_workspace(workspace_id)
    return {"tasks": [t.to_dict() for t in tasks]}


@router.get("/workspaces/{workspace_id}/stats")
async def get_workspace_stats(workspace_id: str):
    """Get workspace statistics."""
    task_stats = _task_manager().get_task_stats(workspace_id)
    workspace_metrics = _monitor().get_workspace_metrics(workspace_id, _task_manager())
    
    return {
        "task_stats": task_stats,
        "workspace_metrics": {
            "total_agents": workspace_metrics.total_agents,
            "active_agents": workspace_metrics.active_agents,
            "total_tasks": workspace_metrics.total_tasks,
            "pending_tasks": workspace_metrics.pending_tasks,
            "in_progress_tasks": workspace_metrics.in_progress_tasks,
            "completed_tasks": workspace_metrics.completed_tasks,
            "blocked_tasks": workspace_metrics.blocked_tasks,
            "completion_rate": workspace_metrics.completion_rate,
            "avg_task_duration_seconds": workspace_metrics.avg_task_duration_seconds
        }
    }


# =============================================================================
# Skill Endpoints
# =============================================================================

@router.get("/skills")
async def list_skills(category: Optional[str] = None, enabled_only: bool = False):
    """List skills with optional filtering."""
    skills = _skill_system().list_skills(
        category=SkillCategory(category) if category else None,
        enabled= True if enabled_only else None
    )
    return {"skills": [s.to_dict() for s in skills]}


@router.post("/skills")
async def create_skill(data: SkillCreate):
    """Create a new skill."""
    skill = _skill_system().create_skill(
        name=data.name,
        category=SkillCategory(data.category),
        description=data.description or "",
        config=data.config or {}
    )
    await event_bus.emit_skill_created(
        skill.skill_id,
        workspace_id=None,
        skill_data=skill.to_dict()
    )
    return skill.to_dict()


@router.get("/skills/{skill_id}")
async def get_skill(skill_id: str):
    """Get skill details."""
    skill = _skill_system().get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill.to_dict()


@router.patch("/skills/{skill_id}")
async def update_skill(
    skill_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    category: Optional[str] = None,
    tags: Optional[list[str]] = None,
    config: Optional[dict] = None,
    enabled: Optional[bool] = None
):
    """Update skill properties."""
    skill = _skill_system().update_skill(
        skill_id,
        name=name,
        description=description,
        category=category,
        tags=tags,
        config=config,
        enabled=enabled
    )
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill.to_dict()


@router.delete("/skills/{skill_id}")
async def delete_skill(skill_id: str):
    """Delete a skill."""
    success = _skill_system().delete_skill(skill_id)
    if not success:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"success": True, "skill_id": skill_id}


@router.get("/skills/search")
async def search_skills(q: str, category: Optional[str] = None):
    """Search skills by name or description."""
    skills = _skill_system().search_skills(q, category=SkillCategory(category) if category else None)
    return {"skills": [s.to_dict() for s in skills]}


@router.get("/skills/stats")
async def get_skill_stats():
    """Get skill statistics."""
    return _skill_system().get_skill_stats()


# =============================================================================
# Monitoring Endpoints
# =============================================================================

@router.get("/monitor/health")
async def get_health():
    """Get system health status."""
    return monitor.get_system_health()


@router.get("/monitor/events")
async def get_events(
    event_type: Optional[str] = None,
    limit: int = 100
):
    """Get recent events."""
    events = monitor.get_events(
        event_type=event_type,
        limit=limit
    )
    return {"events": events}


@router.get("/monitor/agent/{agent_id}/metrics")
async def get_agent_metrics(agent_id: str):
    """Get metrics for an agent."""
    metrics = monitor.get_agent_metrics(agent_id)
    return {
        "agent_id": agent_id,
        "messages_sent": metrics.messages_sent,
        "messages_received": metrics.messages_received,
        "tasks_completed": metrics.tasks_completed,
        "tasks_failed": metrics.tasks_failed,
        "uptime_seconds": metrics.uptime_seconds,
        "last_activity": metrics.last_activity,
        "cpu_usage": metrics.cpu_usage,
        "memory_usage": metrics.memory_usage
    }


@router.get("/monitor/agent-status-summary")
async def get_agent_status_summary():
    """Get summary of agent statuses."""
    return monitor.get_agent_status_summary()


@router.get("/monitor/metrics/export")
async def export_metrics():
    """Export all metrics as JSON."""
    return monitor.export_metrics("json")


# =============================================================================
# WebSocket Integration
# =============================================================================

class ConnectionManager:
    """Manages WebSocket connections for collaboration."""
    
    def __init__(self):
        self.active_connections: list[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
    
    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients."""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)
        
        for conn in disconnected:
            self.disconnect(conn)


manager = ConnectionManager()


async def ws_broadcast_event(event):
    """Broadcast event to all WebSocket clients."""
    await manager.broadcast({
        "type": "event",
        "event_type": event.event_type.value if hasattr(event.event_type, 'value') else event.event_type,
        "payload": event.payload,
        "timestamp": event.timestamp
    })


# Set up event bus to broadcast via WebSocket
event_bus.set_ws_broadcast(ws_broadcast_event)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time collaboration updates."""
    await manager.connect(websocket)
    
    # Send initial state
    await websocket.send_json({
        "type": "init",
        "payload": {
            "workspaces": [w.to_dict() for w in workspace_mgr.list_workspaces()],
            "agents": [],
            "tasks": [],
            "skills": []
        }
    })
    
    try:
        while True:
            data = await websocket.receive_json()
            
            msg_type = data.get("type")
            
            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
            
            elif msg_type == "subscribe":
                # Client subscribing to updates - already connected
                await websocket.send_json({
                    "type": "subscribed",
                    "payload": {"channels": data.get("channels", [])}
                })
            
            elif msg_type == "agent_status":
                # Update agent status
                agent_id = data.get("agent_id")
                status = data.get("status")
                if agent_id and status:
                    _agent_registry().set_status(agent_id, AgentStatus(status))
                    await websocket.send_json({
                        "type": "agent_update",
                        "payload": {"agent_id": agent_id, "status": status}
                    })
            
            elif msg_type == "task_update":
                # Update task status
                task_id = data.get("task_id")
                action = data.get("action")
                if task_id and action:
                    if action == "start":
                        agent_id = data.get("agent_id")
                        if agent_id:
                            _task_manager().start_task(task_id, agent_id)
                    elif action == "complete":
                        _task_manager().complete_task(task_id)
                    elif action == "fail":
                        _task_manager().fail_task(task_id, data.get("error", "Unknown"))
                    
                    await websocket.send_json({
                        "type": "task_update",
                        "payload": {"task_id": task_id, "action": action}
                    })
    
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        _log.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)
