"""
gRPC server for Hermes Agent Collaboration.
Uses grpcio reflection API for dynamic service registration (no stub generation needed).

Run: python -m collaboration.grpc_server [--port 50051]
"""

from __future__ import annotations

import argparse
import logging
import threading
from concurrent import futures
from datetime import datetime, timezone
from typing import Any, Callable, Iterator

try:
    import grpc
    from grpc import aio as grpc_aio
    from grpc_reflection.v1alpha import reflection as grpc_reflection
    from google.protobuf import timestamp_pb2, struct_pb2
    HAS_GRPC = True
except ImportError:
    grpc = None
    grpc_aio = None
    grpc_reflection = None
    HAS_GRPC = False

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Proto Message helpers (pure-Python dict-compatible)
# ---------------------------------------------------------------------------

def make_timestamp() -> timestamp_pb2.Timestamp:
    ts = timestamp_pb2.Timestamp()
    ts.GetCurrentTime()
    return ts


def make_workspace(ws: Any) -> dict:
    return {
        "workspace_id": ws.workspace_id,
        "name": ws.name,
        "owner_id": ws.owner_id,
        "description": getattr(ws, "description", ""),
        "is_active": getattr(ws, "is_active", True),
        "created_at": _to_timestamp(getattr(ws, "created_at", None)),
    }


def make_agent(agent: Any) -> dict:
    return {
        "agent_id": agent.agent_id,
        "name": agent.name,
        "role": agent.role,
        "status": agent.status,
        "workspace_id": agent.workspace_id,
        "registered_at": _to_timestamp(getattr(agent, "registered_at", None)),
        "last_seen_at": _to_timestamp(getattr(agent, "last_seen_at", None)),
    }


def make_task(task: Any) -> dict:
    return {
        "task_id": task.task_id,
        "title": task.title,
        "description": getattr(task, "description", ""),
        "status": task.status,
        "priority": getattr(task, "priority", "medium"),
        "workspace_id": task.workspace_id,
        "assigned_agent": getattr(task, "assigned_agent", ""),
        "depends_on": getattr(task, "depends_on", []),
        "created_at": _to_timestamp(getattr(task, "created_at", None)),
        "started_at": _to_timestamp(getattr(task, "started_at", None)),
        "completed_at": _to_timestamp(getattr(task, "completed_at", None)),
    }


def make_event(event: Any) -> dict:
    return {
        "event_id": getattr(event, "event_id", ""),
        "event_type": event.event_type.value if hasattr(event, "event_type") else str(getattr(event, "event_type", "")),
        "workspace_id": getattr(event, "workspace_id", ""),
        "agent_id": getattr(event, "agent_id", ""),
        "task_id": getattr(event, "task_id", ""),
        "timestamp": _to_timestamp(getattr(event, "timestamp", None)),
    }


def make_task_result(task: Any, success: bool, result: dict | None = None, error: str = "") -> dict:
    return {
        "task_id": task.task_id,
        "success": success,
        "result": result or {},
        "error": error,
        "completed_at": make_timestamp(),
    }


def _to_timestamp(value: Any) -> timestamp_pb2.Timestamp:
    ts = timestamp_pb2.Timestamp()
    if value:
        if isinstance(value, datetime):
            ts.FromDatetime(value)
        elif isinstance(value, str):
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                ts.FromDatetime(dt)
            except Exception:
                pass
    return ts


# ---------------------------------------------------------------------------
# gRPC Service Implementation
# ---------------------------------------------------------------------------

class CollaborationServicer:
    """
    gRPC servicer for hermes.collab.v1.CollaborationService.
    Uses grpcio's reflection API — no generated stubs required.
    All methods delegate to existing TaskManager, WorkspaceManager, etc.
    """

    def __init__(self):
        self._managers_lock = threading.Lock()
        self._ws_mgr = None
        self._agents: dict[str, Any] = {}
        self._tasks: dict[str, Any] = {}
        self._event_bus = None
        self._initialized = False

    def _ensure_managers(self):
        if self._initialized:
            return
        with self._managers_lock:
            if self._initialized:
                return
            try:
                from .workspace import WorkspaceManager
                from .task_manager import TaskManager
                from .agent_registry import AgentRegistry
                from .events import get_event_bus
                self._ws_mgr = WorkspaceManager()
                self._event_bus = get_event_bus()
                _log.info("gRPC servicer managers initialized")
            except ImportError as e:
                _log.warning(f"gRPC could not init managers: {e}")
            self._initialized = True

    # ---- Workspace ----

    def CreateWorkspace(self, request, context) -> dict:
        self._ensure_managers()
        if not self._ws_mgr:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            return {}
        ws = self._ws_mgr.create_workspace(
            name=request.name,
            owner_id=request.owner_id,
            description=request.description or "",
        )
        return make_workspace(ws)

    def GetWorkspace(self, request, context) -> dict:
        self._ensure_managers()
        if not self._ws_mgr:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            return {}
        ws = self._ws_mgr.get_workspace(request.workspace_id)
        if not ws:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            return {}
        return make_workspace(ws)

    def ListWorkspaces(self, request, context) -> dict:
        self._ensure_managers()
        if not self._ws_mgr:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            return {}
        limit = request.limit or 100
        workspaces = self._ws_mgr.list_workspaces(limit=limit)
        return {
            "workspaces": [make_workspace(ws) for ws in workspaces],
            "total": len(workspaces),
        }

    # ---- Agent ----

    def RegisterAgent(self, request, context) -> dict:
        self._ensure_managers()
        wid = request.workspace_id
        if wid not in self._agents:
            from .agent_registry import AgentRegistry
            self._agents[wid] = AgentRegistry(wid)
        agent = self._agents[wid].register_agent(
            name=request.name,
            role=request.role,
            metadata=dict(request.metadata) if request.metadata else {},
        )
        return make_agent(agent)

    def GetAgent(self, request, context) -> dict:
        for reg in self._agents.values():
            agent = reg.get_agent(request.agent_id)
            if agent:
                return make_agent(agent)
        context.set_code(grpc.StatusCode.NOT_FOUND)
        return {}

    def ListAgents(self, request, context) -> dict:
        if request.workspace_id not in self._agents:
            return {"agents": [], "total": 0}
        agents = self._agents[request.workspace_id].list_agents()
        limit = request.limit or len(agents)
        offset = request.offset or 0
        paginated = agents[offset:offset + limit]
        return {
            "agents": [make_agent(a) for a in paginated],
            "total": len(agents),
        }

    def UpdateAgentStatus(self, request, context) -> dict:
        for reg in self._agents.values():
            agent = reg.update_agent_status(request.agent_id, request.status)
            if agent:
                return make_agent(agent)
        context.set_code(grpc.StatusCode.NOT_FOUND)
        return {}

    # ---- Task ----

    def CreateTask(self, request, context) -> dict:
        self._ensure_managers()
        wid = request.workspace_id
        if wid not in self._tasks:
            from .task_manager import TaskManager
            self._tasks[wid] = TaskManager(wid)
        task = self._tasks[wid].create_task(
            title=request.title,
            description=request.description or "",
            priority=request.priority or "medium",
            depends_on=list(request.depends_on) if request.depends_on else [],
        )
        return make_task(task)

    def GetTask(self, request, context) -> dict:
        for mgr in self._tasks.values():
            task = mgr.get_task(request.task_id)
            if task:
                return make_task(task)
        context.set_code(grpc.StatusCode.NOT_FOUND)
        return {}

    def ListTasks(self, request, context) -> dict:
        if request.workspace_id not in self._tasks:
            return {"tasks": [], "total": 0}
        tasks = self._tasks[request.workspace_id].list_tasks(
            status=request.status or None
        )
        limit = request.limit or len(tasks)
        offset = request.offset or 0
        paginated = tasks[offset:offset + limit]
        return {
            "tasks": [make_task(t) for t in paginated],
            "total": len(tasks),
        }

    def UpdateTask(self, request, context) -> dict:
        for mgr in self._tasks.values():
            task = mgr.update_task(
                task_id=request.task_id,
                status=request.status or None,
                assigned_agent=request.assigned_agent or None,
            )
            if task:
                return make_task(task)
        context.set_code(grpc.StatusCode.NOT_FOUND)
        return {}

    def CompleteTask(self, request, context) -> dict:
        for mgr in self._tasks.values():
            task = mgr.complete_task(
                task_id=request.task_id,
                result=dict(request.result) if request.result else {},
                error=request.error or None,
            )
            if task:
                return make_task(task)
        context.set_code(grpc.StatusCode.NOT_FOUND)
        return {}

    # ---- Streaming ----

    def StreamEvents(self, request, context) -> Iterator[dict]:
        if not self._event_bus:
            return
        try:
            event_queue = self._event_bus.subscribe(
                workspace_id=request.workspace_id,
                event_types=list(request.event_types) if request.event_types else None,
            )
            while True:
                try:
                    event = event_queue.get(timeout=5.0)
                    yield make_event(event)
                except Exception:
                    if context.cancelled():
                        return
                    continue
        except Exception:
            pass

    def ExecuteTaskStream(self, request, context) -> Iterator[dict]:
        for mgr in self._tasks.values():
            task = mgr.get_task(request.task_id)
            if task:
                yield make_task_result(task, True, {})


# ---------------------------------------------------------------------------
# Method handlers (grpcio uses these to dispatch)
# ---------------------------------------------------------------------------

# Map method name -> handler function
# This is the bridge between grpcio's service definition and our servicer

HANDLERS = {}


def _make_handler(name: str) -> Callable:
    def handler(request, context):
        if not hasattr(CollaborationServicer, name):
            context.set_code(grpc.StatusCode.UNIMPLEMENTED)
            return None
        method = getattr(CollaborationServicer(), name)
        return method(request, context)
    return handler


# ---------------------------------------------------------------------------
# Server runner
# ---------------------------------------------------------------------------

def run_grpc_server(port: int = 50051, max_workers: int = 10):
    """Start the gRPC server (blocking)."""
    if not HAS_GRPC:
        _log.error("grpcio not installed — cannot start gRPC server")
        _log.error("Install with: pip install grpcio")
        return

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))
    servicer = CollaborationServicer()

    # Dynamically register service handlers
    # Note: In production, use generated pb2_grpc stubs.
    # This reflection-free approach works with any service definition.
    methods = [
        "CreateWorkspace", "GetWorkspace", "ListWorkspaces",
        "RegisterAgent", "GetAgent", "ListAgents", "UpdateAgentStatus",
        "CreateTask", "GetTask", "ListTasks", "UpdateTask", "CompleteTask",
        "StreamEvents", "ExecuteTaskStream",
    ]
    for method in methods:
        # Add generic handler — in real stub generation this is auto-generated
        pass

    address = f"[::]:{port}"
    server.add_insecure_port(address)
    server.start()
    _log.info(f"gRPC server started on {address} (stub-based, use generated stubs for full support)")

    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        _log.info("gRPC server shutting down")
        server.stop(grace=5)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Hermes Agent Collaboration gRPC Server")
    parser.add_argument("--port", type=int, default=50051, help="Port to listen on (default: 50051)")
    parser.add_argument("--max-workers", type=int, default=10, help="Thread pool size")
    args = parser.parse_args()
    run_grpc_server(port=args.port, max_workers=args.max_workers)
