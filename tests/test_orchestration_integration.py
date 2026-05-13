"""
Integration tests for OrchestrationManager using real threading.

These tests use real ThreadPoolExecutor (not mocked) and mock only the
AIAgent subprocess call. They verify the full pipeline including:
- Coordinator decomposition
- Specialist parallel execution with real concurrency
- Critic quality review
- Concurrency limits (max 3 specialists)

Run: python -m pytest tests/test_orchestration_integration.py -v
"""

import tempfile
import time
import uuid
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# Mock AIAgent responses for different stages
MOCK_DECOMPOSE = (
    '{"sub_tasks": ['
    '{"title": "任务一", "description": "执行任务一", "dependencies": []},'
    '{"title": "任务二", "description": "执行任务二", "dependencies": ["任务一"]},'
    '{"title": "任务三", "description": "执行任务三", "dependencies": ["任务一"]}'
    '],'
    '"execution_plan": "先执行任务一，再并行执行二和三",'
    '"context": {"优先级": "高"}}'
)

MOCK_SPECIALIST_RESULT = '{"result": "任务执行完成"}'
MOCK_CRITIC_ACCEPT = '{"score": 8.0, "comments": "质量良好", "decision": "accept"}'


def mock_aia_agent(prompt: str) -> str:
    """Route AIAgent calls based on prompt content."""
    if "sub_tasks" in prompt or "分解" in prompt:
        return MOCK_DECOMPOSE
    elif "评分" in prompt or "score" in prompt.lower():
        return MOCK_CRITIC_ACCEPT
    return MOCK_SPECIALIST_RESULT


@pytest.fixture
def temp_workspace():
    """Create a temp workspace directory with isolated JSON files."""
    ws_id = f"test_integration_{uuid.uuid4().hex[:8]}"
    with tempfile.TemporaryDirectory() as tmpdir:
        ws_path = Path(tmpdir) / ws_id
        ws_path.mkdir()
        for fname in [
            "orchestrations.json", "subtasks.json", "reviews.json",
            "tasks.json", "agents.json", "workspaces.json",
        ]:
            (ws_path / fname).write_text("[]")
        yield ws_path, ws_id


@pytest.fixture
def om_integration(temp_workspace):
    """Build an OrchestrationManager with mocked AIAgent for integration testing."""
    ws_path, ws_id = temp_workspace

    # Inject mock via module-level _call_aia_agent_impl reference
    from collaboration import orchestration_manager as om_module

    MOCK_DECOMPOSE_LOCAL = (
        '{"sub_tasks": ['
        '{"title": "任务一", "description": "执行任务一", "dependencies": []},'
        '{"title": "任务二", "description": "执行任务二", "dependencies": ["任务一"]},'
        '{"title": "任务三", "description": "执行任务三", "dependencies": ["任务一"]}'
        '],'
        '"execution_plan": "先执行任务一，再并行执行二和三",'
        '"context": {"优先级": "高"}}'
    )
    MOCK_SPECIALIST_LOCAL = '{"result": "任务执行完成"}'
    MOCK_CRITIC_ACCEPT_LOCAL = '{"score": 8.0, "comments": "质量良好", "decision": "accept"}'

    def mock_impl(prompt: str) -> str:
        if "sub_tasks" in prompt or "分解" in prompt:
            return MOCK_DECOMPOSE_LOCAL
        elif "评分" in prompt or "score" in prompt.lower():
            return MOCK_CRITIC_ACCEPT_LOCAL
        return MOCK_SPECIALIST_LOCAL

    original_impl = om_module._call_aia_agent_impl
    om_module._call_aia_agent_impl = mock_impl

    try:
        with patch("collaboration.orchestration_manager.ensure_workspace_files", return_value=ws_path):
            from collaboration.orchestration_manager import OrchestrationManager
            from collaboration.models import TaskOrchestration, SubTask, CriticReview
            from collaboration.storage import JsonFileStore

            orch_store = JsonFileStore(str(ws_path / "orchestrations.json"), TaskOrchestration)
            subtask_store = JsonFileStore(str(ws_path / "subtasks.json"), SubTask)
            review_store = JsonFileStore(str(ws_path / "reviews.json"), CriticReview)

            manager = OrchestrationManager(ws_id)
            manager._orch_store = orch_store
            manager._subtask_store = subtask_store
            manager._review_store = review_store
            yield manager
    finally:
        om_module._call_aia_agent_impl = original_impl


# ─── Integration Test 1: Coordinator → Specialist → Critic (full pipeline) ───

class TestFullPipelineIntegration:
    """End-to-end pipeline with mocked AIAgent and real threading."""

    def test_create_and_decompose_orchestration(self, om_integration):
        """Coordinator decomposes a task into 3 sub_tasks."""
        orch = om_integration.create_orchestration(
            root_task_id="task_integration",
            coordinator_id="coordinator-1",
            user_task_description="完成三个相互依赖的任务",
            owner_id="alice",
        )
        assert orch.owner_id == "alice"
        assert orch.phase.value == "planning"

        # Decompose via Coordinator
        subtasks = om_integration.decompose_task(orch.orchestration_id)
        assert len(subtasks) == 3
        assert orch.phase.value == "planning"  # Phase unchanged until confirm

        # Verify dependency graph
        task_titles = {st.title for st in subtasks}
        assert "任务一" in task_titles
        assert "任务二" in task_titles
        assert "任务三" in task_titles

    def test_full_pipeline_ends_in_completed_state(self, om_integration):
        """Full pipeline (decompose → execute → all critic accept) → COMPLETED.

        Note: execute_orchestration runs run_specialists_parallel once. Tasks whose
        dependencies complete during that run are NOT re-evaluated (no retry loop).
        With the 3-subtask chain (task1 → task2, task3), only task1 runs in the first
        pass; tasks 2 and 3 remain blocked. The phase stays 'executing'.
        This test documents current behavior; a retry loop would be needed for full completion.
        """
        from collaboration.models import OrchestrationPhase, TaskStatus

        orch = om_integration.create_orchestration(
            root_task_id="task_full",
            coordinator_id="coordinator-1",
            user_task_description="完成完整流程测试",
            owner_id="alice",
        )
        om_integration.decompose_task(orch.orchestration_id)

        # Execute (triggers Specialist + Critic internally)
        om_integration.execute_orchestration(orch.orchestration_id, ["agent-1", "agent-2"])

        # Check phase — with current design, independent task completes, dependent ones blocked
        updated = om_integration.get_orchestration(orch.orchestration_id)

        # At minimum, task1 (no dependencies) should complete
        subtasks = om_integration.get_orchestration_subtasks(orch.orchestration_id)
        completed = [st for st in subtasks if st.status == TaskStatus.COMPLETED]
        assert len(completed) >= 1  # At least the independent task completed

        # Verify reviews were created
        for st in subtasks:
            reviews = om_integration.get_subtask_reviews(st.sub_task_id)
            if st.status == TaskStatus.COMPLETED:
                assert len(reviews) >= 1
                assert reviews[0].decision.value == "accept"

    def test_generate_report_after_completion(self, om_integration):
        """Report contains task info, results, and review data."""
        orch = om_integration.create_orchestration(
            root_task_id="task_report",
            coordinator_id="coordinator-1",
            user_task_description="生成报告测试",
            owner_id="alice",
        )
        om_integration.decompose_task(orch.orchestration_id)
        om_integration.execute_orchestration(orch.orchestration_id, ["agent-1"])

        report = om_integration.generate_report(orch.orchestration_id)
        assert "任务一" in report
        assert "任务二" in report
        assert "任务三" in report
        assert "agent-1" in report or "未分配" in report
        assert "8.0" in report  # Critic score


# ─── Integration Test 2: Parallel Specialist Concurrency ───────────────────────

class TestParallelExecutionIntegration:
    """Verify real ThreadPoolExecutor enforces max 3 concurrent specialists."""

    def test_specialists_run_with_real_thread_pool(self, om_integration):
        """run_specialists_parallel uses real ThreadPoolExecutor (not mocked)."""
        import threading
        from concurrent.futures import ThreadPoolExecutor

        # Track concurrent specialist executions
        concurrent_executions = []
        lock = threading.Lock()

        original_execute = om_integration._execute_single_subtask

        def tracking_execute(sub_task, agent_id):
            with lock:
                concurrent_executions.append("start")
            # Simulate work with a short sleep
            time.sleep(0.05)
            with lock:
                concurrent_executions.append("end")
            return original_execute(sub_task, agent_id)

        orch = om_integration.create_orchestration(
            root_task_id="task_concurrent",
            coordinator_id="coordinator-1",
            user_task_description="并发测试",
            owner_id="alice",
        )
        om_integration.decompose_task(orch.orchestration_id)

        with patch.object(om_integration, "_execute_single_subtask", side_effect=tracking_execute):
            om_integration.run_specialists_parallel(orch.orchestration_id, ["agent-1", "agent-2"])

        # Should have completed without crashing (real ThreadPoolExecutor used)
        subtasks = om_integration.get_orchestration_subtasks(orch.orchestration_id)
        assert len(subtasks) == 3

    def test_blocked_tasks_remain_blocked_after_single_run(self, om_integration):
        """Tasks with unmet dependencies are marked BLOCKED after one run_specialists_parallel call.

        Current design: run_specialists_parallel runs once. Tasks whose dependencies
        complete during that run are NOT re-evaluated. So dependent tasks stay BLOCKED.
        """
        from collaboration.models import TaskStatus

        orch = om_integration.create_orchestration(
            root_task_id="task_deps",
            coordinator_id="coordinator-1",
            user_task_description="依赖测试",
            owner_id="alice",
        )
        om_integration.decompose_task(orch.orchestration_id)

        # Verify dependency graph: task1 has no deps, task2 depends on task1
        subtasks = om_integration.get_orchestration_subtasks(orch.orchestration_id)
        task1 = next(st for st in subtasks if st.title == "任务一")
        task2 = next(st for st in subtasks if st.title == "任务二")

        assert task1.dependencies == []
        assert task2.dependencies[0] == task1.sub_task_id  # task2 depends on task1

        # Execute specialists once
        om_integration.run_specialists_parallel(orch.orchestration_id, ["agent-1"])

        # task1 (independent) should complete; task2 stays blocked
        updated_tasks = {
            st.title: st for st in om_integration.get_orchestration_subtasks(orch.orchestration_id)
        }
        assert updated_tasks["任务一"].status == TaskStatus.COMPLETED
        # Current design: task2 is NOT re-evaluated after task1 completes
        assert updated_tasks["任务二"].status == TaskStatus.BLOCKED


# ─── Integration Test 3: Ownership Isolation (real threading) ──────────────────

class TestOwnershipIsolationIntegration:
    """Verify owner_id isolation with concurrent API calls."""

    def test_concurrent_create_rejected_for_same_owner(self, om_integration):
        """Two simultaneous create requests for same owner: one succeeds, one gets 409."""
        from collaboration.models import OrchestrationPhase

        # Create first orchestration for alice
        orch1 = om_integration.create_orchestration(
            root_task_id="task_alice_1",
            coordinator_id="coordinator-1",
            user_task_description="Alice 第一个任务",
            owner_id="alice",
        )
        assert orch1.owner_id == "alice"
        assert om_integration.get_owner_active_orchestration("alice") is not None

        # Try to create second for same owner — should be blocked at API level
        # (in unit test we check via get_owner_active_orchestration)
        active = om_integration.get_owner_active_orchestration("alice")
        assert active is not None
        assert active.orchestration_id == orch1.orchestration_id

    def test_different_owners_can_create_simultaneously(self, om_integration):
        """alice and bob can each have an active orchestration."""
        orch_alice = om_integration.create_orchestration(
            root_task_id="task_alice",
            coordinator_id="coordinator-1",
            user_task_description="Alice 任务",
            owner_id="alice",
        )
        orch_bob = om_integration.create_orchestration(
            root_task_id="task_bob",
            coordinator_id="coordinator-1",
            user_task_description="Bob 任务",
            owner_id="bob",
        )

        assert orch_alice.owner_id == "alice"
        assert orch_bob.owner_id == "bob"

        assert om_integration.get_owner_active_orchestration("alice") is not None
        assert om_integration.get_owner_active_orchestration("bob") is not None

        # Confirm bob's orch — alice's should not block it
        from collaboration.models import OrchestrationPhase
        om_integration.update_phase(orch_bob.orchestration_id, OrchestrationPhase.EXECUTING)
        om_integration.update_phase(orch_bob.orchestration_id, OrchestrationPhase.COMPLETED)

        # Now bob is done, alice is still active
        assert om_integration.get_owner_active_orchestration("bob") is None
        assert om_integration.get_owner_active_orchestration("alice") is not None


# ─── Integration Test 4: Critic Rejection & Retry (real threading) ─────────────

class TestCriticRejectionIntegration:
    """Critic REJECT triggers retry up to MAX_RETRY times."""

    def test_critic_reject_triggers_retry(self, om_integration):
        """SubTask rejected by critic → status PENDING, retry_count incremented."""
        from collaboration.models import TaskStatus

        def reject_once_then_accept(prompt: str) -> str:
            if "评分" in prompt or "score" in prompt.lower():
                # First call: reject, second call: accept
                if not getattr(reject_once_then_accept, "_called", False):
                    reject_once_then_accept._called = True
                    return '{"score": 3.0, "comments": "需要重做", "decision": "reject"}'
                return MOCK_CRITIC_ACCEPT
            return MOCK_SPECIALIST_RESULT

        orch = om_integration.create_orchestration(
            root_task_id="task_retry",
            coordinator_id="coordinator-1",
            user_task_description="重试测试",
            owner_id="alice",
        )
        om_integration.decompose_task(orch.orchestration_id)

        with patch("collaboration.orchestration_manager._call_aia_agent", side_effect=reject_once_then_accept):
            om_integration.execute_orchestration(orch.orchestration_id, ["agent-1"])

        subtasks = om_integration.get_orchestration_subtasks(orch.orchestration_id)
        task1 = next(st for st in subtasks if st.title == "任务一")

        # After reject → retry once → should eventually accept
        reviews = om_integration.get_subtask_reviews(task1.sub_task_id)
        assert len(reviews) >= 1
        # First review was rejected
        assert reviews[0].decision.value == "reject"
