"""
OrchestrationManager — Multi-agent orchestration (Coordinator / Specialist / Critic).

Coordinates task decomposition, parallel execution, quality review, and result aggregation.
"""

import json
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
from collaboration.storage import for_orchestrations, for_subtasks, for_reviews, ensure_workspace_files
from collaboration.events import Event, EventType, get_event_bus

MAX_CONCURRENT_SPECIALISTS = 3
CRITIC_THRESHOLD = 6.0
MAX_RETRY = 2
AIAgent_TIMEOUT = 120  # seconds


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _call_aia_agent(prompt: str) -> str:
    """Call AIAgent via subprocess with MINIMAX_CN_API_KEY → ANTHROPIC_API_KEY."""
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
        self._bus = get_event_bus()

    # ─── Orchestration CRUD ──────────────────────────────────────────────────

    def create_orchestration(
        self,
        root_task_id: str,
        coordinator_id: str,
        user_task_description: str,
    ) -> TaskOrchestration:
        """Create a new orchestration and immediately trigger Coordinator decomposition."""
        orch_id = f"orch_{uuid.uuid4().hex[:12]}"
        orch = TaskOrchestration(
            orchestration_id=orch_id,
            root_task_id=root_task_id,
            coordinator_id=coordinator_id,
            phase=OrchestrationPhase.PLANNING,
            sub_task_ids=[],
            context_pool={"user_requirements": user_task_description},
            created_at=_now_iso(),
            updated_at=_now_iso(),
        )
        self._orch_store.upsert(orch.to_dict())
        self._emit("orchestration.created", orch.to_dict())
        return orch

    def get_orchestration(self, orch_id: str) -> Optional[TaskOrchestration]:
        data = self._orch_store.get(orch_id)
        return TaskOrchestration.from_dict(data) if data else None

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

    # ─── Specialist — 并行执行 ──────────────────────────────────────────────

    def _execute_single_subtask(self, sub_task: SubTask, agent_id: str) -> SubTask:
        """Execute one SubTask: mark in_progress → AIAgent → mark completed."""
        sub_task.status = TaskStatus.IN_PROGRESS
        sub_task.assigned_agent_id = agent_id
        sub_task.updated_at = _now_iso()
        self._subtask_store.upsert(sub_task.to_dict())
        self._emit("subtask.started", sub_task.to_dict())

        orch = self.get_orchestration(sub_task.parent_orchestration_id)
        context_json = json.dumps(orch.context_pool, ensure_ascii=False, indent=2) if orch else "{}"

        prompt = f"""你是一个专业执行者。请完成以下子任务。

任务标题：{sub_task.title}
任务描述：{sub_task.description}

共享上下文：
{context_json}

直接输出执行结果（简洁，不要 markdown）。"""

        result = _call_aia_agent(prompt)
        sub_task.result = result
        sub_task.status = TaskStatus.COMPLETED
        sub_task.updated_at = _now_iso()
        self._subtask_store.upsert(sub_task.to_dict())
        self._emit("subtask.completed", sub_task.to_dict())
        return sub_task

    def run_specialists_parallel(self, orch_id: str, agent_pool: list[str]):
        """Run all pending SubTasks in parallel, honouring MAX_CONCURRENT_SPECIALISTS."""
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

        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_SPECIALISTS) as executor:
            futures = {}
            for st in ready:
                agent = agent_pool[len(futures) % len(agent_pool)] if agent_pool else "default"
                future = executor.submit(self._execute_single_subtask, st, agent)
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
        return SubTask.from_dict(data) if data else None

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
        """Main entry point: run full Coordinator→Specialist→Critic pipeline."""
        orch = self.get_orchestration(orch_id)
        if not orch:
            return

        self.update_phase(orch_id, OrchestrationPhase.EXECUTING)
        self._emit("orchestration.user_confirmed", {"orchestration_id": orch_id})

        # Run specialists (handles Critic internally)
        self.run_specialists_parallel(orch_id, agent_pool)

        # Check if all done
        subtasks = self.get_orchestration_subtasks(orch_id)
        all_done = all(st.status in (TaskStatus.COMPLETED, TaskStatus.FAILED) for st in subtasks)
        has_failed = any(st.status == TaskStatus.FAILED for st in subtasks)

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