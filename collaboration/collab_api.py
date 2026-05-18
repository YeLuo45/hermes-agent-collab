"""
FastAPI Router for Hermes Agent Team Collaboration API.
Provides REST endpoints for workspaces, agents, tasks, skills, and monitoring.
"""

import asyncio
import json
import logging
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
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
    from .events import EventType, get_event_bus
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
    from collaboration.events import EventType, get_event_bus

_log = logging.getLogger(__name__)

# Base path for collaboration data
COLLAB_BASE = Path("~/.hermes/collab").expanduser()
COLLAB_BASE.mkdir(parents=True, exist_ok=True)

# Per-workspace manager cache — lazily initialized per workspace_id
_manager_cache: dict[str, dict] = {}

def _get_workspace_managers(workspace_id: str | None = None):
    """Lazily get or create managers for a workspace.
    
    If workspace_id is None, returns managers for the current workspace
    (or creates a 'default' workspace if none exists).
    """
    if workspace_id is None:
        from collaboration.storage import get_current_workspace_id
        workspace_id = get_current_workspace_id()
        if workspace_id is None:
            # Auto-create a default workspace
            ws_mgr = WorkspaceManager()
            ws = ws_mgr.create_workspace(name="default", owner_id="system")
            workspace_id = ws.workspace_id
    
    if workspace_id not in _manager_cache:
        from collaboration.storage import ensure_workspace_files
        ws_path = ensure_workspace_files(workspace_id)
        _manager_cache[workspace_id] = {
            "workspace_id": workspace_id,
            "agents": AgentRegistry(workspace_id),
            "tasks": TaskManager(workspace_id),
            "skills": SkillSystem(workspace_id),
        }
    
    return _manager_cache[workspace_id]

# WorkspaceManager is stateless (no per-workspace state) so one instance suffices
workspace_mgr = WorkspaceManager()
event_bus = get_event_bus()

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
    action: str  # start, complete, fail, block, unblock, cancel, phase_transition
    agent_id: Optional[str] = None
    result: Optional[dict] = None
    error: Optional[str] = None
    blockers: Optional[list[str]] = None
    # Phase transition fields
    decision: Optional[str] = None  # "accept" or "reject" for phase_transition
    approver: Optional[str] = None   # agent_id of reviewer
    comments: Optional[str] = ""


class SkillCreate(BaseModel):
    name: str
    category: str
    description: Optional[str] = ""
    config: Optional[dict] = {}


# =============================================================================
# Auth Request/Response Models
# =============================================================================

class ApiKeyCreate(BaseModel):
    name: str
    workspace_id: str
    scopes: list[str]  # ["read", "write", "admin"]


class ApiKeyResponse(BaseModel):
    key_id: str
    name: str
    workspace_id: str
    scopes: list[str]
    created_at: str
    last_used_at: Optional[str]
    is_active: bool
    key_secret: Optional[str] = None  # only populated on create


# =============================================================================
# Multi-Agent Protocol Request/Response Models
# =============================================================================

class MessageSendRequest(BaseModel):
    receiver_id: Optional[str] = None  # None = broadcast
    msg_type: str
    payload: dict = {}
    session_id: Optional[str] = None
    ttl_seconds: int = 300


class SessionCreateRequest(BaseModel):
    participants: list[str]
    context: Optional[dict] = {}


class DistributionCreateRequest(BaseModel):
    task_id: str
    description: str
    policy_type: Optional[str] = "capability_match"
    policy_min_confidence: Optional[float] = 0.3
    required_capabilities: Optional[list[str]] = None


class DistributionAssignRequest(BaseModel):
    agent_id: str


class CapabilityMatchRequest(BaseModel):
    query: str
    required_capabilities: list[str]
    min_confidence: float = 0.3


class HookSubscribeRequest(BaseModel):
    event: str
    callback_url: Optional[str] = None
    filter_fields: Optional[dict] = None


class PluginRegisterRequest(BaseModel):
    name: str
    description: Optional[str] = ""
    hooks: list[str]
    config: Optional[dict] = {}


# =============================================================================
# Workspace Endpoints
# =============================================================================

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
    agents = agent_registry.list_agents(
        workspace_id=workspace_id,
        status=AgentStatus(status) if status else None,
        role=role
    )
    return {"agents": [a.to_dict() for a in agents]}


@router.post("/agents")
async def register_agent(data: AgentCreate):
    """Register a new agent."""
    profile = agent_registry.register_agent(
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
    profile = agent_registry.get_agent(agent_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Agent not found")
    return profile.to_dict()


@router.patch("/agents/{agent_id}/status")
async def update_agent_status(agent_id: str, data: AgentStatusUpdate):
    """Update agent status."""
    old_profile = agent_registry.get_agent(agent_id)
    if not old_profile:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    old_status = old_profile.status.value if old_profile.status else "unknown"
    new_status = AgentStatus(data.status)
    
    success = agent_registry.update_status(agent_id, new_status)
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
    success = agent_registry.delete_agent(agent_id)
    if not success:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"success": True, "agent_id": agent_id}


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
    tasks = task_mgr.list_tasks(
        workspace_id=workspace_id,
        status=TaskStatus(status) if status else None,
        priority=Priority(priority) if priority else None,
        assignee_id=assignee_id
    )
    return {"tasks": [t.to_dict() for t in tasks]}


@router.post("/tasks")
async def create_task(data: TaskCreate):
    """Create a new task."""
    task = task_mgr.create_task(
        title=data.title,
        description=data.description or "",
        workspace_id=data.workspace_id,
        owner_id=data.owner_id,
        assignee_id=data.assignee_id,
        priority=Priority(data.priority) if data.priority else Priority.MEDIUM,
        skills_required=data.skills_required or [],
        blocked_by=data.blocked_by or []
    )
    
    # Add task to workspace
    workspace_mgr.add_task_to_workspace(data.workspace_id, task.task_id)
    
    await event_bus.emit_task_created(
        task.task_id,
        workspace_id=data.workspace_id,
        task_data=task.to_dict()
    )
    
    return task.to_dict()


@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """Get task details."""
    task = task_mgr.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.to_dict()


@router.patch("/tasks/{task_id}")
async def update_task(task_id: str, data: TaskUpdate):
    """Update task properties."""
    task = task_mgr.update_task(
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
        task = task_mgr.start_task(task_id, data.agent_id)
        if task:
            agent_registry.assign_task(data.agent_id, task_id)
    
    elif data.action == "complete":
        task = task_mgr.complete_task(task_id, data.result)
        if task and task.assignee_id:
            agent_registry.clear_task(task.assignee_id)
    
    elif data.action == "fail":
        task = task_mgr.fail_task(task_id, data.error or "Unknown error")
        if task and task.assignee_id:
            agent_registry.clear_task(task.assignee_id)
    
    elif data.action == "block":
        if not data.blockers:
            raise HTTPException(status_code=400, detail="blockers required for block")
        task = task_mgr.block_task(task_id, data.blockers)
    
    elif data.action == "unblock":
        task = task_mgr.unblock_task(task_id)
    
    elif data.action == "cancel":
        task = task_mgr.cancel_task(task_id)

    elif data.action == "phase_transition":
        if not data.decision:
            raise HTTPException(status_code=400, detail="decision required for phase_transition")
        task = task_mgr.transition_phase(task_id, data.decision, data.approver, data.comments or "")

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
    success = task_mgr.delete_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"success": True, "task_id": task_id}


@router.get("/tasks/{task_id}/subtasks")
async def get_subtasks(task_id: str):
    """Get subtasks of a task."""
    subtasks = task_mgr.get_subtasks(task_id)
    return {"tasks": [t.to_dict() for t in subtasks]}


@router.get("/workspaces/{workspace_id}/tasks")
async def get_workspace_tasks(workspace_id: str):
    """Get all tasks in a workspace."""
    tasks = task_mgr.get_tasks_by_workspace(workspace_id)
    return {"tasks": [t.to_dict() for t in tasks]}


@router.get("/workspaces/{workspace_id}/stats")
async def get_workspace_stats(workspace_id: str):
    """Get workspace statistics."""
    task_stats = task_mgr.get_task_stats(workspace_id)
    workspace_metrics = monitor.get_workspace_metrics(workspace_id, task_mgr)
    
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
    skills = skill_system.list_skills(
        category=SkillCategory(category) if category else None,
        enabled= True if enabled_only else None
    )
    return {"skills": [s.to_dict() for s in skills]}


@router.post("/skills")
async def create_skill(data: SkillCreate):
    """Create a new skill."""
    skill = skill_system.create_skill(
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
    skill = skill_system.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill.to_dict()


@router.patch("/skills/{skill_id}")
async def update_skill(
    skill_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    config: Optional[dict] = None,
    enabled: Optional[bool] = None
):
    """Update skill properties."""
    skill = skill_system.update_skill(
        skill_id,
        name=name,
        description=description,
        config=config,
        enabled=enabled
    )
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill.to_dict()


@router.delete("/skills/{skill_id}")
async def delete_skill(skill_id: str):
    """Delete a skill."""
    success = skill_system.delete_skill(skill_id)
    if not success:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"success": True, "skill_id": skill_id}


@router.get("/skills/search")
async def search_skills(q: str, category: Optional[str] = None):
    """Search skills by name or description."""
    skills = skill_system.search_skills(q, category=SkillCategory(category) if category else None)
    return {"skills": [s.to_dict() for s in skills]}


@router.get("/skills/stats")
async def get_skill_stats():
    """Get skill statistics."""
    return skill_system.get_skill_stats()


# =============================================================================
# Orchestration Endpoints (Multi-Agent)
# =============================================================================

try:
    from .orchestration_manager import OrchestrationManager
except ImportError:
    from collaboration.orchestration_manager import OrchestrationManager


def _get_orch_mgr(workspace_id: str | None = None) -> OrchestrationManager:
    if workspace_id is None:
        from collaboration.storage import get_current_workspace_id
        workspace_id = get_current_workspace_id() or "default"
    return OrchestrationManager(workspace_id)


class OrchestrationCreate(BaseModel):
    root_task_id: str
    coordinator_id: str
    user_task_description: str
    owner_id: str = "anonymous"  # User creating this orchestration


class OrchestrationConfirm(BaseModel):
    agent_pool: list[str] = []  # list of agent_ids to use as specialists
    requester_id: str = "anonymous"  # Must match orchestration owner_id


@router.post("/orchestrations")
async def create_orchestration(data: OrchestrationCreate):
    """Create orchestration and trigger Coordinator task decomposition.

    Fails if the owner already has an active orchestration running.
    """
    mgr = _get_orch_mgr()
    # Check per-owner concurrency limit
    active = mgr.get_owner_active_orchestration(data.owner_id)
    if active:
        raise HTTPException(
            status_code=409,
            detail=f"Owner '{data.owner_id}' already has an active orchestration: {active.orchestration_id}",
        )
    orch = mgr.create_orchestration(
        root_task_id=data.root_task_id,
        coordinator_id=data.coordinator_id,
        user_task_description=data.user_task_description,
        owner_id=data.owner_id,
    )
    # Immediately run Coordinator decomposition (synchronous, may take a few seconds)
    import threading
    def run_decompose():
        try:
            mgr.decompose_task(orch.orchestration_id)
        except Exception as e:
            _log.error(f"Coordinator decomposition failed: {e}")
    threading.Thread(target=run_decompose, daemon=True).start()
    return orch.to_dict()


@router.get("/orchestrations")
async def list_orchestrations():
    """List all orchestrations."""
    mgr = _get_orch_mgr()
    return {"orchestrations": [o.to_dict() for o in mgr.list_orchestrations()]}


@router.get("/orchestrations/{orch_id}")
async def get_orchestration(orch_id: str):
    """Get orchestration by ID."""
    mgr = _get_orch_mgr()
    orch = mgr.get_orchestration(orch_id)
    if not orch:
        raise HTTPException(status_code=404, detail="Orchestration not found")
    return orch.to_dict()


@router.get("/orchestrations/{orch_id}/subtasks")
async def get_orchestration_subtasks(orch_id: str):
    """Get all sub-tasks for an orchestration."""
    mgr = _get_orch_mgr()
    subtasks = mgr.get_orchestration_subtasks(orch_id)
    return {"subtasks": [st.to_dict() for st in subtasks]}


@router.post("/orchestrations/{orch_id}/confirm")
async def confirm_orchestration(orch_id: str, data: OrchestrationConfirm):
    """User confirms decomposition plan → start parallel execution.

    Fails if requester_id does not match the orchestration's owner_id.
    """
    mgr = _get_orch_mgr()
    orch = mgr.get_orchestration(orch_id)
    if not orch:
        raise HTTPException(status_code=404, detail="Orchestration not found")

    # Ownership check
    if orch.owner_id != data.requester_id:
        raise HTTPException(
            status_code=403,
            detail=f"Requester '{data.requester_id}' does not own orchestration '{orch_id}'",
        )

    # Concurrency lock check (same owner can't run two at once)
    if not mgr.acquire_orchestration_lock(orch_id, data.requester_id):
        raise HTTPException(
            status_code=409,
            detail=f"Requester '{data.requester_id}' already has an active orchestration running",
        )

    # Run execution in background thread to avoid blocking
    import threading
    agent_pool = data.agent_pool if data.agent_pool else ["default"]
    def run():
        try:
            mgr.execute_orchestration(orch_id, agent_pool)
        except Exception as e:
            _log.error(f"Orchestration execution failed: {e}")
    threading.Thread(target=run, daemon=True).start()

    return {"phase": "executing", "orchestration_id": orch_id}


@router.get("/orchestrations/{orch_id}/report")
async def get_orchestration_report(orch_id: str):
    """Get final execution report (markdown)."""
    mgr = _get_orch_mgr()
    report = mgr.generate_report(orch_id)
    return {"report": report}


@router.get("/orchestrations/{orch_id}/stream")
async def stream_orchestration(orch_id: str):
    """SSE stream of real-time orchestration events for a specific orchestration.

    Streams: subtask.starting, subtask.started, subtask.completed,
    subtask.rejected, subtask.retry, review.created,
    orchestration.completed, orchestration.failed.
    """
    import asyncio
    from fastapi.responses import StreamingResponse

    async def event_generator():
        bus = get_event_bus()
        queue: asyncio.Queue[dict] = asyncio.Queue()

        # Filter for orchestration-specific events
        ORCH_EVENTS = {
            "subtask.starting", "subtask.started", "subtask.completed",
            "subtask.rejected", "subtask.retry", "subtask.cancelled",
            "review.created",
            "orchestration.completed", "orchestration.failed", "orchestration.cancelled",
        }

        async def on_event(event: "Event"):
            if event.payload.get("orchestration_id") == orch_id:
                await queue.put(event.to_dict())
            elif event.event_type.value.startswith("subtask."):
                # Check if this subtask belongs to this orchestration
                st_orch_id = event.payload.get("parent_orchestration_id")
                if st_orch_id == orch_id:
                    await queue.put(event.to_dict())

        await bus.subscribe(on_event, workspace_id=None)

        # Send heartbeat every 15s to keep connection alive
        last_heartbeat = 0

        try:
            while True:
                try:
                    event_data = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {json.dumps(event_data)}\n\n"
                    last_heartbeat = 0
                except asyncio.TimeoutError:
                    last_heartbeat += 15
                    if last_heartbeat >= 60:
                        break
                    yield f": heartbeat\n\n"
        except GeneratorExit:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/orchestrations/{orch_id}/cancel")
async def cancel_orchestration(orch_id: str):
    """Cancel an in-progress orchestration.

    Marks all non-terminal subtasks as CANCELLED and updates the
    orchestration phase to CANCELLED.
    """
    mgr = _get_orch_mgr()
    orch = mgr.cancel_orchestration(orch_id)
    if not orch:
        raise HTTPException(status_code=404, detail="Orchestration not found")
    return orch.to_dict()


@router.get("/orchestrations/{orch_id}/events")
async def get_orchestration_events(
    orch_id: str,
    event_type: str | None = None,
):
    """Get the persisted event log for an orchestration."""
    mgr = _get_orch_mgr()
    types = [event_type] if event_type else None
    events = mgr.get_orchestration_events(orch_id, event_types=types)
    return {"orchestration_id": orch_id, "count": len(events), "events": events}


@router.post("/orchestrations/{orch_id}/resume")
async def resume_orchestration(orch_id: str):
    """Resume a failed or cancelled orchestration.

    All non-terminal subtasks are reset to PENDING and re-executed.
    """
    mgr = _get_orch_mgr()
    # Get agent pool from request body
    try:
        body = await request.json()
        agent_pool = body.get("agent_pool", [])
    except Exception:
        agent_pool = []
    result = mgr.resume_orchestration(orch_id, agent_pool)
    if not result:
        raise HTTPException(status_code=404, detail="Orchestration not found or not in resumable state")
    return result.to_dict()


@router.get("/orchestrations/{orch_id}/replay")
async def get_replay(orch_id: str):
    """Get full replay: state snapshot + ordered steps."""
    mgr = _get_orch_mgr()
    result = mgr.replay_orchestration(orch_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# =============================================================================
# Template Endpoints
# =============================================================================

@router.post("/orchestrations/{orch_id}/save-as-template")
async def save_as_template(orch_id: str):
    """Save a completed orchestration as a reusable template."""
    mgr = _get_orch_mgr()
    try:
        body = await request.json()
    except Exception:
        body = {}
    name = body.get("name", f"template-{orch_id[:8]}")
    description = body.get("description", "")
    tags = body.get("tags", [])
    result = mgr.save_orchestration_as_template(orch_id, name, description, tags)
    if not result:
        raise HTTPException(status_code=404, detail="Orchestration not found or not completed")
    return result.to_dict()


@router.get("/templates")
async def list_templates(tag: str | None = None):
    """List all saved templates, optionally filtered by tag."""
    mgr = _get_orch_mgr()
    return {"templates": mgr.list_templates(tag=tag)}


@router.get("/templates/{template_id}")
async def get_template(template_id: str):
    """Get a template by ID."""
    mgr = _get_orch_mgr()
    tpl = mgr.get_template(template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    return tpl


@router.delete("/templates/{template_id}")
async def delete_template(template_id: str):
    """Delete a template."""
    mgr = _get_orch_mgr()
    ok = mgr.delete_template(template_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"deleted": template_id}


@router.post("/templates/{template_id}/apply")
async def apply_template(template_id: str):
    """Create a new orchestration from a template.

    The new orchestration skips the planning phase and goes directly to execution.
    """
    mgr = _get_orch_mgr()
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_task_description = body.get("user_task_description", "")
    coordinator_id = body.get("coordinator_id", "")
    owner_id = body.get("owner_id", "anonymous")
    result = mgr.apply_template(template_id, user_task_description, coordinator_id, owner_id)
    if not result:
        raise HTTPException(status_code=404, detail="Template not found")
    return result.to_dict()


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
# Message Bus Metrics Endpoints (dead-letter + queue metrics)
# =============================================================================

@router.get("/dead_letters")
async def get_dead_letters():
    """Get all dead-letter events that failed all retry attempts.

    Dead letters are events that could not be published after 3 retries
    and have been persisted to ~/.hermes/collab/dead_letters.json.
    """
    return {
        "dead_letters": event_bus.get_dead_letters(),
        "count": len(event_bus.get_dead_letters()),
    }


@router.delete("/dead_letters")
async def clear_dead_letters():
    """Clear all dead-letter events."""
    event_bus.clear_dead_letters()
    return {"success": True, "message": "Dead letters cleared"}


@router.get("/metrics")
async def get_message_bus_metrics():
    """Get message bus metrics including queue depths and drop counts.

    Returns:
        total_published: Total events published since bus start
        total_failed: Events that exhausted all retries and went to dead-letter
        queue_depths: Per-workspace (or None for global) queue sizes
        drop_counts: Per-workspace count of events dropped due to backpressure
        total_subscribers: Number of registered subscribers
        total_adapters: Number of registered channel adapters
    """
    return event_bus.get_metrics()


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


# ─── SSE (Server-Sent Events) ────────────────────────────────────────────────

class SSEManager:
    """Manages SSE client connections for real-time event streaming."""

    def __init__(self):
        # Each client has an asyncio.Queue to deliver events
        self._queues: dict[int, asyncio.Queue] = {}
        self._counter = 0

    def connect(self) -> tuple[int, asyncio.Queue]:
        """Register a new SSE client. Returns (client_id, queue)."""
        q: asyncio.Queue = asyncio.Queue()
        cid = self._counter
        self._counter += 1
        self._queues[cid] = q
        return cid, q

    def disconnect(self, client_id: int):
        """Remove a client."""
        self._queues.pop(client_id, None)

    async def broadcast(self, event: dict):
        """Push an event to all connected clients."""
        disconnected = []
        for cid, q in self._queues.items():
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                disconnected.append(cid)
        for cid in disconnected:
            self.disconnect(cid)

    async def event_generator(self, client_id: int, queue: asyncio.Queue):
        """Yield SSE-formatted events from the client's queue."""
        # Send initial heartbeat comment
        yield "event: connected\ndata: {}\n\n"
        while client_id in self._queues:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30)
                # Format as SSE: "event: <type>\ndata: <json>\n\n"
                event_type = event.get("event_type", "message")
                yield f"event: {event_type}\ndata: {json.dumps(event)}\n\n"
            except asyncio.TimeoutError:
                # Send keepalive comment
                yield ": heartbeat\n\n"


_sse_manager = SSEManager()


async def sse_broadcast_event(event):
    """Broadcast event to all SSE clients."""
    event_dict = {
        "type": "event",
        "event_type": event.event_type.value if hasattr(event.event_type, "value") else event.event_type,
        "payload": event.payload,
        "timestamp": event.timestamp,
    }
    await _sse_manager.broadcast(event_dict)


# Set up event bus to broadcast via SSE (WebSocket is handled by ChannelAdapter)
event_bus.set_ws_broadcast(sse_broadcast_event)


# =============================================================================
# Auth Endpoints
# =============================================================================

def _get_auth_service(workspace_id: str = "default"):
    """Get AuthService for a workspace."""
    from collaboration.storage import ensure_workspace_files
    from collaboration.auth import AuthService
    ws_path = ensure_workspace_files(workspace_id)
    return AuthService(ws_path)


@router.post("/auth/keys", response_model=ApiKeyResponse)
async def create_api_key(data: ApiKeyCreate):
    """Create a new API key. The key_secret is returned ONLY here — never again."""
    auth = _get_auth_service(data.workspace_id)
    key, raw_secret = auth.create_key(data.name, data.workspace_id, data.scopes)
    resp = key.to_dict()
    resp["key_secret"] = raw_secret
    return ApiKeyResponse(**resp)


@router.get("/auth/keys")
async def list_api_keys(workspace_id: str = "default"):
    """List all API keys for a workspace (secrets are masked)."""
    auth = _get_auth_service(workspace_id)
    keys = auth.list_keys(workspace_id)
    return {"keys": [k.to_dict() for k in keys]}


@router.get("/auth/keys/{key_id}", response_model=ApiKeyResponse)
async def get_api_key(key_id: str, workspace_id: str = "default"):
    """Get API key metadata."""
    auth = _get_auth_service(workspace_id)
    key = auth.get_key(key_id)
    if not key or key.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Key not found")
    return ApiKeyResponse(**key.to_dict())


@router.delete("/auth/keys/{key_id}")
async def revoke_api_key(key_id: str, workspace_id: str = "default"):
    """Revoke (deactivate) an API key."""
    auth = _get_auth_service(workspace_id)
    ok = auth.revoke_key(key_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Key not found")
    return {"success": True}


@router.post("/auth/verify")
async def verify_api_key(x_api_key: str):
    """Verify an API key and return its metadata.

    Header: X-API-Key: <key_id:secret>
    """
    if ":" not in x_api_key:
        raise HTTPException(status_code=400, detail="Invalid key format. Use key_id:secret")
    key_id, raw_secret = x_api_key.split(":", 1)

    # Try all workspaces to find the key
    workspaces = workspace_mgr.list_workspaces()
    found_key = None
    for ws in workspaces:
        auth = _get_auth_service(ws.workspace_id)
        key = auth._store.verify(raw_secret, key_id)
        if key:
            found_key = key
            break

    if not found_key:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    return found_key.to_dict()


# =============================================================================
# Dashboard Endpoint
# =============================================================================

@router.get("/dashboard")
async def get_dashboard():
    """Serve the real-time web dashboard."""
    import inspect
    from pathlib import Path
    # Find dashboard file relative to collaboration package
    from collaboration import __path__ as collab_paths
    collab_dir = Path(collab_paths[0])
    dashboard_path = collab_dir.parent / "dashboard" / "index.html"
    if not dashboard_path.exists():
        raise HTTPException(status_code=404, detail="Dashboard not found")
    from fastapi.responses import FileResponse
    return FileResponse(str(dashboard_path), media_type="text/html")


@router.get("/sse")
async def sse_endpoint():
    """SSE (Server-Sent Events) endpoint for real-time collaboration updates.

    Clients receive events as SSE stream. Each event has a named event type
    (e.g. 'orchestration.started', 'subtask.completed') so the client can
    listen for specific event types via EventSource.

    Alternative to WebSocket with simpler browser integration.
    """
    cid, queue = _sse_manager.connect()

    async def event_stream():
        async for message in _sse_manager.event_generator(cid, queue):
            yield message
        _sse_manager.disconnect(cid)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# =============================================================================
# Orchestration Lifecycle Endpoints
# =============================================================================

@router.post("/orchestrations")
async def create_orchestration(data: dict):
    """Create a new task orchestration."""
    mgr = _get_orch_mgr()
    from collaboration.models import Task, Priority, TaskStatus
    task = Task(
        task_id=f"task_{uuid().hex[:8]}",
        workspace_id=data.get("workspace_id", "default"),
        title=data.get("title", "Untitled"),
        description=data.get("description", ""),
        status=TaskStatus.PENDING,
        priority=Priority(data.get("priority", "medium")),
    )
    orch = mgr.create_orchestration(task)
    return orch.to_dict()


@router.post("/orchestrations/{orch_id}/start")
async def start_orchestration(orch_id: str):
    """Start an orchestration (transition from PLANNING to EXECUTING)."""
    mgr = _get_orch_mgr()
    from collaboration.models import OrchestrationPhase
    mgr.update_phase(orch_id, OrchestrationPhase.EXECUTING)
    orch = mgr.get_orchestration(orch_id)
    if not orch:
        raise HTTPException(status_code=404, detail="Orchestration not found")
    return orch.to_dict()


@router.post("/orchestrations/{orch_id}/phase")
async def update_orchestration_phase(orch_id: str, phase: str):
    """Update orchestration phase."""
    mgr = _get_orch_mgr()
    from collaboration.models import OrchestrationPhase
    try:
        mgr.update_phase(orch_id, OrchestrationPhase(phase))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid phase: {phase}")
    orch = mgr.get_orchestration(orch_id)
    if not orch:
        raise HTTPException(status_code=404, detail="Orchestration not found")
    return orch.to_dict()


# =============================================================================
# Multi-Agent Protocol Endpoints (messages, sessions, distributions)
# =============================================================================

@router.post("/messages")
async def send_message(data: MessageSendRequest, workspace_id: str = "default"):
    """Send a message from one agent to another or broadcast."""
    from collaboration.protocol import MultiAgentProtocol
    proto = MultiAgentProtocol(workspace_id)
    msg = proto.send_message(
        sender_id=data.payload.get("sender_id", "system"),
        receiver_id=data.receiver_id,
        msg_type=data.msg_type,
        payload=data.payload,
        session_id=data.session_id,
        ttl_seconds=data.ttl_seconds,
    )
    return {
        "msg_id": msg.msg_id,
        "status": msg.status.value if hasattr(msg.status, "value") else msg.status,
        "timestamp": msg.timestamp,
    }


@router.get("/messages/pending")
async def get_pending_messages(agent_id: str, workspace_id: str = "default"):
    """Get pending messages for an agent."""
    from collaboration.protocol import MultiAgentProtocol
    proto = MultiAgentProtocol(workspace_id)
    msgs = proto.get_pending_messages(agent_id)
    return {"messages": [m.to_dict() for m in msgs]}


@router.post("/messages/{msg_id}/ack")
async def acknowledge_message(msg_id: str, agent_id: str, workspace_id: str = "default"):
    """Acknowledge a message."""
    from collaboration.protocol import MultiAgentProtocol
    proto = MultiAgentProtocol(workspace_id)
    ok = proto.acknowledge_message(msg_id, agent_id)
    return {"success": ok}


@router.post("/sessions")
async def create_session(data: SessionCreateRequest, workspace_id: str = "default"):
    """Create a new collaborative session."""
    from collaboration.protocol import MultiAgentProtocol
    proto = MultiAgentProtocol(workspace_id)
    session = proto.create_session(data.participants, data.context)
    return session.to_dict()


@router.get("/sessions")
async def list_sessions(workspace_id: str = "default", status: Optional[str] = None):
    """List sessions, optionally filtered by status."""
    from collaboration.protocol import MultiAgentProtocol
    from collaboration.models import SessionStatus
    proto = MultiAgentProtocol(workspace_id)
    sess_status = SessionStatus(status) if status else None
    sessions = proto.list_sessions(status=sess_status)
    return {"sessions": [s.to_dict() for s in sessions]}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, workspace_id: str = "default"):
    """Get a session by ID."""
    from collaboration.protocol import MultiAgentProtocol
    proto = MultiAgentProtocol(workspace_id)
    session = proto.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.to_dict()


@router.post("/sessions/{session_id}/end")
async def end_session(session_id: str, workspace_id: str = "default"):
    """End a session."""
    from collaboration.protocol import MultiAgentProtocol
    proto = MultiAgentProtocol(workspace_id)
    ok = proto.end_session(session_id)
    return {"success": ok}


@router.post("/distributions")
async def distribute_task(data: DistributionCreateRequest, workspace_id: str = "default"):
    """Distribute a task to agents based on delegation policy."""
    from collaboration.protocol import MultiAgentProtocol
    from collaboration.models import DelegationPolicy
    proto = MultiAgentProtocol(workspace_id)
    policy = DelegationPolicy(
        type=data.policy_type or "capability_match",
        min_confidence=data.policy_min_confidence or 0.3,
    )
    dist = proto.distribute_task(
        task_id=data.task_id,
        description=data.description,
        policy=policy,
        required_capabilities=data.required_capabilities,
    )
    return dist.to_dict()


@router.get("/distributions/{distribution_id}")
async def get_distribution(distribution_id: str, workspace_id: str = "default"):
    """Get a distribution by ID."""
    from collaboration.protocol import MultiAgentProtocol
    proto = MultiAgentProtocol(workspace_id)
    dist = proto.get_distribution(distribution_id)
    if not dist:
        raise HTTPException(status_code=404, detail="Distribution not found")
    return dist.to_dict()


@router.post("/distributions/{distribution_id}/assign")
async def assign_distribution(
    distribution_id: str,
    data: DistributionAssignRequest,
    workspace_id: str = "default",
):
    """Assign a distributed task to a specific agent."""
    from collaboration.protocol import MultiAgentProtocol
    proto = MultiAgentProtocol(workspace_id)
    ok = proto.assign_to_agent(distribution_id, data.agent_id)
    return {"success": ok}


@router.get("/capabilities/match")
async def match_capabilities(
    query: str,
    required_capabilities: str,  # comma-separated
    min_confidence: float = 0.3,
    workspace_id: str = "default",
):
    """Match agents by their registered capabilities."""
    from collaboration.protocol import MultiAgentProtocol
    proto = MultiAgentProtocol(workspace_id)
    caps = [c.strip() for c in required_capabilities.split(",") if c.strip()]
    result = proto.match_capabilities(query, caps, min_confidence)
    return result.to_dict()


# =============================================================================
# Plugin/Hook Management Endpoints
# =============================================================================

@router.get("/plugins")
async def list_plugins(workspace_id: str = "default"):
    """List all registered plugins."""
    from collaboration.plugin_system import get_registry
    registry = get_registry(workspace_id)
    plugins = list(registry._plugins.values())
    return {"plugins": [{"name": p.name, "hooks": p.hooks, "enabled": p.enabled, "config": p.config} for p in plugins]}


@router.post("/plugins")
async def register_plugin(data: PluginRegisterRequest, workspace_id: str = "default"):
    """Register a new plugin."""
    from collaboration.plugin_system import get_registry, Plugin
    registry = get_registry(workspace_id)
    plugin = Plugin(
        name=data.name,
        description=data.description or "",
        hooks=data.hooks,
        config=data.config or {},
    )
    registry.register(plugin)
    return {"success": True, "plugin_name": data.name}


@router.delete("/plugins/{plugin_name}")
async def unregister_plugin(plugin_name: str, workspace_id: str = "default"):
    """Unregister a plugin."""
    from collaboration.plugin_system import get_registry
    registry = get_registry(workspace_id)
    ok = registry.unregister(plugin_name)
    return {"success": ok}


@router.patch("/plugins/{plugin_name}/enable")
async def toggle_plugin(plugin_name: str, enabled: bool, workspace_id: str = "default"):
    """Enable or disable a plugin."""
    from collaboration.plugin_system import get_registry
    registry = get_registry(workspace_id)
    if enabled:
        ok = registry.enable(plugin_name)
    else:
        ok = registry.disable(plugin_name)
    return {"success": ok}


@router.get("/hooks/events")
async def list_hook_events():
    """List all available hook event types."""
    from collaboration.models import HookEvent
    return {"events": [e.value for e in HookEvent]}


@router.get("/hooks")
async def list_subscriptions(workspace_id: str = "default"):
    """List all hook subscriptions for a workspace."""
    from collaboration.plugin_system import get_registry
    registry = get_registry(workspace_id)
    subs = []
    for event_name, handlers in registry._subscribers.items():
        for handler in handlers:
            subs.append({"event": event_name, "handler": str(handler)})
    return {"subscriptions": subs}


@router.post("/hooks/subscribe")
async def subscribe_to_hook(data: HookSubscribeRequest, workspace_id: str = "default"):
    """Subscribe to a hook event.

    Note: This registers an in-process callback. For HTTP callbacks,
    use the plugin system with a custom config.
    """
    from collaboration.plugin_system import get_registry
    registry = get_registry(workspace_id)

    def inline_handler(event_data: dict):
        _log.info(f"Hook triggered: {data.event} -> {event_data}")

    ok = registry.subscribe(data.event, inline_handler)
    return {"success": ok}


# =============================================================================
# SSE Stream Endpoints (workspace-scoped with filtering and cursor)
# =============================================================================

@router.get("/events")
async def sse_events_endpoint(
    workspace_id: Optional[str] = None,
    types: Optional[str] = None,  # comma-separated
    cursor: Optional[int] = None,
    timeout: int = 60,
):
    """SSE stream with workspace scoping, event filtering, and reconnect cursor.

    Query params:
    - workspace_id: filter events by workspace (omit for global)
    - types: comma-separated event types (e.g., task.created,agent.registered)
    - cursor: resume from event seq (for reconnect)
    - timeout: client disconnect timeout in seconds (default 60, max 300)
    """
    if timeout > 300:
        timeout = 300

    event_types = None
    if types:
        event_types = set(types.split(","))

    async def event_generator():
        bus = get_event_bus()
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=100)
        counter = 0

        async def on_event(event):
            nonlocal counter
            # Filter by workspace
            if workspace_id and event.workspace_id != workspace_id:
                return
            # Filter by event type
            event_type_val = event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)
            if event_types and event_type_val not in event_types:
                return
            # Skip events before cursor
            counter += 1
            if cursor and counter <= cursor:
                return
            event_dict = event.to_dict()
            event_dict["seq"] = counter
            try:
                queue.put_nowait(event_dict)
            except asyncio.QueueFull:
                pass

        await bus.subscribe(on_event, workspace_id=None)

        last_heartbeat = 0
        try:
            while True:
                try:
                    event_data = await asyncio.wait_for(queue.get(), timeout=timeout)
                    event_type_val = event_data.get("event_type", "message")
                    yield f"event: {event_type_val}\nid: {event_data.get('seq', 0)}\ndata: {json.dumps(event_data)}\n\n"
                    last_heartbeat = 0
                except asyncio.TimeoutError:
                    last_heartbeat += timeout
                    if last_heartbeat >= 60:
                        break
                    yield f": heartbeat\n\n"
        except GeneratorExit:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/workspaces/{ws_id}/events")
async def sse_workspace_events(
    ws_id: str,
    types: Optional[str] = None,
    cursor: Optional[int] = None,
    timeout: int = 60,
):
    """Workspace-scoped SSE stream."""
    if timeout > 300:
        timeout = 300

    event_types = None
    if types:
        event_types = set(types.split(","))

    async def event_generator():
        bus = get_event_bus()
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=100)
        counter = 0

        async def on_event(event):
            nonlocal counter
            if event.workspace_id != ws_id:
                return
            event_type_val = event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)
            if event_types and event_type_val not in event_types:
                return
            counter += 1
            if cursor and counter <= cursor:
                return
            event_dict = event.to_dict()
            event_dict["seq"] = counter
            try:
                queue.put_nowait(event_dict)
            except asyncio.QueueFull:
                pass

        await bus.subscribe(on_event, workspace_id=None)

        last_heartbeat = 0
        try:
            while True:
                try:
                    event_data = await asyncio.wait_for(queue.get(), timeout=timeout)
                    event_type_val = event_data.get("event_type", "message")
                    yield f"event: {event_type_val}\nid: {event_data.get('seq', 0)}\ndata: {json.dumps(event_data)}\n\n"
                    last_heartbeat = 0
                except asyncio.TimeoutError:
                    last_heartbeat += timeout
                    if last_heartbeat >= 60:
                        break
                    yield f": heartbeat\n\n"
        except GeneratorExit:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
                    agent_registry.update_status(agent_id, AgentStatus(status))
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
                            task_mgr.start_task(task_id, agent_id)
                    elif action == "complete":
                        task_mgr.complete_task(task_id)
                    elif action == "fail":
                        task_mgr.fail_task(task_id, data.get("error", "Unknown"))
                    
                    await websocket.send_json({
                        "type": "task_update",
                        "payload": {"task_id": task_id, "action": action}
                    })
    
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        _log.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)
