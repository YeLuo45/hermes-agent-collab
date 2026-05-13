"""
OrchestrationManager — Multi-agent orchestration (Coordinator / Specialist / Critic).

Coordinates task decomposition, parallel execution, quality review, and result aggregation.
"""

import json
import logging
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from collaboration.models import (
    TaskOrchestration, SubTask, CriticReview,
    OrchestrationPhase, ReviewDecision, TaskStatus,
)
from collaboration.storage import for_orchestrations, for_subtasks, for_reviews, for_events, ensure_workspace_files
from collaboration.events import Event, EventType, get_event_bus

_log = logging.getLogger(__name__)

MAX_CONCURRENT_SPECIALISTS = 3
CRITIC_THRESHOLD = 6.0
MAX_RETRY = 2
AIAgent_TIMEOUT = 120  # seconds
CIRCUIT_BREAKER_THRESHOLD = 3  # consecutive failures before agent is skipped
CIRCUIT_BREAKER_COOLDOWN = 300  # seconds before circuit resets
SUBTASK_TERMINAL = frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED})

# Per-agent circuit breaker registry: agent_id -> {"failures": int, "tripped_at": float|None}
_agent_circuit_breakers: dict[str, dict] = {}
_breaker_lock = __import__("threading").Lock()


def _is_agent_circuit_open(agent_id: str) -> bool:
    """Return True if agent circuit is open (too many consecutive failures)."""
    if agent_id == "default" or not agent_id:
        return False
    with _breaker_lock:
        state = _agent_circuit_breakers.get(agent_id)
        if not state:
            return False
        if state.get("tripped_at") is None:
            return False
        import time
        if time.time() - state["tripped_at"] > CIRCUIT_BREAKER_COOLDOWN:
            # Auto-reset after cooldown
            state["failures"] = 0
            state["tripped_at"] = None
            return False
        return True


def _record_agent_failure(agent_id: str):
    """Record a failure for circuit breaker. Trips the circuit after threshold."""
    if agent_id == "default" or not agent_id:
        return
    with _breaker_lock:
        state = _agent_circuit_breakers.setdefault(agent_id, {"failures": 0, "tripped_at": None})
        state["failures"] += 1
        if state["failures"] >= CIRCUIT_BREAKER_THRESHOLD:
            state["tripped_at"] = __import__("time").time()
            _log.warning("Circuit breaker tripped for agent %s after %d failures", agent_id, state["failures"])


def _record_agent_success(agent_id: str):
    """Reset failure counter on success."""
    if agent_id == "default" or not agent_id:
        return
    with _breaker_lock:
        state = _agent_circuit_breakers.get(agent_id)
        if state:
            state["failures"] = 0
            state["tripped_at"] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_aia_agent_impl(prompt: str) -> str:
    """The actual AIAgent subprocess call. Extracted for test injection."""
    import subprocess, os, sys
    from pathlib import Path
    from dotenv import load_dotenv

    load_dotenv(Path.home() / ".hermes" / ".env")
    os.environ["ANTHROPIC_API_KEY"] = os.environ.get("MINIMAX_CN_API_KEY", "")

    escaped_prompt = prompt.replace("'''", "''' '''").replace("'", "\\'")
    script = f"""
import sys, os, yaml
from pathlib import Path
sys.path.insert(0, str(Path.home() / '.hermes' / 'hermes-agent'))
from run_agent import AIAgent
with open(Path.home() / '.hermes' / 'config.yaml') as f:
    cfg = yaml.safe_load(f)
m = cfg.get('model', {{}})
ag = AIAgent(model=m.get('default','MiniMax-M2.7'), base_url=m.get('base_url',''),
             provider=m.get('provider',''), api_key=os.environ.get('MINIMAX_CN_API_KEY',''),
             platform='collab', quiet_mode=True, verbose_logging=False)
print(ag.chat('''{escaped_prompt}'''), flush=True)
"""
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=AIAgent_TIMEOUT,
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "AIAgent call timed out after 120s"})
    except Exception as e:
        return json.dumps({"error": str(e)})


# Override this in tests to inject mock behaviour
_call_aia_agent_impl = _default_aia_agent_impl


def _call_aia_agent(prompt: str) -> str:
    """Call AIAgent via subprocess. Delegates to _call_aia_agent_impl for test injection."""
    return _call_aia_agent_impl(prompt)


def _parse_json_response(response: str) -> dict:
    """Extract JSON from AIAgent response, stripping markdown code blocks."""
    json_str = re.search(r'\{[\s\S]*\}', response)
    if json_str:
        return json.loads(json_str.group())
    return {}


class OrchestrationManager:
    """Manages the full multi-agent orchestration lifecycle."""

    def __init__(self, workspace_id: str):
        self.workspace_id = workspace_id
        ws_path = ensure_workspace_files(workspace_id)
        self._orch_store = for_orchestrations(ws_path)
        self._subtask_store = for_subtasks(ws_path)
        self._review_store = for_reviews(ws_path)
        self._event_store = for_events(ws_path)
        self._bus = get_event_bus()

        # Wire event bus → persistent event store
        self._bus.set_event_store(self._event_store.upsert)

    # ─── Orchestration CRUD ──────────────────────────────────────────────────

    def create_orchestration(
        self,
        root_task_id: str,
        coordinator_id: str,
        user_task_description: str,
        owner_id: str = "anonymous",
    ) -> TaskOrchestration:
        """Create a new orchestration and immediately trigger Coordinator decomposition."""
        orch_id = f"orch_{uuid.uuid4().hex[:12]}"
        orch = TaskOrchestration(
            orchestration_id=orch_id,
            root_task_id=root_task_id,
            coordinator_id=coordinator_id,
            owner_id=owner_id,
            user_task_description=user_task_description,
            phase=OrchestrationPhase.PLANNING,
            sub_task_ids=[],
            context_pool={"user_requirements": user_task_description},
            created_at=_now_iso(),
            updated_at=_now_iso(),
        )
        self._orch_store.upsert(orch.to_dict())
        self._emit("orchestration.created", orch.to_dict())
        return orch

    # ─── Ownership & Concurrency Guards ──────────────────────────────────────

    def _get_active_orchestrations(self) -> list[TaskOrchestration]:
        """Return orchestrations currently in non-terminal phase."""
        return [
            o for o in self._orch_store.list()
            if o.phase not in (OrchestrationPhase.COMPLETED, OrchestrationPhase.FAILED)
        ]

    def check_ownership(self, orch_id: str, requester_id: str) -> bool:
        """Verify the requester owns the orchestration."""
        orch = self.get_orchestration(orch_id)
        if not orch:
            return False
        return orch.owner_id == requester_id

    def acquire_orchestration_lock(self, orch_id: str, requester_id: str) -> bool:
        """Acquire exclusive lock on an orchestration for the given owner.

        Returns True if lock acquired (no other active orchestration for this owner
        is currently running). Fails if another orchestration owned by the same
        user is already in-progress.
        """
        active = self._get_active_orchestrations()
        for orch in active:
            if orch.orchestration_id == orch_id:
                # Own orchestration in-progress — re-entry allowed
                continue
            if orch.owner_id == requester_id:
                # Same owner already has an active orchestration
                return False
        return True

    def get_owner_active_orchestration(self, owner_id: str) -> TaskOrchestration | None:
        """Return the currently-active orchestration for an owner, if any."""
        for orch in self._get_active_orchestrations():
            if orch.owner_id == owner_id:
                return orch
        return None

    def get_orchestration(self, orch_id: str) -> Optional[TaskOrchestration]:
        data = self._orch_store.get(orch_id)
        # JsonFileStore.get() already deserializes; from_dict would fail on an already-deserialized object
        return data if data else None

    def list_orchestrations(self) -> list[TaskOrchestration]:
        return self._orch_store.list()

    def update_phase(self, orch_id: str, phase: OrchestrationPhase):
        orch = self.get_orchestration(orch_id)
        if orch:
            orch.phase = phase
            orch.updated_at = _now_iso()
            self._orch_store.upsert(orch.to_dict())

    # ─── Coordinator — 任务分解 ─────────────────────────────────────────────

    def decompose_task(self, orch_id: str) -> list[SubTask]:
        """Coordinator analyses the root task and produces SubTask list via AIAgent."""
        orch = self.get_orchestration(orch_id)
        if not orch:
            raise ValueError(f"Orchestration {orch_id} not found")

        user_desc = orch.context_pool.get("user_requirements", "")
        prompt = f"""你是一个任务分解专家。请将以下任务分解为 3-6 个可独立执行的子任务。

任务：{user_desc}

请严格按以下 JSON 格式输出（不要添加任何解释，不要使用 markdown 代码块）：
{{
  "sub_tasks": [
    {{"title": "子任务标题", "description": "详细描述", "dependencies": ["依赖的子任务标题"]}}
  ],
  "execution_plan": "执行顺序说明",
  "context": {{"关键提取": "值"}}
}}"""

        response = _call_aia_agent(prompt)
        parsed = _parse_json_response(response)

        if not parsed.get("sub_tasks"):
            raise ValueError(f"Coordinator failed to decompose: {response[:200]}")

        title_to_id = {}
        for st_data in parsed["sub_tasks"]:
            st_id = f"st_{uuid.uuid4().hex[:12]}"
            title_to_id[st_data["title"]] = st_id

        sub_tasks = []
        for st_data in parsed["sub_tasks"]:
            deps = [title_to_id[d] for d in st_data.get("dependencies", []) if d in title_to_id]
            st = SubTask(
                sub_task_id=title_to_id[st_data["title"]],
                parent_orchestration_id=orch_id,
                title=st_data["title"],
                description=st_data["description"],
                assigned_agent_id=None,
                status=TaskStatus.PENDING,
                dependencies=deps,
                result=None,
            )
            self._subtask_store.upsert(st.to_dict())
            sub_tasks.append(st)

        # Persist updated orch
        orch.sub_task_ids = [st.sub_task_id for st in sub_tasks]
        orch.context_pool.update(parsed.get("context", {}))
        orch.updated_at = _now_iso()
        self._orch_store.upsert(orch.to_dict())

        self._emit("orchestration.plan_ready", {
            "orchestration_id": orch_id,
            "sub_tasks": [st.to_dict() for st in sub_tasks],
            "execution_plan": parsed.get("execution_plan", ""),
        })
        return sub_tasks

    # ─── Specialist 智能路由 ────────────────────────────────────────────────

    def _route_to_agent(self, sub_task: SubTask, available_agents: list["Agent"]) -> str:
        """Route a SubTask to the best-matching Agent based on capability keyword overlap.

        Scoring:
        - Exact capability keyword match in description → +2 per match
        - Partial (substring) match in description → +1 per match
        - Exact match in title → +3 bonus
        Returns agent_id with highest score, or 'default' if no agents provided.
        """
        if not available_agents:
            return "default"

        desc_lower = sub_task.description.lower()
        title_lower = sub_task.title.lower()
        best_agent_id = available_agents[0].agent_id
        best_score = -1

        for agent in available_agents:
            score = 0
            for cap in agent.capabilities:
                cap_lower = cap.lower()
                if cap_lower in desc_lower:
                    score += 2
                if cap_lower in title_lower:
                    score += 3
            if score > best_score:
                best_score = score
                best_agent_id = agent.agent_id

        return best_agent_id

    # ─── Specialist — 并行执行 ──────────────────────────────────────────────

    def _execute_single_subtask(self, sub_task: SubTask, agent_id: str) -> SubTask:
        """Execute one SubTask: check circuit → AIAgent → mark completed / handle timeout."""
        # Circuit breaker check
        if _is_agent_circuit_open(agent_id):
            sub_task.status = TaskStatus.FAILED
            sub_task.result = f"Agent {agent_id} circuit breaker open (consecutive failures)"
            sub_task.updated_at = _now_iso()
            self._subtask_store.upsert(sub_task.to_dict())
            self._emit("subtask.starting", {
                "sub_task_id": sub_task.sub_task_id,
                "title": sub_task.title,
                "assigned_agent_id": agent_id,
                "skipped": True,
                "reason": "circuit_breaker_open",
            })
            self._emit("subtask.started", sub_task.to_dict())
            return sub_task

        sub_task.status = TaskStatus.IN_PROGRESS
        sub_task.assigned_agent_id = agent_id
        sub_task.updated_at = _now_iso()
        self._subtask_store.upsert(sub_task.to_dict())
        self._emit("subtask.starting", {
            "sub_task_id": sub_task.sub_task_id,
            "title": sub_task.title,
            "assigned_agent_id": agent_id,
        })
        self._emit("subtask.started", sub_task.to_dict())

        orch = self.get_orchestration(sub_task.parent_orchestration_id)
        context_json = json.dumps(orch.context_pool, ensure_ascii=False, indent=2) if orch else "{}"

        prompt = f"""你是一个专业执行者。请完成以下子任务。

任务标题：{sub_task.title}
任务描述：{sub_task.description}

共享上下文：
{context_json}

直接输出执行结果（简洁，不要 markdown）。"""

        try:
            result = _call_aia_agent(prompt)
        except Exception as e:
            _record_agent_failure(agent_id)
            sub_task.result = f"Agent call error: {str(e)}"
            sub_task.status = TaskStatus.FAILED
            sub_task.updated_at = _now_iso()
            self._subtask_store.upsert(sub_task.to_dict())
            self._emit("subtask.completed", sub_task.to_dict())
            return sub_task

        # Check for timeout / error in response
        try:
            result_data = json.loads(result)
            if "error" in result_data or "timed out" in result.lower():
                _record_agent_failure(agent_id)
                sub_task.result = result
                sub_task.status = TaskStatus.FAILED
                sub_task.updated_at = _now_iso()
                self._subtask_store.upsert(sub_task.to_dict())
                self._emit("subtask.completed", sub_task.to_dict())
                return sub_task
        except (json.JSONDecodeError, TypeError):
            pass

        _record_agent_success(agent_id)
        sub_task.result = result
        sub_task.status = TaskStatus.COMPLETED
        sub_task.updated_at = _now_iso()
        self._subtask_store.upsert(sub_task.to_dict())
        self._emit("subtask.completed", sub_task.to_dict())
        return sub_task

    def run_specialists_parallel(self, orch_id: str, agent_pool: list[str]):
        """Run all pending SubTasks in parallel, honouring MAX_CONCURRENT_SPECIALISTS.

        Uses capability-based routing to assign the best-matching Agent to each SubTask.
        """
        from collaboration.agent_registry import AgentRegistry

        orch = self.get_orchestration(orch_id)
        if not orch:
            return

        pending = [
            st for sid in orch.sub_task_ids
            if (st := self.get_subtask(sid)) and st.status == TaskStatus.PENDING
        ]

        if not pending:
            return

        # Build execution order: tasks whose dependencies are all completed first
        def can_run(st: SubTask) -> bool:
            return all(
                (dep_st := self.get_subtask(dep)) and dep_st.status == TaskStatus.COMPLETED
                for dep in st.dependencies
            )

        ready, not_ready = [], []
        for st in pending:
            (ready if can_run(st) else not_ready).append(st)

        # Load full Agent objects for capability routing
        registry = AgentRegistry(self.workspace_id)
        agents = [registry.get(aid) for aid in agent_pool if registry.get(aid)]
        available_agents = [a for a in agents if a is not None]

        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_SPECIALISTS) as executor:
            futures = {}
            for st in ready:
                # Use capability-based routing instead of round-robin
                agent_id = self._route_to_agent(st, available_agents) if available_agents else "default"
                future = executor.submit(self._execute_single_subtask, st, agent_id)
                futures[future] = st

            for future in as_completed(futures):
                st = futures[future]
                try:
                    result_st = future.result()
                    # After specialist completes, trigger Critic
                    self._run_critic(result_st)
                except Exception as e:
                    st.status = TaskStatus.FAILED
                    st.result = f"Execution error: {str(e)}"
                    st.updated_at = _now_iso()
                    self._subtask_store.upsert(st.to_dict())

            # Handle blocked tasks (dependencies not yet complete)
            for st in not_ready:
                st.status = TaskStatus.BLOCKED
                st.updated_at = _now_iso()
                self._subtask_store.upsert(st.to_dict())

    # ─── Critic — 质量审查 ──────────────────────────────────────────────────

    def _run_critic(self, sub_task: SubTask) -> CriticReview:
        """Critic reviews a completed SubTask,打分并决定是否打回重做."""
        prompt = f"""你是一个严格的代码审查专家。请对以下任务执行结果进行评分。

任务标题：{sub_task.title}
任务描述：{sub_task.description}
执行结果：{sub_task.result or 'N/A'}

严格评分 0-10，6分以下必须 REJECT。
请严格按以下 JSON 格式输出（不要解释，不要 markdown 代码块）：
{{"score": 0-10, "comments": "评分理由（中文）", "decision": "accept/reject"}}"""

        response = _call_aia_agent(prompt)
        parsed = _parse_json_response(response)

        score = float(parsed.get("score", 5.0))
        decision_str = parsed.get("decision", "accept").lower()
        decision = ReviewDecision.ACCEPT if decision_str == "accept" else ReviewDecision.REJECT
        comments = parsed.get("comments", "")

        review = CriticReview(
            review_id=f"rev_{uuid.uuid4().hex[:12]}",
            orchestration_id=sub_task.parent_orchestration_id,
            sub_task_id=sub_task.sub_task_id,
            critic_agent_id="critic",
            score=score,
            comments=comments,
            decision=decision,
        )
        self._review_store.upsert(review.to_dict())
        self._emit("review.created", review.to_dict())

        if decision == ReviewDecision.REJECT and sub_task.retry_count < MAX_RETRY:
            sub_task.status = TaskStatus.PENDING
            sub_task.retry_count += 1
            sub_task.updated_at = _now_iso()
            self._subtask_store.upsert(sub_task.to_dict())
            self._emit("subtask.rejected", sub_task.to_dict())
            self._emit("subtask.retry", {
                "sub_task_id": sub_task.sub_task_id,
                "retry_count": sub_task.retry_count,
            })
        elif decision == ReviewDecision.REJECT and sub_task.retry_count >= MAX_RETRY:
            sub_task.status = TaskStatus.FAILED
            sub_task.updated_at = _now_iso()
            self._subtask_store.upsert(sub_task.to_dict())
            self._emit("subtask.rejected", sub_task.to_dict())

        return review

    # ─── SubTask CRUD ────────────────────────────────────────────────────────

    def get_subtask(self, sub_task_id: str) -> Optional[SubTask]:
        data = self._subtask_store.get(sub_task_id)
        # JsonFileStore.get() already deserializes
        return data if data else None

    def get_orchestration_subtasks(self, orch_id: str) -> list[SubTask]:
        return [
            st for st in self._subtask_store.list()
            if st.parent_orchestration_id == orch_id
        ]

    def get_subtask_reviews(self, sub_task_id: str) -> list[CriticReview]:
        return [
            r for r in self._review_store.list()
            if r.sub_task_id == sub_task_id
        ]

    # ─── 结果汇总 ──────────────────────────────────────────────────────────

    def generate_report(self, orch_id: str) -> str:
        """Generate markdown execution report."""
        orch = self.get_orchestration(orch_id)
        if not orch:
            return "# Orchestration not found"

        subtasks = self.get_orchestration_subtasks(orch_id)
        lines = [
            f"# 任务执行报告：{orch.root_task_id}",
            f"\n**编排ID**: {orch.orchestration_id}",
            f"**阶段**: {orch.phase.value if isinstance(orch.phase, OrchestrationPhase) else orch.phase}",
            f"**创建时间**: {orch.created_at}",
            f"\n## 子任务执行结果\n",
        ]

        for st in subtasks:
            revs = self.get_subtask_reviews(st.sub_task_id)
            last_review = revs[-1] if revs else None
            icon = "✅" if st.status == TaskStatus.COMPLETED else ("⚠️" if st.retry_count > 0 else "❌")
            lines.append(f"### {icon} {st.title}")
            lines.append(f"- 执行者: {st.assigned_agent_id or '未分配'}")
            lines.append(f"- 重试次数: {st.retry_count}")
            if last_review:
                lines.append(f"- 评分: {last_review.score}/10 | {last_review.decision.value}")
                lines.append(f"- 审查意见: {last_review.comments}")
            lines.append(f"\n**执行结果**:\n{st.result or 'N/A'}\n")

        if orch.context_pool:
            lines.append("\n## 共享上下文\n")
            lines.append(f"```json\n{json.dumps(orch.context_pool, ensure_ascii=False, indent=2)}\n```\n")

        return "\n".join(lines)

    # ─── WebSocket 事件 ─────────────────────────────────────────────────────

    def _emit(self, event_name: str, payload: dict):
        """Emit a WebSocket broadcast event via the event bus."""
        try:
            event_type = EventType(event_name)
        except ValueError:
            return
        self._bus.emit_sync(Event(event_type, workspace_id=self.workspace_id, payload=payload))

    # ─── 执行入口 ──────────────────────────────────────────────────────────

    def execute_orchestration(self, orch_id: str, agent_pool: list[str]):
        """Main entry point: run full Coordinator→Specialist→Critic pipeline.

        Uses a retry loop to handle dependency chains: run_specialists_parallel
        is called repeatedly until all subtasks reach a terminal state
        (COMPLETED / FAILED / CANCELLED). BLOCKED tasks become eligible for
        execution in subsequent iterations once their dependencies complete.
        """
        orch = self.get_orchestration(orch_id)
        if not orch:
            return

        self.update_phase(orch_id, OrchestrationPhase.EXECUTING)
        self._emit("orchestration.user_confirmed", {"orchestration_id": orch_id})

        TERMINAL = SUBTASK_TERMINAL
        max_iterations = 20  # safety guard against infinite loops
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            # Re-evaluate BLOCKED tasks — their dependencies may have completed in the last iteration
            for st in self.get_orchestration_subtasks(orch_id):
                if st.status == TaskStatus.BLOCKED:
                    st.status = TaskStatus.PENDING
                    st.updated_at = _now_iso()
                    self._subtask_store.upsert(st.to_dict())

            # Run specialists — only READY (PENDING with all deps met) tasks execute
            self.run_specialists_parallel(orch_id, agent_pool)

            # Re-read subtask states after this iteration
            subtasks = self.get_orchestration_subtasks(orch_id)
            terminal = [st for st in subtasks if st.status in TERMINAL]
            non_terminal = [st for st in subtasks if st.status not in TERMINAL]

            # If all done or nothing left to do, exit
            if not non_terminal:
                break

            # No PENDING tasks but some are still BLOCKED — this is a true circular dependency
            if not any(st.status == TaskStatus.PENDING for st in non_terminal):
                blocked = [st for st in non_terminal if st.status == TaskStatus.BLOCKED]
                if blocked:
                    _log.warning("Circular dependency detected in orchestration %s", orch_id)
                    for st in blocked:
                        st.status = TaskStatus.FAILED
                        st.result = "Circular dependency: no eligible tasks remain"
                        st.updated_at = _now_iso()
                        self._subtask_store.upsert(st.to_dict())
                break

            # Small pause between iterations to allow completed results to propagate
            import time; time.sleep(0.1)

        # Final state evaluation
        subtasks = self.get_orchestration_subtasks(orch_id)
        has_failed = any(st.status == TaskStatus.FAILED for st in subtasks)
        all_done = all(st.status in TERMINAL for st in subtasks)

        if has_failed:
            self.update_phase(orch_id, OrchestrationPhase.FAILED)
            self._emit("orchestration.failed", {"orchestration_id": orch_id})
        elif all_done:
            self.update_phase(orch_id, OrchestrationPhase.COMPLETED)
            report = self.generate_report(orch_id)
            self._emit("orchestration.completed", {
                "orchestration_id": orch_id,
                "report": report,
            })

    def cancel_orchestration(self, orch_id: str) -> Optional[TaskOrchestration]:
        """Cancel an in-progress orchestration.

        Marks all non-terminal subtasks as CANCELLED and updates the
        orchestration phase to CANCELLED. Thread-safe via workspace lock.
        """
        with self._ws_lock:
            orch = self.get_orchestration(orch_id)
            if not orch:
                return None

            if orch.phase in {OrchestrationPhase.COMPLETED, OrchestrationPhase.FAILED,
                              OrchestrationPhase.CANCELLED}:
                return orch  # Already terminal, nothing to cancel

            # Cancel all non-terminal subtasks
            for st in self.get_orchestration_subtasks(orch_id):
                if st.status not in SUBTASK_TERMINAL:
                    st.status = TaskStatus.CANCELLED
                    st.result = "Cancelled by user"
                    st.updated_at = _now_iso()
                    self._subtask_store.upsert(st.to_dict())
                    self._emit("subtask.cancelled", st.to_dict())

            self.update_phase(orch_id, OrchestrationPhase.CANCELLED)
            self._emit("orchestration.cancelled", {"orchestration_id": orch_id})
            return self.get_orchestration(orch_id)

    # ─── Orchestration History & Replay ──────────────────────────────────────────

    def get_orchestration_events(
        self,
        orch_id: str,
        event_types: list[str] | None = None,
    ) -> list[dict]:
        """Return the persisted event log for an orchestration.

        Args:
            orch_id: orchestration to get events for
            event_types: optional filter — if provided, only matching events are returned

        Returns:
            List of event dicts in chronological order.
        """
        all_events = self._event_store.list()
        matching = [
            ev for ev in all_events
            if ev.get("payload", {}).get("orchestration_id") == orch_id
            or ev.get("payload", {}).get("parent_orchestration_id") == orch_id
        ]
        if event_types:
            matching = [ev for ev in matching if ev.get("event") in event_types]
        # Sort by timestamp (already ISO strings)
        matching.sort(key=lambda ev: ev.get("timestamp", ""))
        return matching

    def get_replay_steps(self, orch_id: str) -> list[dict]:
        """Return an ordered sequence of replay steps from an orchestration's event log.

        Each step is a dict with: timestamp, phase, actor, action, details.
        Used by replay_orchestration for deterministic state reconstruction.
        """
        events = self.get_orchestration_events(orch_id)
        steps = []
        for ev in events:
            et = ev.get("event", "")
            payload = ev.get("payload", {})
            if et == "orchestration.created":
                steps.append({"ts": ev["timestamp"], "phase": "init", "actor": "system",
                              "action": "created", "details": payload})
            elif et == "orchestration.plan_ready":
                steps.append({"ts": ev["timestamp"], "phase": "planning", "actor": "coordinator",
                              "action": "decomposed", "details": {"num_subtasks": len(payload.get("sub_task_ids", []))}})
            elif et == "orchestration.user_confirmed":
                steps.append({"ts": ev["timestamp"], "phase": "executing", "actor": "user",
                              "action": "confirmed", "details": {}})
            elif et == "subtask.starting":
                steps.append({"ts": ev["timestamp"], "phase": "executing", "actor": payload.get("agent_id", "unknown"),
                              "action": "starting", "details": {"subtask_id": payload.get("subtask_id"),
                                                               "title": payload.get("title", "")}})
            elif et == "subtask.completed":
                steps.append({"ts": ev["timestamp"], "phase": "executing", "actor": payload.get("agent_id", "unknown"),
                              "action": "completed", "details": {"subtask_id": payload.get("subtask_id"),
                                                                "status": payload.get("status", ""),
                                                                "result_preview": (payload.get("result", "")[:80] if payload.get("result") else "")}})
            elif et == "subtask.rejected":
                steps.append({"ts": ev["timestamp"], "phase": "review", "actor": "critic",
                              "action": "rejected", "details": {"subtask_id": payload.get("subtask_id"),
                                                               "score": payload.get("score", 0),
                                                               "reason": payload.get("reason", "")}})
            elif et == "review.created":
                steps.append({"ts": ev["timestamp"], "phase": "review", "actor": "critic",
                              "action": "reviewed", "details": {"score": payload.get("score", 0),
                                                               "decision": payload.get("decision", "")}})
            elif et == "orchestration.completed":
                steps.append({"ts": ev["timestamp"], "phase": "done", "actor": "system",
                              "action": "completed", "details": {}})
            elif et == "orchestration.failed":
                steps.append({"ts": ev["timestamp"], "phase": "done", "actor": "system",
                              "action": "failed", "details": {"reason": payload.get("reason", "")}})
            elif et == "orchestration.cancelled":
                steps.append({"ts": ev["timestamp"], "phase": "done", "actor": "user",
                              "action": "cancelled", "details": {}})
            elif et == "subtask.cancelled":
                steps.append({"ts": ev["timestamp"], "phase": "done", "actor": "user",
                              "action": "cancelled", "details": {"subtask_id": payload.get("subtask_id")}})
        return steps

    def replay_orchestration(self, orch_id: str) -> dict:
        """Reconstruct orchestration state by replaying persisted events.

        Returns:
            A state dict: {orchestration, subtasks, reviews, replay_steps}.
        """
        from collaboration.models import TaskOrchestration, SubTask, CriticReview

        orch = self.get_orchestration(orch_id)
        if not orch:
            return {"error": f"Orchestration {orch_id} not found"}

        # Rebuild subtask list
        all_subtasks = self._subtask_store.list()
        orch_subtasks = [st for st in all_subtasks
                        if st.get("parent_orchestration_id") == orch_id
                        or st.get("orchestration_id") == orch_id]

        # Rebuild reviews
        all_reviews = self._review_store.list()
        orch_reviews = [r for r in all_reviews if r.get("orchestration_id") == orch_id]

        return {
            "orchestration": orch.to_dict(),
            "subtasks": orch_subtasks,
            "reviews": [r.to_dict() if hasattr(r, "to_dict") else r for r in orch_reviews],
            "replay_steps": self.get_replay_steps(orch_id),
        }