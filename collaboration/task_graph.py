"""
Task DAG (Directed Acyclic Graph) visualization API.
Provides task dependency graph building, topological sort, and execution planning.
"""

from __future__ import annotations

import uuid
from collections import deque
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class TaskGraphNode(BaseModel):
    task_id: str
    title: str
    status: TaskStatus
    assigned_agent: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    depends_on: list[str] = Field(default_factory=list)
    dependents: list[str] = Field(default_factory=list)

    class Config:
        use_enum_values = True


class TaskGraphEdge(BaseModel):
    from_task: str
    to_task: str
    edge_type: str = "dependency"


class TaskGraphStats(BaseModel):
    total_tasks: int
    pending_tasks: int
    running_tasks: int
    completed_tasks: int
    failed_tasks: int
    parallel_opportunities: int = 0
    critical_path_length: int = 0


class TaskGraphResponse(BaseModel):
    workspace_id: str
    nodes: list[TaskGraphNode]
    edges: list[TaskGraphEdge]
    stats: TaskGraphStats


class TopologicalSortResponse(BaseModel):
    sorted_task_ids: list[str]
    has_cycles: bool = False
    cycle_tasks: list[list[str]] = Field(default_factory=list)
    levels: list[list[str]] = Field(default_factory=list)


class ExecutionPhase(BaseModel):
    phase_id: int
    tasks: list[str]
    can_run_parallel: bool = True
    depends_on_phases: list[int] = Field(default_factory=list)


class ExecutionPlan(BaseModel):
    workspace_id: str
    phases: list[ExecutionPhase]
    estimated_duration_median: float = 0.0


class UpstreamDownstreamResponse(BaseModel):
    task_id: str
    upstream: list[TaskGraphNode]
    downstream: list[TaskGraphNode]


# ---------------------------------------------------------------------------
# Topological Sort (Kahn's algorithm)
# ---------------------------------------------------------------------------

class TopologicalSorter:
    """Kahn's algorithm for topological sorting with cycle detection."""

    def __init__(self, nodes: list[TaskGraphNode], edges: list[TaskGraphEdge]):
        self.nodes = {n.task_id: n for n in nodes}
        self.edges = edges
        self.graph: dict[str, list[str]] = {n.task_id: [] for n in nodes}
        self.reverse_graph: dict[str, list[str]] = {n.task_id: [] for n in nodes}

        for edge in edges:
            if edge.from_task in self.graph and edge.to_task in self.graph:
                self.graph[edge.from_task].append(edge.to_task)
                self.reverse_graph[edge.to_task].append(edge.from_task)

    def sort(self) -> TopologicalSortResponse:
        in_degree = {nid: 0 for nid in self.graph}
        for edges_from in self.graph.values():
            for target in edges_from:
                in_degree[target] += 1

        queue = deque([nid for nid, deg in in_degree.items() if deg == 0])
        sorted_ids: list[str] = []
        levels: list[list[str]] = []
        current_level = 0

        while queue:
            level_nodes = []
            for _ in range(len(queue)):
                node_id = queue.popleft()
                sorted_ids.append(node_id)
                level_nodes.append(node_id)

                for neighbor in self.graph[node_id]:
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        queue.append(neighbor)

            if level_nodes:
                levels.append(level_nodes)
                current_level += 1

        has_cycles = len(sorted_ids) < len(self.nodes)
        cycle_tasks: list[list[str]] = []
        if has_cycles:
            remaining = set(self.nodes.keys()) - set(sorted_ids)
            while remaining:
                start = remaining.pop()
                cycle = [start]
                visited = {start}
                current = start
                while True:
                    for neighbor in self.graph.get(current, []):
                        if neighbor in remaining or neighbor == start:
                            if neighbor == start:
                                cycle_tasks.append(cycle.copy())
                                remaining -= set(cycle)
                                break
                            elif neighbor not in visited:
                                cycle.append(neighbor)
                                visited.add(neighbor)
                                remaining.discard(neighbor)
                                current = neighbor
                                break
                    else:
                        remaining -= set(cycle)
                        break
                break

        return TopologicalSortResponse(
            sorted_task_ids=sorted_ids,
            has_cycles=has_cycles,
            cycle_tasks=cycle_tasks,
            levels=levels,
        )

    def compute_critical_path_length(self, durations: dict[str, float] | None = None) -> int:
        """Returns the length (node count) of the longest dependency chain."""
        if durations is None:
            durations = {nid: 1.0 for nid in self.nodes}

        est: dict[str, float] = {}
        sorted_result = self.sort()
        if sorted_result.has_cycles:
            return 0

        for level in sorted_result.levels:
            for task_id in level:
                max_pred_est = 0.0
                for pred in self.reverse_graph.get(task_id, []):
                    max_pred_est = max(max_pred_est, est.get(pred, 0.0))
                est[task_id] = max_pred_est + durations.get(task_id, 1.0)

        return int(max(est.values()) if est else 0)

    def parallel_opportunities(self) -> int:
        """Maximum number of tasks that can run in parallel at any level."""
        sorted_result = self.sort()
        if not sorted_result.levels:
            return 0
        return max(len(level) for level in sorted_result.levels)


# ---------------------------------------------------------------------------
# Task Graph Builder
# ---------------------------------------------------------------------------

class TaskGraphBuilder:
    """Builds TaskGraphResponse from workspace tasks stored in TaskManager."""

    def __init__(self, task_manager: Any):
        self.task_manager = task_manager

    def build(self, workspace_id: str) -> TaskGraphResponse:
        tasks = self.task_manager.list_tasks(workspace_id)

        nodes: list[TaskGraphNode] = []
        edges: list[TaskGraphEdge] = []
        dependent_map: dict[str, list[str]] = {}

        for task in tasks:
            task_id = task.get("id") or task.get("task_id")
            if not task_id:
                continue

            depends_on = task.get("depends_on", [])
            if isinstance(depends_on, str):
                depends_on = [depends_on] if depends_on else []

            node = TaskGraphNode(
                task_id=task_id,
                title=task.get("title", ""),
                status=TaskStatus(task.get("status", "pending")),
                assigned_agent=task.get("assigned_agent"),
                created_at=task.get("created_at", datetime.utcnow()),
                started_at=task.get("started_at"),
                completed_at=task.get("completed_at"),
                depends_on=depends_on,
                dependents=[],  # filled below
            )
            nodes.append(node)

            for dep_id in depends_on:
                edges.append(TaskGraphEdge(from_task=dep_id, to_task=task_id))
                dependent_map.setdefault(dep_id, []).append(task_id)

        for node in nodes:
            node.dependents = dependent_map.get(node.task_id, [])

        stats = self._compute_stats(nodes)

        return TaskGraphResponse(
            workspace_id=workspace_id,
            nodes=nodes,
            edges=edges,
            stats=stats,
        )

    def _compute_stats(self, nodes: list[TaskGraphNode]) -> TaskGraphStats:
        status_counts = {s: 0 for s in TaskStatus}
        for n in nodes:
            try:
                status_counts[n.status] += 1
            except Exception:
                pass

        edges = [TaskGraphEdge(from_task=n.task_id, to_task=d)
                 for n in nodes for d in n.depends_on]
        sorter = TopologicalSorter(nodes, edges)
        sorted_result = sorter.sort()
        parallel_opps = sorter.parallel_opportunities()
        crit_path = sorter.compute_critical_path_length()

        return TaskGraphStats(
            total_tasks=len(nodes),
            pending_tasks=status_counts.get(TaskStatus.PENDING, 0),
            running_tasks=status_counts.get(TaskStatus.RUNNING, 0),
            completed_tasks=status_counts.get(TaskStatus.COMPLETED, 0),
            failed_tasks=status_counts.get(TaskStatus.FAILED, 0),
            parallel_opportunities=parallel_opps,
            critical_path_length=crit_path,
        )

    def get_upstream(self, task_id: str) -> list[TaskGraphNode]:
        """Get all tasks this task depends on (upstream)."""
        tasks = self.task_manager.list_tasks("")
        task_map = {t.get("id") or t.get("task_id"): t for t in tasks}
        visited: set[str] = set()
        result: list[TaskGraphNode] = []

        def dfs(tid: str):
            if tid in visited:
                return
            visited.add(tid)
            t = task_map.get(tid)
            if not t:
                return
            depends_on = t.get("depends_on", [])
            for dep_id in depends_on:
                dfs(dep_id)
            node = TaskGraphNode(
                task_id=tid,
                title=t.get("title", ""),
                status=TaskStatus(t.get("status", "pending")),
                assigned_agent=t.get("assigned_agent"),
                created_at=t.get("created_at", datetime.utcnow()),
                started_at=t.get("started_at"),
                completed_at=t.get("completed_at"),
                depends_on=t.get("depends_on", []),
            )
            if node.task_id not in [r.task_id for r in result]:
                result.append(node)

        dfs(task_id)
        return result

    def get_downstream(self, task_id: str) -> list[TaskGraphNode]:
        """Get all tasks that depend on this task (downstream)."""
        tasks = self.task_manager.list_tasks("")
        task_map = {t.get("id") or t.get("task_id"): t for t in tasks}
        dependent_map: dict[str, list[str]] = {}
        for t in tasks:
            tid = t.get("id") or t.get("task_id")
            if not tid:
                continue
            for dep in t.get("depends_on", []):
                dependent_map.setdefault(dep, []).append(tid)

        visited: set[str] = set()
        result: list[TaskGraphNode] = []

        def dfs(tid: str):
            if tid in visited:
                return
            visited.add(tid)
            for dep_task_id in dependent_map.get(tid, []):
                t = task_map.get(dep_task_id)
                if not t:
                    continue
                dfs(dep_task_id)
                node = TaskGraphNode(
                    task_id=dep_task_id,
                    title=t.get("title", ""),
                    status=TaskStatus(t.get("status", "pending")),
                    assigned_agent=t.get("assigned_agent"),
                    created_at=t.get("created_at", datetime.utcnow()),
                    started_at=t.get("started_at"),
                    completed_at=t.get("completed_at"),
                    depends_on=t.get("depends_on", []),
                )
                if node.task_id not in [r.task_id for r in result]:
                    result.append(node)

        dfs(task_id)
        return result


# ---------------------------------------------------------------------------
# Execution Plan Generator
# ---------------------------------------------------------------------------

class ExecutionPlanGenerator:
    """Generates phased execution plan from task graph."""

    def __init__(self, task_graph_builder: TaskGraphBuilder):
        self.builder = task_graph_builder

    def generate(self, workspace_id: str) -> ExecutionPlan:
        graph = self.builder.build(workspace_id)
        nodes = graph.nodes
        edges = graph.edges

        sorter = TopologicalSorter(nodes, edges)
        sort_result = sorter.sort()

        phases: list[ExecutionPhase] = []
        for level_idx, level_tasks in enumerate(sort_result.levels):
            depends_on_phases = []
            if level_idx > 0:
                depends_on_phases = [level_idx - 1]

            can_run_parallel = len(level_tasks) > 1

            phase = ExecutionPhase(
                phase_id=level_idx,
                tasks=level_tasks,
                can_run_parallel=can_run_parallel,
                depends_on_phases=depends_on_phases,
            )
            phases.append(phase)

        estimated_duration = len(phases) * 10.0

        return ExecutionPlan(
            workspace_id=workspace_id,
            phases=phases,
            estimated_duration_median=estimated_duration,
        )
