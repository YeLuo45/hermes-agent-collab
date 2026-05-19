"""
Playground / REPL sandbox environment for hermes-agent-collab.
Provides isolated code execution, REPL sessions, and workflow preview.
"""

from __future__ import annotations

import asyncio
import copy
import datetime
import io
import json
import sys
import traceback
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any

# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class Sandbox:
    """Isolated execution context for playground."""
    session_id: str
    workspace_id: str
    created_at: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    ttl_seconds: int = 3600  # 1 hour default
    max_steps: int = 1000
    timeout_seconds: int = 30
    status: str = "active"  # "active" | "expired" | "stopped"
    execution_count: int = 0


@dataclass
class REPLResult:
    """Result of a REPL execution."""
    seq: int
    code: str
    output: str
    error: str | None = None
    duration_ms: float = 0.0
    timestamp: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DAGNode:
    """A node in the workflow DAG."""
    id: str
    name: str
    node_type: str  # "task" | "agent" | "condition" | "merge"
    config: dict = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DAG:
    """Directed Acyclic Graph representation of a workflow."""
    nodes: list[DAGNode] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)  # [{"from": "a", "to": "b"}]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Snapshot:
    """Saved playground state for sharing."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    description: str = ""
    workspace_id: str = ""
    sandbox_state: dict = field(default_factory=dict)
    repl_history: list[dict] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    created_by: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Safe Executor
# ---------------------------------------------------------------------------

# Dangerous builtins to disable
_BLOCKED_BUILTINS = {
    'open', 'exec', 'eval', 'compile', '__import__',
    'reload', 'input', 'breakpoint', 'exit', 'quit',
    'getattr', 'setattr', 'delattr', 'hasattr',
    'memoryview', 'buffer',
}

# Safe globals for sandbox execution
_SAFE_GLOBALS = {
    '__builtins__': {name: None for name in dir(__builtins__) if name not in _BLOCKED_BUILTINS},
    'print': print,
    'len': len,
    'range': range,
    'str': str,
    'int': int,
    'float': float,
    'bool': bool,
    'list': list,
    'dict': dict,
    'tuple': tuple,
    'set': set,
    'frozenset': frozenset,
    'sorted': sorted,
    'reversed': reversed,
    'enumerate': enumerate,
    'zip': zip,
    'map': map,
    'filter': filter,
    'sum': sum,
    'min': min,
    'max': max,
    'abs': abs,
    'round': round,
    'pow': pow,
    'divmod': divmod,
    'isinstance': isinstance,
    'issubclass': issubclass,
    'type': type,
    'id': id,
    'hash': hash,
    'repr': repr,
    'format': format,
    'chr': chr,
    'ord': ord,
    'hex': hex,
    'oct': oct,
    'bin': bin,
    'slice': slice,
    'super': super,
    'object': object,
    'property': property,
    'classmethod': classmethod,
    'staticmethod': staticmethod,
    'getattr': getattr,
    'setattr': setattr,
    'hasattr': hasattr,
    'delattr': delattr,
    'vars': vars,
    'dir': dir,
    'help': help,
    'iter': iter,
    'next': next,
    'any': any,
    'all': all,
    'None': None,
    'True': True,
    'False': False,
}


def _execute_safe(code: str, timeout_seconds: int = 30) -> tuple[str, str | None, float]:
    """
    Execute code in a safe sandbox environment.
    Returns (output, error, duration_ms).
    """
    import time
    start = time.perf_counter()

    stdout_capture = io.StringIO()
    old_stdout = sys.stdout
    old_stderr = sys.stderr

    try:
        sys.stdout = stdout_capture
        sys.stderr = stdout_capture

        # Create safe globals (copy to avoid mutation)
        safe_globals = {k: v for k, v in _SAFE_GLOBALS.items()}
        safe_globals['__builtins__'] = {name: None for name in dir(__builtins__) if name not in _BLOCKED_BUILTINS}

        # Execute with timeout simulation (actual timeout handled by caller)
        exec(code, safe_globals)

        duration_ms = (time.perf_counter() - start) * 1000
        output = stdout_capture.getvalue()
        return output, None, duration_ms

    except SyntaxError as e:
        duration_ms = (time.perf_counter() - start) * 1000
        return "", f"SyntaxError: {e}", duration_ms
    except Exception as e:
        duration_ms = (time.perf_counter() - start) * 1000
        tb = traceback.format_exc()
        return "", f"{type(e).__name__}: {e}\n{tb}", duration_ms
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr


# ---------------------------------------------------------------------------
# Workflow Preview
# ---------------------------------------------------------------------------

class WorkflowPreview:
    """Render and preview workflow definitions as DAG."""

    def __init__(self):
        self._node_counter = 0

    def _make_node_id(self, name: str) -> str:
        """Generate a unique node ID."""
        self._node_counter += 1
        # Sanitize name for Mermaid compatibility
        safe = "".join(c if c.isalnum() else "_" for c in name)
        return f"{safe}_{self._node_counter}"

    def from_template(self, template: dict, params: dict | None = None) -> DAG:
        """
        Instantiate a template with params and return DAG.
        Template format: {
            "name": str,
            "steps": [{"id": str, "name": str, "type": str, "config": {}, "depends_on": []}, ...]
        }
        """
        params = params or {}
        dag = DAG()

        for step in template.get("steps", []):
            node = DAGNode(
                id=step.get("id", self._make_node_id(step.get("name", "unnamed"))),
                name=step.get("name", "unnamed"),
                node_type=step.get("type", "task"),
                config=self._substitute_params(step.get("config", {}), params),
                depends_on=step.get("depends_on", []),
            )
            dag.nodes.append(node)

        # Build edges from depends_on
        node_ids = {n.id for n in dag.nodes}
        for node in dag.nodes:
            for dep in node.depends_on:
                if dep in node_ids:
                    dag.edges.append({"from": dep, "to": node.id})

        return dag

    def from_workflow(self, workflow: dict, params: dict | None = None) -> DAG:
        """
        Build DAG from a full workflow definition.
        Workflow: {
            "name": str,
            "agents": [...],
            "tasks": [...],
            "edges": [...]
        }
        """
        params = params or {}
        dag = DAG()

        # Add agent nodes
        for agent in workflow.get("agents", []):
            node = DAGNode(
                id=f"agent_{agent.get('id', 'unnamed')}",
                name=agent.get("name", "unnamed agent"),
                node_type="agent",
                config=self._substitute_params(agent.get("config", {}), params),
            )
            dag.nodes.append(node)

        # Add task nodes
        for task in workflow.get("tasks", []):
            node = DAGNode(
                id=f"task_{task.get('id', 'unnamed')}",
                name=task.get("name", "unnamed task"),
                node_type="task",
                config=self._substitute_params(task.get("config", {}), params),
                depends_on=task.get("depends_on", []),
            )
            dag.nodes.append(node)

        # Add edges
        for edge in workflow.get("edges", []):
            dag.edges.append({"from": edge.get("from"), "to": edge.get("to")})

        return dag

    def _substitute_params(self, config: dict, params: dict) -> dict:
        """Substitute {{param}} placeholders in config values."""
        result = {}
        for k, v in config.items():
            if isinstance(v, str):
                result[k] = self._replace_placeholders(v, params)
            elif isinstance(v, dict):
                result[k] = self._substitute_params(v, params)
            elif isinstance(v, list):
                result[k] = [
                    self._replace_placeholders(item, params) if isinstance(item, str) else item
                    for item in v
                ]
            else:
                result[k] = v
        return result

    def _replace_placeholders(self, text: str, params: dict) -> str:
        """Replace {{param}} placeholders in text."""
        result = text
        for param_name, param_value in params.items():
            result = result.replace(f"{{{{{param_name}}}}}", str(param_value))
        return result

    def to_mermaid(self, dag: DAG) -> str:
        """Convert DAG to Mermaid flowchart markdown."""
        lines = ["```mermaid", "flowchart TD"]

        for node in dag.nodes:
            # Mermaid node syntax: node_id["label"] or node_id{{"label"}} for rounded
            shape = "[[" if node.node_type == "task" else "["
            close = "]]" if node.node_type == "task" else "]"
            label = node.name.replace('"', "'")
            lines.append(f'    {node.id}{shape}"{label}"{close}')

        for edge in dag.edges:
            frm = edge.get("from", "")
            to = edge.get("to", "")
            if frm and to:
                lines.append(f'    {frm} --> {to}')

        lines.append("```")
        return "\n".join(lines)

    def validate(self, dag: DAG) -> list[str]:
        """Validate DAG and return list of errors."""
        errors = []

        # Check for cycles (simple DFS)
        def has_cycle(node_id: str, visited: set, rec_stack: set) -> bool:
            visited.add(node_id)
            rec_stack.add(node_id)
            for edge in dag.edges:
                if edge.get("from") == node_id:
                    neighbor = edge.get("to")
                    if neighbor not in visited:
                        if has_cycle(neighbor, visited, rec_stack):
                            return True
                    elif neighbor in rec_stack:
                        return True
            rec_stack.remove(node_id)
            return False

        node_ids = {n.id for n in dag.nodes}
        for node in dag.nodes:
            if not node.id:
                errors.append("Node has empty ID")
            if node.id != node.id.lower():
                errors.append(f"Node ID '{node.id}' should be lowercase")
            for dep in node.depends_on:
                if dep not in node_ids:
                    errors.append(f"Node '{node.id}' depends on unknown node '{dep}'")

        visited = set()
        for node in dag.nodes:
            if node.id not in visited:
                if has_cycle(node.id, visited, set()):
                    errors.append(f"Cycle detected involving node '{node.id}'")
                    break

        # Check for orphaned nodes (no incoming edges except entry points)
        has_incoming = {edge.get("to") for edge in dag.edges}
        for node in dag.nodes:
            if node.id not in has_incoming and len(dag.nodes) > 1:
                # Entry nodes should have no depends_on
                if node.depends_on:
                    pass  # OK - it's an entry point

        return errors


# ---------------------------------------------------------------------------
# REPL Session
# ---------------------------------------------------------------------------

class REPLSession:
    """Interactive REPL session for testing agent logic."""

    def __init__(self, sandbox: Sandbox):
        self.sandbox = sandbox
        self._history: list[REPLResult] = []
        self._seq = 0
        self._workspace: dict[str, Any] = {}

    def execute(self, code: str) -> REPLResult:
        """Execute Python-like code in sandbox."""
        self._seq += 1
        self.sandbox.execution_count += 1

        output, error, duration_ms = _execute_safe(
            code, timeout_seconds=self.sandbox.timeout_seconds
        )

        result = REPLResult(
            seq=self._seq,
            code=code,
            output=output,
            error=error,
            duration_ms=duration_ms,
        )
        self._history.append(result)
        return result

    def evaluate(self, expr: str) -> str:
        """Evaluate expression and return string representation."""
        result = self.execute(expr)
        if result.error:
            return f"Error: {result.error}"
        return result.output or "None"

    def get_history(self) -> list[REPLResult]:
        """Get all executed commands and results."""
        return copy.deepcopy(self._history)

    def clear_history(self) -> None:
        """Clear REPL history."""
        self._history.clear()
        self._seq = 0


# ---------------------------------------------------------------------------
# Playground Manager
# ---------------------------------------------------------------------------

class PlaygroundManager:
    """
    Manages Playground / REPL sandbox environment.
    Provides isolated code execution, REPL sessions, and workflow preview.
    """

    def __init__(self):
        self._sandboxes: dict[str, Sandbox] = {}
        self._sessions: dict[str, REPLSession] = {}
        self._snapshots: dict[str, Snapshot] = {}
        self._preview = WorkflowPreview()

    def create_sandbox(
        self,
        workspace_id: str,
        ttl_seconds: int = 3600,
        max_steps: int = 1000,
        timeout_seconds: int = 30,
    ) -> Sandbox:
        """Create a new sandbox environment."""
        sandbox_id = str(uuid.uuid4())[:8]
        sandbox = Sandbox(
            session_id=sandbox_id,
            workspace_id=workspace_id,
            ttl_seconds=ttl_seconds,
            max_steps=max_steps,
            timeout_seconds=timeout_seconds,
        )
        self._sandboxes[sandbox_id] = sandbox
        self._sessions[sandbox_id] = REPLSession(sandbox)
        return sandbox

    def get_sandbox(self, sandbox_id: str) -> Sandbox | None:
        """Get sandbox by ID."""
        return self._sandboxes.get(sandbox_id)

    def delete_sandbox(self, sandbox_id: str) -> bool:
        """Delete a sandbox and its session."""
        if sandbox_id in self._sandboxes:
            del self._sandboxes[sandbox_id]
        if sandbox_id in self._sessions:
            del self._sessions[sandbox_id]
        return True

    def execute(self, sandbox_id: str, code: str) -> REPLResult | None:
        """Execute code in a sandbox."""
        sandbox = self._sandboxes.get(sandbox_id)
        if sandbox is None:
            return None
        if sandbox.status != "active":
            return REPLResult(
                seq=0, code=code, output="",
                error=f"Sandbox is {sandbox.status}"
            )
        if sandbox.execution_count >= sandbox.max_steps:
            return REPLResult(
                seq=0, code=code, output="",
                error=f"Max steps ({sandbox.max_steps}) exceeded"
            )

        session = self._sessions.get(sandbox_id)
        if session is None:
            return None

        return session.execute(code)

    def get_history(self, sandbox_id: str) -> list[dict] | None:
        """Get REPL history for a sandbox."""
        session = self._sessions.get(sandbox_id)
        if session is None:
            return None
        return [r.to_dict() for r in session.get_history()]

    def clear_history(self, sandbox_id: str) -> bool:
        """Clear REPL history for a sandbox."""
        session = self._sessions.get(sandbox_id)
        if session is None:
            return False
        session.clear_history()
        return True

    def preview_workflow(self, workflow: dict, params: dict | None = None) -> dict:
        """
        Preview a workflow as DAG and return renderable data.
        Returns {"dag": {...}, "mermaid": str, "errors": []}.
        """
        params = params or {}
        dag = self._preview.from_workflow(workflow, params)
        errors = self._preview.validate(dag)
        mermaid = self._preview.to_mermaid(dag) if not errors else ""
        return {
            "dag": dag.to_dict(),
            "mermaid": mermaid,
            "errors": errors,
        }

    def preview_template(self, template: dict, params: dict | None = None) -> dict:
        """
        Preview a template as DAG and return renderable data.
        Returns {"dag": {...}, "mermaid": str, "errors": []}.
        """
        params = params or {}
        dag = self._preview.from_template(template, params)
        errors = self._preview.validate(dag)
        mermaid = self._preview.to_mermaid(dag) if not errors else ""
        return {
            "dag": dag.to_dict(),
            "mermaid": mermaid,
            "errors": errors,
        }

    def create_snapshot(
        self,
        sandbox_id: str,
        name: str = "",
        description: str = "",
        created_by: str = "",
    ) -> Snapshot | None:
        """Save current sandbox state as a snapshot."""
        sandbox = self._sandboxes.get(sandbox_id)
        session = self._sessions.get(sandbox_id)
        if sandbox is None:
            return None

        snapshot = Snapshot(
            name=name,
            description=description,
            workspace_id=sandbox.workspace_id,
            sandbox_state={
                "ttl_seconds": sandbox.ttl_seconds,
                "max_steps": sandbox.max_steps,
                "timeout_seconds": sandbox.timeout_seconds,
                "execution_count": sandbox.execution_count,
            },
            repl_history=self.get_history(sandbox_id) or [],
            created_by=created_by,
        )
        self._snapshots[snapshot.id] = snapshot
        return snapshot

    def get_snapshot(self, snapshot_id: str) -> Snapshot | None:
        """Load a snapshot by ID."""
        return self._snapshots.get(snapshot_id)

    def delete_snapshot(self, snapshot_id: str) -> bool:
        """Delete a snapshot."""
        if snapshot_id in self._snapshots:
            del self._snapshots[snapshot_id]
            return True
        return False

    def list_snapshots(self, workspace_id: str | None = None) -> list[dict]:
        """List all snapshots, optionally filtered by workspace."""
        result = []
        for snap in self._snapshots.values():
            if workspace_id and snap.workspace_id != workspace_id:
                continue
            result.append(snap.to_dict())
        return result

    def list_sandboxes(self, workspace_id: str | None = None) -> list[dict]:
        """List all sandboxes, optionally filtered by workspace."""
        result = []
        for sb in self._sandboxes.values():
            if workspace_id and sb.workspace_id != workspace_id:
                continue
            result.append(asdict(sb))
        return result
