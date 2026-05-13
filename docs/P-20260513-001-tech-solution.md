# Technical Solution: hermes-agent-collab 多Agent编排系统

**Proposal ID**: P-20260513-001
**Project**: hermes-agent-collab
**Direction**: A — Multi-Agent Orchestration System
**Status**: approved_for_dev

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        FastAPI Server                            │
│                     (collab server :9119)                        │
├─────────────────────────────────────────────────────────────────┤
│  REST Endpoints          │  WebSocket Server                    │
│  ───────────────────    │  ─────────────────────               │
│  POST /orchestrations    │  ws /api/collab/ws/{workspace_id}    │
│  GET  /orchestrations    │                                      │
│  POST /confirm           │  Push: orchestration.*, subtask.*    │
│  GET  /report            │              review.*                │
├─────────────────────────────────────────────────────────────────┤
│                 OrchestrationManager                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │  Coordinator  │→ │  Specialist  │→ │   Critic     │         │
│  │  (AIAgent)    │  │  (AIAgent)   │  │  (AIAgent)   │         │
│  │  任务分解      │  │  并行执行     │  │  质量审查     │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
│         │                  │                  │                │
│         └──────────┬───────┴──────────────────┘                │
│                    ▼                                            │
│              Context Pool (dict, in-memory)                     │
│              共享上下文，所有 Agent 可读写                         │
├─────────────────────────────────────────────────────────────────┤
│  ThreadPoolExecutor(max_workers=3)                              │
│  并发执行 Specialist，控制并发上限                               │
├─────────────────────────────────────────────────────────────────┤
│  JsonFileStore (现有) + 新增 orchestrations.json                │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. File Changes

### 2.1 新增文件

| 文件 | 职责 |
|------|------|
| `collaboration/models.py` | 新增 `OrchestrationPhase`, `TaskOrchestration`, `SubTask`, `CriticReview`, `ReviewDecision` |
| `collaboration/orchestration_manager.py` | `OrchestrationManager` — 核心编排逻辑（Coordinator/Specialist/Critic） |
| `collaboration/storage.py` | 扩展 `JsonFileStore` 支持 orchestrations.json |
| `collaboration/events.py` | 新增 `EventType.ORCHESTRATION_*`, `SUBTASK_*`, `REVIEW_*` 事件类型 |
| `collaboration/websocket_server.py` | 扩展支持编排相关 WebSocket 事件广播 |

### 2.2 修改文件

| 文件 | 修改内容 |
|------|---------|
| `collaboration/models.py` | 新增 Enum：`OrchestrationPhase`, `ReviewDecision` |
| `collaboration/collab_api.py` | 新增编排 REST 端点（5个） |
| `collaboration/__init__.py` | 导出新增的模型和类 |
| `collaboration/web/index.html` | 新增"多Agent模式"复选框 + 编排状态展示UI |

---

## 3. Data Models

### 3.1 新增 Enum

```python
# collaboration/models.py

class OrchestrationPhase(str, Enum):
    PLANNING = "planning"
    EXECUTING = "executing"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    FAILED = "failed"

class ReviewDecision(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"
```

### 3.2 TaskOrchestration

```python
@dataclass
class TaskOrchestration:
    orchestration_id: str
    root_task_id: str
    coordinator_id: str
    phase: OrchestrationPhase
    sub_task_ids: list[str]
    context_pool: dict
    created_at: str
    updated_at: str

    def to_dict(self) -> dict:
        return {
            "orchestration_id": self.orchestration_id,
            "root_task_id": self.root_task_id,
            "coordinator_id": self.coordinator_id,
            "phase": self.phase.value if isinstance(self.phase, OrchestrationPhase) else self.phase,
            "sub_task_ids": self.sub_task_ids,
            "context_pool": self.context_pool,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskOrchestration":
        phase = data.get("phase", "planning")
        if isinstance(phase, str):
            phase = OrchestrationPhase(phase)
        return cls(
            orchestration_id=data["orchestration_id"],
            root_task_id=data["root_task_id"],
            coordinator_id=data["coordinator_id"],
            phase=phase,
            sub_task_ids=data.get("sub_task_ids", []),
            context_pool=data.get("context_pool", {}),
            created_at=data.get("created_at", _now_iso()),
            updated_at=data.get("updated_at", _now_iso()),
        )
```

### 3.3 SubTask

```python
@dataclass
class SubTask:
    sub_task_id: str
    parent_orchestration_id: str
    title: str
    description: str
    assigned_agent_id: str | None
    status: TaskStatus
    dependencies: list[str]
    result: str | None
    retry_count: int = 0
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return {
            "sub_task_id": self.sub_task_id,
            "parent_orchestration_id": self.parent_orchestration_id,
            "title": self.title,
            "description": self.description,
            "assigned_agent_id": self.assigned_agent_id,
            "status": self.status.value if isinstance(self.status, TaskStatus) else self.status,
            "dependencies": self.dependencies,
            "result": self.result,
            "retry_count": self.retry_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SubTask":
        from collaboration.models import TaskStatus
        status = data.get("status", "pending")
        if isinstance(status, str):
            try:
                status = TaskStatus(status)
            except ValueError:
                status = TaskStatus.PENDING
        return cls(
            sub_task_id=data["sub_task_id"],
            parent_orchestration_id=data["parent_orchestration_id"],
            title=data["title"],
            description=data["description"],
            assigned_agent_id=data.get("assigned_agent_id"),
            status=status,
            dependencies=data.get("dependencies", []),
            result=data.get("result"),
            retry_count=data.get("retry_count", 0),
            created_at=data.get("created_at", _now_iso()),
            updated_at=data.get("updated_at", _now_iso()),
        )
```

### 3.4 CriticReview

```python
@dataclass
class CriticReview:
    review_id: str
    orchestration_id: str
    sub_task_id: str
    critic_agent_id: str
    score: float
    comments: str
    decision: ReviewDecision
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return {
            "review_id": self.review_id,
            "orchestration_id": self.orchestration_id,
            "sub_task_id": self.sub_task_id,
            "critic_agent_id": self.critic_agent_id,
            "score": self.score,
            "comments": self.comments,
            "decision": self.decision.value if isinstance(self.decision, ReviewDecision) else self.decision,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CriticReview":
        decision = data.get("decision", "accept")
        if isinstance(decision, str):
            decision = ReviewDecision(decision)
        return cls(
            review_id=data["review_id"],
            orchestration_id=data["orchestration_id"],
            sub_task_id=data["sub_task_id"],
            critic_agent_id=data["critic_agent_id"],
            score=data["score"],
            comments=data["comments"],
            decision=decision,
            created_at=data.get("created_at", _now_iso()),
        )
```

---

## 4. OrchestrationManager — Core Logic

```python
# collaboration/orchestration_manager.py

import asyncio
import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from collaboration.models import (
    TaskOrchestration, SubTask, CriticReview,
    OrchestrationPhase, ReviewDecision, TaskStatus
)
from collaboration.storage import JsonFileStore, ensure_workspace_files

MAX_CONCURRENT_SPECIALISTS = 3
CRITIC_THRESHOLD = 6.0
MAX_RETRY = 2

# Thread pool for AIAgent calls (shared with existing usage)
_executor = ThreadPoolExecutor(max_workers=4)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class OrchestrationManager:
    """Manages multi-agent orchestration lifecycle."""

    def __init__(self, workspace_id: str):
        self.workspace_id = workspace_id
        ws_path = ensure_workspace_files(workspace_id)
        self._store = JsonFileStore.for_orchestrations(ws_path)
        self._subtask_store = JsonFileStore.for_subtasks(ws_path)
        self._review_store = JsonFileStore.for_reviews(ws_path)

    # ─── Orchestration CRUD ─────────────────────────────────────────────────

    def create_orchestration(
        self,
        root_task_id: str,
        coordinator_id: str,
        user_task_description: str
    ) -> TaskOrchestration:
        """Create orchestration and trigger Coordinator to decompose task."""
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
        self._store.upsert(orch.to_dict())
        return orch

    def get_orchestration(self, orch_id: str) -> Optional[TaskOrchestration]:
        data = self._store.get(orch_id)
        return TaskOrchestration.from_dict(data) if data else None

    def list_orchestrations(self) -> list[TaskOrchestration]:
        return [TaskOrchestration.from_dict(d) for d in self._store.list()]

    def update_phase(self, orch_id: str, phase: OrchestrationPhase):
        orch = self.get_orchestration(orch_id)
        if orch:
            orch.phase = phase
            orch.updated_at = _now_iso()
            self._store.upsert(orch.to_dict())

    # ─── Coordinator — 任务分解 ─────────────────────────────────────────────

    def _call_aia agent(self, prompt: str, system: str = None) -> str:
        """Call AIAgent via subprocess (non-blocking wrapper)."""
        import subprocess, os, sys
        from pathlib import Path
        from dotenv import load_dotenv
        load_dotenv(Path.home() / ".hermes" / ".env")
        os.environ["ANTHROPIC_API_KEY"] = os.environ.get("MINIMAX_CN_API_KEY", "")

        script = f"""
import sys, os, yaml
from pathlib import Path
sys.path.insert(0, str(Path.home() / ".hermes" / "hermes-agent"))
from run_agent import AIAgent
with open(Path.home() / ".hermes" / "config.yaml") as f:
    cfg = yaml.safe_load(f)
m = cfg.get("model", {{}})
ag = AIAgent(model=m.get("default","MiniMax-M2.7"), base_url=m.get("base_url",""),
             provider=m.get("provider",""), api_key=os.environ.get("MINIMAX_CN_API_KEY",""),
             platform="collab", quiet_mode=True, verbose_logging=False)
result = ag.chat('''{prompt}''')
print(result, flush=True)
"""
        try:
            result = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True, text=True, timeout=120
            )
            return result.stdout.strip()
        except Exception as e:
            return f"{{\"error\": \"{str(e)}\"}}"

    def decompose_task(self, orch_id: str, user_description: str) -> list[SubTask]:
        """Coordinator decomposes task into sub_tasks."""
        prompt = f"""你是一个任务分解专家。请将以下任务分解为 3-6 个可独立执行的子任务。

任务：{user_description}

请按以下 JSON 格式输出（不要添加任何解释）：
{{
  "sub_tasks": [
    {{"title": "子任务标题", "description": "子任务详细描述", "dependencies": ["依赖的子任务标题"]}}
  ],
  "execution_plan": "执行顺序说明",
  "context": {{"关键信息提取": "值"}}
}}"""

        response = self._call_aia gent(prompt)
        # Parse JSON from response (strip markdown code blocks if present)
        json_match = re.search(r'\{[\s\S]*\}', response)
        if not json_match:
            raise ValueError(f"Coordinator failed to return valid JSON: {response}")

        parsed = json.loads(json_match.group())
        sub_tasks = []
        title_to_id = {}

        for st_data in parsed.get("sub_tasks", []):
            st_id = f"st_{uuid.uuid4().hex[:12]}"
            title_to_id[st_data["title"]] = st_id

        for st_data in parsed.get("sub_tasks", []):
            deps = [title_to_id[dep] for dep in st_data.get("dependencies", []) if dep in title_to_id]
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

        # Update orch with sub_task_ids and context
        orch = self.get_orchestration(orch_id)
        orch.sub_task_ids = [st.sub_task_id for st in sub_tasks]
        orch.context_pool.update(parsed.get("context", {}))
        orch.updated_at = _now_iso()
        self._store.upsert(orch.to_dict())

        return sub_tasks

    # ─── Specialist — 并行执行 ─────────────────────────────────────────────

    def execute_subtask(self, sub_task: SubTask, agent_id: str) -> str:
        """Specialist executes a single sub_task via AIAgent."""
        # Mark as in_progress
        sub_task.status = TaskStatus.IN_PROGRESS
        sub_task.assigned_agent_id = agent_id
        sub_task.updated_at = _now_iso()
        self._subtask_store.upsert(sub_task.to_dict())

        # Build execution prompt with context
        context = self.get_orchestration(sub_task.parent_orchestration_id).context_pool
        prompt = f"""你是一个专业执行者。请完成以下子任务。

任务标题：{sub_task.title}
任务描述：{sub_task.description}

共享上下文：
{json.dumps(context, ensure_ascii=False, indent=2)}

请直接执行任务，完成后输出执行结果（简洁）。"""

        result = self._call_aia gent(prompt)
        sub_task.result = result
        sub_task.status = TaskStatus.COMPLETED
        sub_task.updated_at = _now_iso()
        self._subtask_store.upsert(sub_task.to_dict())

        return result

    def run_specialists_parallel(self, orch_id: str, agent_pool: list[str]):
        """Run all pending sub_tasks in parallel (max MAX_CONCURRENT_SPECIALISTS)."""
        orch = self.get_orchestration(orch_id)
        pending = [self.get_subtask(sid) for sid in orch.sub_task_ids
                  if self.get_subtask(sid).status == TaskStatus.PENDING]

        futures = []
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_SPECIALISTS) as executor:
            for st in pending:
                # Find available agent
                agent = agent_pool[len(futures) % len(agent_pool)]
                future = executor.submit(self.execute_subtask, st, agent)
                futures.append((future, st))

            for future, st in futures:
                try:
                    future.result()
                except Exception as e:
                    st.status = TaskStatus.FAILED
                    st.result = f"Execution error: {str(e)}"
                    st.updated_at = _now_iso()
                    self._subtask_store.upsert(st.to_dict())

    # ─── Critic — 质量审查 ─────────────────────────────────────────────────

    def review_subtask(self, sub_task: SubTask) -> CriticReview:
        """Critic reviews a completed sub_task."""
        prompt = f"""你是一个代码审查专家。请对以下任务执行结果进行评分。

任务标题：{sub_task.title}
任务描述：{sub_task.description}
执行结果：{sub_task.result}

请严格按以下 JSON 格式输出（不要添加任何解释）：
{{"score": 0-10, "comments": "评分理由（中文）", "decision": "accept/reject"}}"""

        response = self._call_aia gent(prompt)
        json_match = re.search(r'\{[\s\S]*\}', response)
        if not json_match:
            raise ValueError(f"Critic failed to return valid JSON: {response}")

        parsed = json.loads(json_match.group())
        decision_str = parsed.get("decision", "accept").lower()
        decision = ReviewDecision.ACCEPT if decision_str == "accept" else ReviewDecision.REJECT
        score = float(parsed.get("score", 5.0))

        review = CriticReview(
            review_id=f"rev_{uuid.uuid4().hex[:12]}",
            orchestration_id=sub_task.parent_orchestration_id,
            sub_task_id=sub_task.sub_task_id,
            critic_agent_id="critic",
            score=score,
            comments=parsed.get("comments", ""),
            decision=decision,
        )
        self._review_store.upsert(review.to_dict())

        if decision == ReviewDecision.REJECT and sub_task.retry_count < MAX_RETRY:
            sub_task.status = TaskStatus.PENDING  # Will be retried
            sub_task.retry_count += 1
            sub_task.updated_at = _now_iso()
            self._subtask_store.upsert(sub_task.to_dict())

        return review

    # ─── SubTask CRUD ───────────────────────────────────────────────────────

    def get_subtask(self, sub_task_id: str) -> Optional[SubTask]:
        data = self._subtask_store.get(sub_task_id)
        return SubTask.from_dict(data) if data else None

    def get_orchestration_subtasks(self, orch_id: str) -> list[SubTask]:
        return [st for st in self._subtask_store.list()
                if st.get("parent_orchestration_id") == orch_id]

    def get_subtask_reviews(self, sub_task_id: str) -> list[CriticReview]:
        return [CriticReview.from_dict(r) for r in self._review_store.list()
                if r.get("sub_task_id") == sub_task_id]

    # ─── 结果汇总 ──────────────────────────────────────────────────────────

    def generate_report(self, orch_id: str) -> str:
        """Generate markdown execution report."""
        orch = self.get_orchestration(orch_id)
        subtasks = [self.get_subtask(sid) for sid in orch.sub_task_ids]
        reviews = {sid: self.get_subtask_reviews(sid) for sid in orch.sub_task_ids}

        lines = [f"# 任务执行报告：{orch.root_task_id}"]
        lines.append(f"\n**编排ID**: {orch.orchestration_id}")
        lines.append(f"**创建时间**: {orch.created_at}")
        lines.append(f"**阶段**: {orch.phase.value if isinstance(orch.phase, OrchestrationPhase) else orch.phase}")
        lines.append(f"\n## 子任务执行结果\n")

        for st in subtasks:
            revs = reviews.get(st.sub_task_id, [])
            last_review = revs[-1] if revs else None
            status_icon = "✅" if st.status == TaskStatus.COMPLETED else ("⚠️" if st.retry_count > 0 else "❌")
            lines.append(f"### {status_icon} {st.title}")
            lines.append(f"- 执行者: {st.assigned_agent_id or '未分配'}")
            lines.append(f"- 重试次数: {st.retry_count}")
            if last_review:
                lines.append(f"- 评分: {last_review.score}/10")
                lines.append(f"- 审查意见: {last_review.comments}")
            lines.append(f"\n**执行结果**:\n{st.result or 'N/A'}\n")

        if orch.context_pool:
            lines.append("\n## 共享上下文\n")
            lines.append(f"```json\n{json.dumps(orch.context_pool, ensure_ascii=False, indent=2)}\n```\n")

        return "\n".join(lines)

    # ─── WebSocket 事件助手 ─────────────────────────────────────────────────

    def emit_ws_event(self, event_type: str, payload: dict):
        """Emit WebSocket event via event bus."""
        from collaboration.events import Event, EventType, get_event_bus
        bus = get_event_bus()
        bus.emit_sync(Event(
            EventType.WS_BROADCAST,
            workspace_id=self.workspace_id,
            payload={"event": event_type, "data": payload},
        ))
```

### 4.1 Storage 扩展

```python
# collaboration/storage.py 新增

def for_orchestrations(ws_path: Path) -> JsonFileStore:
    return JsonFileStore(ws_path / "orchestrations.json")

def for_subtasks(ws_path: Path) -> JsonFileStore:
    return JsonFileStore(ws_path / "subtasks.json")

def for_reviews(ws_path: Path) -> JsonFileStore:
    return JsonFileStore(ws_path / "reviews.json")
```

### 4.2 Events 扩展

```python
# collaboration/events.py 新增 EventType

class EventType(str, Enum):
    # ... existing ...
    ORCHESTRATION_CREATED = "orchestration.created"
    ORCHESTRATION_PLAN_READY = "orchestration.plan_ready"
    ORCHESTRATION_USER_CONFIRMED = "orchestration.user_confirmed"
    ORCHESTRATION_COMPLETED = "orchestration.completed"
    SUBTASK_STARTED = "subtask.started"
    SUBTASK_COMPLETED = "subtask.completed"
    SUBTASK_REJECTED = "subtask.rejected"
    SUBTASK_RETRY = "subtask.retry"
    REVIEW_CREATED = "review.created"
```

---

## 5. REST API Endpoints

### 5.1 创建编排任务

```
POST /api/collab/orchestrations
Body: {
  "root_task_id": "task_xxx",
  "coordinator_id": "agent_xxx",
  "user_task_description": "我要实现一个用户登录功能..."
}
Response: {
  "orchestration_id": "orch_xxx",
  "phase": "planning",
  "sub_tasks": [],  // Coordinator 分解后填充
  "context_pool": {...}
}
```

**逻辑**：
1. 创建 `TaskOrchestration`（phase=PLANNING）
2. 调用 `orchestration_manager.decompose_task()` → Coordinator AIAgent
3. 推送 WebSocket `orchestration.plan_ready`
4. 返回（包含分解计划，等待用户确认）

### 5.2 用户确认分解计划

```
POST /api/collab/orchestrations/{orch_id}/confirm
Response: { "phase": "executing" }
```

**逻辑**：
1. 更新 `Orchestration.phase = EXECUTING`
2. 调用 `run_specialists_parallel()` → Specialist 并行执行
3. 每个完成自动触发 Critic 审查
4. 推送 WebSocket `subtask.completed`, `review.created`, `subtask.rejected`
5. 全部完成后 `phase = COMPLETED`，调用 `generate_report()`
6. 推送 WebSocket `orchestration.completed`

### 5.3 获取编排详情

```
GET /api/collab/orchestrations/{orch_id}
GET /api/collab/orchestrations/{orch_id}/subtasks
GET /api/collab/orchestrations/{orch_id}/report
```

---

## 6. WebSocket Events

| Event | Payload | 触发时机 |
|-------|---------|---------|
| `orchestration.created` | orch_id, root_task_id, phase | 编排创建 |
| `orchestration.plan_ready` | orch_id, sub_tasks[], execution_plan | Coordinator 分解完成 |
| `orchestration.user_confirmed` | orch_id | 用户确认分解计划 |
| `orchestration.completed` | orch_id, report | 全部完成 |
| `subtask.started` | sub_task_id, assigned_agent | Specialist 开始 |
| `subtask.completed` | sub_task_id, result | Specialist 完成 |
| `subtask.rejected` | sub_task_id, score, comments | Critic REJECT |
| `subtask.retry` | sub_task_id, retry_count | 重试触发 |
| `review.created` | review_id, sub_task_id, score, decision | 审查完成 |

---

## 7. Frontend Changes

### 7.1 新增 UI 元素

**任务创建区域**（在现有 Task 创建表单中）：
- 复选框："多Agent模式" (id: `orchestration_mode`)
- 描述文本："启用后任务将由多个 Agent 协同完成"

**编排状态面板**（新增区块）：
- 分解计划展示（子任务列表 + 依赖关系）
- 执行进度（每个子任务的状态 + 实时更新）
- 审查结果（Critic 评分 + 决定）
- 最终报告（Markdown 渲染）

### 7.2 WebSocket 前端处理

```javascript
// 连接
const ws = new WebSocket(`ws://${location.host}/api/collab/ws/${workspace_id}`);
ws.onmessage = (e) => {
  const { event, data } = JSON.parse(e.data);
  switch(event) {
    case 'orchestration.plan_ready':
      renderDecompositionPlan(data.sub_tasks);
      startConfirmCountdown(300); // 5min
      break;
    case 'subtask.started':
      updateSubTaskStatus(data.sub_task_id, 'in_progress');
      break;
    case 'subtask.completed':
      updateSubTaskStatus(data.sub_task_id, 'completed', data.result);
      break;
    case 'review.created':
      showReviewBadge(data.sub_task_id, data.score, data.decision);
      break;
    case 'orchestration.completed':
      showFinalReport(data.report);
      break;
  }
};
```

---

## 8. Implementation Notes

1. **AIAgent 调用**：复用 `hermes-agent-collab-cli` skill 中的 `_hermes_chat()` 模式，设置 `ANTHROPIC_API_KEY=MINIMAX_CN_API_KEY`
2. **ThreadPoolExecutor**：max_workers=4（含 Coordinator/Critic/Specialist），Specialist 实际并发上限3由 `MAX_CONCURRENT_SPECIALISTS` 控制
3. **JSON 存储**：每个 workspace 独立 `orchestrations.json` / `subtasks.json` / `reviews.json`
4. **错误处理**：AIAgent 调用超时（120s），超时视为 Failed
5. **向后兼容**：单Agent模式（不带 `orchestration_mode`）不受影响

---

## 9. New Storage Files

```
~/.hermes/collab/{workspace_id}/
  orchestrations.json    # TaskOrchestration 列表
  subtasks.json          # SubTask 列表
  reviews.json           # CriticReview 列表
```

---

## 10. Verification

- `python3 -m collab.server` 启动无 import 错误
- `curl http://localhost:9119/api/collab/orchestrations` 返回空列表 []
- JSON 文件缺失时自动创建（`JsonFileStore` 已有此行为）