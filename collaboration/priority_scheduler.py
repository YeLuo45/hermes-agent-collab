"""
Priority Scheduler for hermes-agent-collab.

Implements a multi-level priority queue with optional preemption.
Tasks are executed by a worker pool based on priority order.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any, Callable, Coroutine

_log = logging.getLogger(__name__)


# ─── Enums ─────────────────────────────────────────────────────────────────────


class TaskPriority(IntEnum):
    """Task priority levels (lower = higher priority)."""
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3


class TaskState(IntEnum):
    """Task execution state."""
    PENDING = 0
    RUNNING = 1
    COMPLETED = 2
    FAILED = 3
    CANCELLED = 4
    PREEMPTED = 5


# ─── PriorityTask ──────────────────────────────────────────────────────────────


@dataclass
class PriorityTask:
    """
    A task with priority and optional preemption support.
    """
    task_id: str
    priority: TaskPriority
    payload: Any
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    deadline: datetime | None = None
    max_retries: int = 3
    preemption_allowed: bool = True
    state: TaskState = TaskState.PENDING
    checkpoint: dict | None = None
    result: Any = None
    error: str | None = None
    attempts: int = 0
    worker_id: str | None = None

    def __post_init__(self):
        if not self.task_id:
            self.task_id = str(uuid.uuid4())

    @property
    def is_high_priority(self) -> bool:
        return self.priority <= TaskPriority.HIGH

    @property
    def is_critical(self) -> bool:
        return self.priority == TaskPriority.CRITICAL

    def can_be_preempted(self) -> bool:
        return self.preemption_allowed and self.state == TaskState.RUNNING

    def save_checkpoint(self, state: dict):
        """Save checkpoint for preemption recovery."""
        self.checkpoint = state

    def get_checkpoint(self) -> dict | None:
        return self.checkpoint


# ─── Priority Queue ────────────────────────────────────────────────────────────


class PriorityQueue:
    """
    Multi-level priority queue with 4 priority levels.
    Lower priority number = higher priority.
    """

    def __init__(self):
        self._queues: dict[TaskPriority, asyncio.Queue] = {
            p: asyncio.Queue() for p in TaskPriority
        }
        self._all_tasks: dict[str, PriorityTask] = {}
        self._lock = asyncio.Lock()

    async def put(self, task: PriorityTask):
        """Add task to appropriate priority queue."""
        async with self._lock:
            self._all_tasks[task.task_id] = task
        await self._queues[task.priority].put(task)
        _log.debug(f"Task {task.task_id} added to {task.priority.name} queue")

    async def get(self) -> PriorityTask:
        """
        Get highest priority task (lowest number first).
        Blocks until a task is available.
        """
        # Check queues in priority order: CRITICAL(0) -> HIGH(1) -> NORMAL(2) -> LOW(3)
        for priority in TaskPriority:
            q = self._queues[priority]
            if not q.empty():
                return q.get_nowait()
        # All empty, wait for any task
        # We use a combined future approach
        while True:
            for priority in TaskPriority:
                q = self._queues[priority]
                if not q.empty():
                    return q.get_nowait()
            await asyncio.sleep(0.01)

    async def get_nowait(self) -> PriorityTask | None:
        """Try to get highest priority task without blocking."""
        for priority in TaskPriority:
            q = self._queues[priority]
            if not q.empty():
                return q.get_nowait()
        return None

    def cancel(self, task_id: str) -> bool:
        """Cancel a pending task. Returns True if found and cancelled."""
        task = self._all_tasks.get(task_id)
        if task and task.state == TaskState.PENDING:
            task.state = TaskState.CANCELLED
            _log.info(f"Task {task_id} cancelled")
            return True
        return False

    def preempt(self, task_id: str) -> bool:
        """Preempt a running task. Returns True if preemption succeeded."""
        task = self._all_tasks.get(task_id)
        if task and task.can_be_preempted():
            task.state = TaskState.PREEMPTED
            _log.info(f"Task {task_id} preempted by higher priority task")
            return True
        return False

    def get_task(self, task_id: str) -> PriorityTask | None:
        return self._all_tasks.get(task_id)

    def list_by_priority(self, priority: TaskPriority | None = None) -> list[PriorityTask]:
        """List all tasks, optionally filtered by priority."""
        tasks = list(self._all_tasks.values())
        if priority is not None:
            tasks = [t for t in tasks if t.priority == priority]
        return sorted(tasks, key=lambda t: (t.priority, t.created_at))

    @property
    def pending_count(self) -> dict[TaskPriority, int]:
        return {p: q.qsize() for p, q in self._queues.items()}

    @property
    def total_pending(self) -> int:
        return sum(q.qsize() for q in self._queues.values())


# ─── Worker ────────────────────────────────────────────────────────────────────


@dataclass
class Worker:
    """A worker that executes tasks from the scheduler."""
    worker_id: str
    current_task: PriorityTask | None = None
    _running: asyncio.Task | None = field(default=None, repr=False)
    _stopped: bool = field(default=False, repr=False)

    async def run(self, scheduler: "PriorityScheduler", handler: Callable[[PriorityTask], Coroutine]) -> None:
        """Run loop: fetch and execute tasks."""
        while not self._stopped:
            try:
                # Get next task (with timeout for graceful shutdown)
                task = await asyncio.wait_for(scheduler.queue.get(), timeout=1.0)
                if task is None:
                    continue

                # Skip cancelled/preempted tasks
                if task.state in (TaskState.CANCELLED, TaskState.PREEMPTED):
                    continue

                # Execute task
                task.state = TaskState.RUNNING
                task.worker_id = self.worker_id
                task.attempts += 1
                self.current_task = task

                try:
                    result = await handler(task)
                    task.result = result
                    task.state = TaskState.COMPLETED
                    _log.info(f"Task {task.task_id} completed by {self.worker_id}")
                except Exception as e:
                    task.error = str(e)
                    if task.attempts < task.max_retries:
                        # Re-queue for retry
                        task.state = TaskState.PENDING
                        await scheduler.queue.put(task)
                        _log.warning(f"Task {task.task_id} failed, retry {task.attempts}/{task.max_retries}")
                    else:
                        task.state = TaskState.FAILED
                        _log.error(f"Task {task.task_id} failed permanently: {e}")
                finally:
                    self.current_task = None

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                _log.exception(f"Worker {self.worker_id} error: {e}")

    def stop(self):
        """Signal worker to stop."""
        self._stopped = True
        if self._running:
            self._running.cancel()


# ─── Priority Scheduler ────────────────────────────────────────────────────────


class PriorityScheduler:
    """
    Priority-based task scheduler with optional preemption.

    Features:
    - 4 priority levels (CRITICAL, HIGH, NORMAL, LOW)
    - Configurable worker pool size
    - Optional preemption of lower priority tasks
    - Starvation prevention for low priority tasks
    - Deadline support
    """

    def __init__(
        self,
        max_workers: int = 4,
        preemption_enabled: bool = True,
        starvation_threshold: int = 300,
    ):
        self.max_workers = max_workers
        self.preemption_enabled = preemption_enabled
        self.starvation_threshold = starvation_threshold  # seconds
        self._queue = PriorityQueue()
        self._workers: list[Worker] = []
        self._worker_tasks: list[asyncio.Task] = []
        self._started = False
        self._stopped = False
        self._lock = asyncio.Lock()
        self._task_handler: Callable[[PriorityTask], Coroutine] | None = None
        self._last_low_priority_run: float = 0

    @property
    def queue(self) -> PriorityQueue:
        return self._queue

    async def set_task_handler(self, handler: Callable[[PriorityTask], Coroutine]):
        """Set the async handler function for executing tasks."""
        self._task_handler = handler

    async def start(self):
        """Start the scheduler and worker pool."""
        if self._started:
            return

        async with self._lock:
            if self._started:
                return
            self._started = True

        if self._task_handler is None:
            raise ValueError("Task handler not set. Call set_task_handler() before start().")

        # Create workers
        for i in range(self.max_workers):
            worker = Worker(worker_id=f"worker-{i}")
            self._workers.append(worker)
            task = asyncio.create_task(worker.run(self, self._task_handler))
            self._worker_tasks.append(task)

        _log.info(f"PriorityScheduler started with {self.max_workers} workers")

    async def stop(self):
        """Stop the scheduler and all workers."""
        if not self._started:
            return

        self._stopped = True

        # Stop all workers
        for worker in self._workers:
            worker.stop()

        # Wait for worker tasks
        for task in self._worker_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._workers.clear()
        self._worker_tasks.clear()
        self._started = False
        _log.info("PriorityScheduler stopped")

    async def submit(
        self,
        payload: Any,
        priority: TaskPriority = TaskPriority.NORMAL,
        deadline: datetime | None = None,
        preemption_allowed: bool = True,
        task_id: str | None = None,
    ) -> str:
        """
        Submit a task to the scheduler.

        Returns the task_id.
        """
        task = PriorityTask(
            task_id=task_id or str(uuid.uuid4()),
            priority=priority,
            payload=payload,
            deadline=deadline,
            preemption_allowed=preemption_allowed,
        )
        await self._queue.put(task)

        # Trigger preemption check for high priority tasks
        if self.preemption_enabled and priority <= TaskPriority.HIGH:
            await self._check_preemption()

        return task.task_id

    async def cancel(self, task_id: str) -> bool:
        """Cancel a pending task."""
        return self._queue.cancel(task_id)

    async def preempt_running_task(self, task_id: str) -> bool:
        """
        Force preempt a running task (P0/P1 can always preempt).
        """
        task = self._queue.get_task(task_id)
        if not task:
            return False
        if task.state == TaskState.RUNNING:
            task.state = TaskState.PREEMPTED
            _log.warning(f"Task {task_id} force preempted")
            return True
        return False

    def get_status(self, task_id: str) -> dict | None:
        """Get task status as a dict."""
        task = self._queue.get_task(task_id)
        if not task:
            return None
        return {
            "task_id": task.task_id,
            "priority": task.priority.name,
            "state": task.state.name,
            "created_at": task.created_at.isoformat(),
            "deadline": task.deadline.isoformat() if task.deadline else None,
            "attempts": task.attempts,
            "worker_id": task.worker_id,
            "error": task.error,
        }

    def list_tasks(self, priority: TaskPriority | None = None) -> list[dict]:
        """List all tasks."""
        tasks = self._queue.list_by_priority(priority)
        return [
            {
                "task_id": t.task_id,
                "priority": t.priority.name,
                "state": t.state.name,
                "created_at": t.created_at.isoformat(),
                "deadline": t.deadline.isoformat() if t.deadline else None,
            }
            for t in tasks
        ]

    async def _check_preemption(self):
        """
        Check if a running task should be preempted for a higher priority task.
        Called when a CRITICAL or HIGH priority task is submitted.
        """
        if not self.preemption_enabled:
            return

        # Find running lower priority task
        for task in self._queue._all_tasks.values():
            if task.state == TaskState.RUNNING and task.can_be_preempted():
                # Check if there's a higher priority task waiting
                highest_waiting = None
                for p in TaskPriority:
                    if p >= task.priority:
                        continue
                    # A higher priority (lower number) task is waiting
                    for t in self._queue._all_tasks.values():
                        if t.priority == p and t.state == TaskState.PENDING:
                            if highest_waiting is None or t.priority < highest_waiting.priority:
                                highest_waiting = t

                if highest_waiting:
                    # Preempt the current task
                    task.state = TaskState.PREEMPTED
                    # Re-queue the preempted task
                    await self._queue.put(task)
                    _log.info(f"Preempted {task.task_id} for {highest_waiting.task_id}")
                    return

    async def _check_starvation(self):
        """
        Periodically check for starvation of low priority tasks.
        Low priority tasks that wait too long get a temporary priority boost.
        """
        if not self._started:
            return

        now = time.time()
        for task in self._queue._all_tasks.values():
            if (
                task.priority == TaskPriority.LOW
                and task.state == TaskState.PENDING
            ):
                wait_time = now - task.created_at.timestamp()
                if wait_time > self.starvation_threshold:
                    # Temporarily boost priority
                    _log.info(f"Boosting low priority task {task.task_id} due to starvation")
                    task.priority = TaskPriority.NORMAL


# Singleton
_scheduler: PriorityScheduler | None = None


def get_priority_scheduler() -> PriorityScheduler:
    """Get singleton PriorityScheduler."""
    global _scheduler
    if _scheduler is None:
        _scheduler = PriorityScheduler()
    return _scheduler
