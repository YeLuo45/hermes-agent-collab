"""Data models for the collaboration module.

All models are plain Python dataclasses with to_dict/from_dict serialization
support for JSON file storage.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentRole(str, Enum):
    DEVELOPER = "developer"
    PM = "pm"
    QA = "qa"
    CUSTOM = "custom"
    # chatdev-inspired extended roles
    ORCHESTRATOR = "orchestrator"
    EXECUTOR = "executor"
    CRITIC = "critic"
    MONITOR = "monitor"
    SPECIALIST = "specialist"


# Role-specific system prompts (chatdev-inspired)
ROLE_SYSTEM_PROMPTS: dict[str, str] = {
    "orchestrator": "You are the orchestrator. Your role is to coordinate team members, assign tasks, monitor progress, and ensure alignment with project goals. Delegate work appropriately based on each member's capabilities.",
    "executor": "You are the executor. Your role is to carry out specific tasks according to the plan. Focus on completion, quality, and timely delivery of your assigned work.",
    "critic": "You are the critic. Your role is to review plans and work products, provide constructive feedback, identify issues, and ensure quality standards are met. Be thorough and specific in your reviews.",
    "monitor": "You are the monitor. Your role is to track progress, report blockers, update status, and flag risks. Keep stakeholders informed with accurate and timely status updates.",
    "specialist": "You are a specialist. Your role is to provide expert knowledge in your domain. Offer deep technical insight and guidance when called upon.",
    "developer": "You are a developer. Write, review, and refine code following best practices.",
    "pm": "You are a project manager. Coordinate timelines, resources, and stakeholder communication.",
    "qa": "You are a QA engineer. Test thoroughly, identify bugs, and ensure quality.",
}


class AgentStatus(str, Enum):
    IDLE = "idle"
    WORKING = "working"
    BLOCKED = "blocked"
    OFFLINE = "offline"


class TaskStatus(str, Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SkillLevel(str, Enum):
    NOVICE = "novice"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"


class SkillCategory(str, Enum):
    CODE = "code"
    DATA = "data"
    ML = "ml"
    DEVOPS = "devops"
    RESEARCH = "research"
    CREATIVE = "creative"
    OTHER = "other"


class OrchestrationPhase(str, Enum):
    PLANNING = "planning"
    EXECUTING = "executing"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RESUMING = "resuming"


class ReviewDecision(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"


# chatdev-inspired TaskComplexity routing
class TaskComplexity(str, Enum):
    SIMPLE = "simple"       # Single-phase: PENDING → EXECUTING → DONE
    NORMAL = "normal"      # Standard: PENDING → PLANNING → EXECUTING → DONE
    COMPLEX = "complex"     # Full phase-gated: all review gates


class Phase(str, Enum):
    """Phase-gated pipeline phases (chatdev-inspired)."""
    PENDING = "pending"
    PLANNING = "planning"
    PLAN_REVIEW = "plan_review"
    EXECUTING = "executing"
    EXECUTION_REVIEW = "execution_review"
    DONE = "done"
    REJECTED = "rejected"


# ─── Agent ────────────────────────────────────────────────────────────────────


@dataclass
class Agent:
    """Agent profile representing a team member (human or AI)."""

    agent_id: str
    name: str
    role: AgentRole | str
    status: AgentStatus | str = AgentStatus.IDLE
    system_prompt: str | None = None  # chatdev-inspired role-specific prompt
    capabilities: list[str] = field(default_factory=list)
    avatar: str | None = None
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "role": self.role.value if isinstance(self.role, AgentRole) else self.role,
            "status": self.status.value if isinstance(self.status, AgentStatus) else self.status,
            "system_prompt": self.system_prompt,
            "capabilities": self.capabilities,
            "avatar": self.avatar,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Agent":
        role = data.get("role", "developer")
        if isinstance(role, str):
            try:
                role = AgentRole(role)
            except ValueError:
                role = AgentRole.CUSTOM

        status = data.get("status", "idle")
        if isinstance(status, str):
            try:
                status = AgentStatus(status)
            except ValueError:
                status = AgentStatus.IDLE

        return cls(
            agent_id=data["agent_id"],
            name=data["name"],
            role=role,
            status=status,
            system_prompt=data.get("system_prompt"),
            capabilities=data.get("capabilities", []),
            avatar=data.get("avatar"),
            created_at=data.get("created_at", _now_iso()),
            updated_at=data.get("updated_at", _now_iso()),
            metadata=data.get("metadata", {}),
        )

    @staticmethod
    def new(name: str, role: AgentRole | str, capabilities: list[str] | None = None) -> "Agent":
        """Factory to create a new Agent with a fresh UUID."""
        if isinstance(role, str):
            try:
                role = AgentRole(role)
            except ValueError:
                role = AgentRole.CUSTOM
        return Agent(
            agent_id=str(uuid4()),
            name=name,
            role=role,
            capabilities=capabilities or [],
        )


# ─── Task ─────────────────────────────────────────────────────────────────────


@dataclass
class Task:
    """Task entity with full lifecycle support."""

    task_id: str
    title: str
    description: str
    status: TaskStatus | str = TaskStatus.PENDING
    assignee: str | None = None
    creator: str | None = None
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    blocked_reason: str | None = None
    depends_on: list[str] = field(default_factory=list)
    priority: Priority | str = Priority.MEDIUM
    workspace_id: str | None = None
    # chatdev-inspired phase-gated pipeline fields
    complexity: TaskComplexity | str = TaskComplexity.NORMAL
    phase: Phase | str = Phase.PENDING
    phase_history: list[dict] = field(default_factory=list)  # [{phase, decision, approver, comments, timestamp}]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "description": self.description,
            "status": self.status.value if isinstance(self.status, TaskStatus) else self.status,
            "assignee": self.assignee,
            "creator": self.creator,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "blocked_reason": self.blocked_reason,
            "depends_on": self.depends_on,
            "priority": self.priority.value if isinstance(self.priority, Priority) else self.priority,
            "workspace_id": self.workspace_id,
            "complexity": self.complexity.value if isinstance(self.complexity, TaskComplexity) else self.complexity,
            "phase": self.phase.value if isinstance(self.phase, Phase) else self.phase,
            "phase_history": self.phase_history,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        status = data.get("status", "pending")
        if isinstance(status, str):
            try:
                status = TaskStatus(status)
            except ValueError:
                status = TaskStatus.PENDING

        priority = data.get("priority", "medium")
        if isinstance(priority, str):
            try:
                priority = Priority(priority)
            except ValueError:
                priority = Priority.MEDIUM

        return cls(
            task_id=data["task_id"],
            title=data["title"],
            description=data.get("description", ""),
            status=status,
            assignee=data.get("assignee"),
            creator=data.get("creator"),
            created_at=data.get("created_at", _now_iso()),
            updated_at=data.get("updated_at", _now_iso()),
            blocked_reason=data.get("blocked_reason"),
            depends_on=data.get("depends_on", []),
            priority=priority,
            workspace_id=data.get("workspace_id"),
            complexity=data.get("complexity", "normal"),
            phase=data.get("phase", "pending"),
            phase_history=data.get("phase_history", []),
            metadata=data.get("metadata", {}),
        )

    @staticmethod
    def new(title: str, description: str = "", creator: str | None = None, workspace_id: str | None = None) -> "Task":
        """Factory to create a new Task with a fresh UUID."""
        return Task(
            task_id=str(uuid4()),
            title=title,
            description=description,
            creator=creator,
            workspace_id=workspace_id,
        )

    def can_transition_to(self, new_status: TaskStatus) -> bool:
        """Validate task state machine transitions."""
        current = self.status if isinstance(self.status, TaskStatus) else TaskStatus(self.status)
        new = new_status if isinstance(new_status, TaskStatus) else TaskStatus(new_status)

        valid_transitions: dict[TaskStatus, set[TaskStatus]] = {
            TaskStatus.PENDING: {TaskStatus.CLAIMED, TaskStatus.BLOCKED},
            TaskStatus.CLAIMED: {TaskStatus.IN_PROGRESS, TaskStatus.PENDING, TaskStatus.BLOCKED},
            TaskStatus.IN_PROGRESS: {
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.BLOCKED,
                TaskStatus.PENDING,
            },
            TaskStatus.BLOCKED: {TaskStatus.PENDING, TaskStatus.CLAIMED, TaskStatus.IN_PROGRESS},
            TaskStatus.COMPLETED: set(),
            TaskStatus.FAILED: {TaskStatus.PENDING, TaskStatus.CLAIMED, TaskStatus.IN_PROGRESS},
        }
        return new in valid_transitions.get(current, set())


# ─── Skill ────────────────────────────────────────────────────────────────────


@dataclass
class Skill:
    """Reusable skill definition stored in a workspace."""

    skill_id: str
    name: str
    category: SkillCategory | str
    description: str = ""
    version: str = "1.0.0"
    author: str | None = None
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    commands: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    usage_count: int = 0
    workspace_id: str | None = None
    level: SkillLevel | str = SkillLevel.NOVICE
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "category": self.category.value if isinstance(self.category, SkillCategory) else self.category,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "commands": self.commands,
            "tags": self.tags,
            "usage_count": self.usage_count,
            "workspace_id": self.workspace_id,
            "level": self.level.value if isinstance(self.level, SkillLevel) else self.level,
            "enabled": self.enabled,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Skill":
        level = data.get("level", "novice")
        if isinstance(level, str):
            try:
                level = SkillLevel(level)
            except ValueError:
                level = SkillLevel.NOVICE

        category = data.get("category", "other")
        if isinstance(category, str):
            try:
                category = SkillCategory(category)
            except ValueError:
                category = SkillCategory.OTHER

        return cls(
            skill_id=data["skill_id"],
            name=data["name"],
            category=category,
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            author=data.get("author"),
            created_at=data.get("created_at", _now_iso()),
            updated_at=data.get("updated_at", _now_iso()),
            commands=data.get("commands", []),
            tags=data.get("tags", []),
            usage_count=data.get("usage_count", 0),
            workspace_id=data.get("workspace_id"),
            level=level,
            enabled=data.get("enabled", True),
            metadata=data.get("metadata", {}),
        )

    @staticmethod
    def new(
        name: str,
        category: SkillCategory | str,
        description: str = "",
        author: str | None = None,
        workspace_id: str | None = None,
        commands: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> "Skill":
        """Factory to create a new Skill with a fresh UUID."""
        return Skill(
            skill_id=str(uuid4()),
            name=name,
            category=category,
            description=description,
            author=author,
            workspace_id=workspace_id,
            commands=commands or [],
            tags=tags or [],
        )


# ─── Workspace ────────────────────────────────────────────────────────────────


@dataclass
class Workspace:
    """Workspace entity — isolated data container for a team."""

    workspace_id: str
    name: str
    description: str = ""
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    agents: list[str] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "agents": self.agents,
            "settings": self.settings,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Workspace":
        return cls(
            workspace_id=data["workspace_id"],
            name=data["name"],
            description=data.get("description", ""),
            created_at=data.get("created_at", _now_iso()),
            updated_at=data.get("updated_at", _now_iso()),
            agents=data.get("agents", []),
            settings=data.get("settings", {}),
            metadata=data.get("metadata", {}),
        )

    @staticmethod
    def new(name: str, description: str = "") -> "Workspace":
        """Factory to create a new Workspace with a fresh UUID."""
        return Workspace(
            workspace_id=str(uuid4()),
            name=name,
            description=description,
        )


# ─── TaskOrchestration ────────────────────────────────────────────────────────


@dataclass
class TaskOrchestration:
    """Multi-agent orchestration record — coordinates Coordinator/Specialist/Critic workflow."""

    orchestration_id: str
    root_task_id: str
    coordinator_id: str
    owner_id: str = "anonymous"  # User who created this orchestration
    user_task_description: str = ""
    phase: OrchestrationPhase | str = OrchestrationPhase.PLANNING
    sub_task_ids: list[str] = field(default_factory=list)
    context_pool: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "orchestration_id": self.orchestration_id,
            "root_task_id": self.root_task_id,
            "coordinator_id": self.coordinator_id,
            "owner_id": self.owner_id,
            "user_task_description": self.user_task_description,
            "phase": self.phase.value if isinstance(self.phase, OrchestrationPhase) else self.phase,
            "sub_task_ids": self.sub_task_ids,
            "context_pool": self.context_pool,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskOrchestration":
        phase = data.get("phase", "planning")
        if isinstance(phase, str):
            try:
                phase = OrchestrationPhase(phase)
            except ValueError:
                phase = OrchestrationPhase.PLANNING
        return cls(
            orchestration_id=data["orchestration_id"],
            root_task_id=data["root_task_id"],
            coordinator_id=data["coordinator_id"],
            owner_id=data.get("owner_id", "anonymous"),
            user_task_description=data.get("user_task_description", ""),
            phase=phase,
            sub_task_ids=data.get("sub_task_ids", []),
            context_pool=data.get("context_pool", {}),
            created_at=data.get("created_at", _now_iso()),
            updated_at=data.get("updated_at", _now_iso()),
        )


# ─── SubTask ──────────────────────────────────────────────────────────────────


@dataclass
class SubTask:
    """A decomposed sub-task produced by the Coordinator for Specialist execution."""

    sub_task_id: str
    parent_orchestration_id: str
    title: str
    description: str
    assigned_agent_id: str | None = None
    status: TaskStatus | str = TaskStatus.PENDING
    dependencies: list[str] = field(default_factory=list)
    result: str | None = None
    retry_count: int = 0
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        status = self.status.value if isinstance(self.status, TaskStatus) else self.status
        return {
            "sub_task_id": self.sub_task_id,
            "parent_orchestration_id": self.parent_orchestration_id,
            "title": self.title,
            "description": self.description,
            "assigned_agent_id": self.assigned_agent_id,
            "status": status,
            "dependencies": self.dependencies,
            "result": self.result,
            "retry_count": self.retry_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SubTask":
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


# ─── CriticReview ─────────────────────────────────────────────────────────────


@dataclass
class CriticReview:
    """Critic agent's quality review of a completed SubTask."""

    review_id: str
    orchestration_id: str
    sub_task_id: str
    critic_agent_id: str
    score: float
    comments: str
    decision: ReviewDecision | str = ReviewDecision.ACCEPT
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        decision = self.decision.value if isinstance(self.decision, ReviewDecision) else self.decision
        return {
            "review_id": self.review_id,
            "orchestration_id": self.orchestration_id,
            "sub_task_id": self.sub_task_id,
            "critic_agent_id": self.critic_agent_id,
            "score": self.score,
            "comments": self.comments,
            "decision": decision,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CriticReview":
        decision = data.get("decision", "accept")
        if isinstance(decision, str):
            try:
                decision = ReviewDecision(decision)
            except ValueError:
                decision = ReviewDecision.ACCEPT
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


# ─── OrchestrationTemplate ────────────────────────────────────────────────────


@dataclass
class OrchestrationTemplate:
    """A saved template from a successful orchestration — captures the Coordinator's
    decomposition pattern so it can be replayed on a new user task without
    requiring the Coordinator to re-plan."""

    template_id: str
    name: str
    description: str = ""
    # The original orchestration_id this template was created from
    source_orchestration_id: str | None = None
    # Skeleton of the planned subtasks (titles + descriptions + dependency structure)
    # Excludes runtime fields like assigned_agent_id, result, status
    subtask_skeleton: list[dict[str, Any]] = field(default_factory=list)
    # Coordinator configuration hint
    coordinator_config: dict[str, Any] = field(default_factory=dict)
    # Tags for template discovery
    tags: list[str] = field(default_factory=list)
    # Metrics from the source execution
    source_metrics: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "name": self.name,
            "description": self.description,
            "source_orchestration_id": self.source_orchestration_id,
            "subtask_skeleton": self.subtask_skeleton,
            "coordinator_config": self.coordinator_config,
            "tags": self.tags,
            "source_metrics": self.source_metrics,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OrchestrationTemplate":
        return cls(
            template_id=data["template_id"],
            name=data.get("name", ""),
            description=data.get("description", ""),
            source_orchestration_id=data.get("source_orchestration_id"),
            subtask_skeleton=data.get("subtask_skeleton", []),
            coordinator_config=data.get("coordinator_config", {}),
            tags=data.get("tags", []),
            source_metrics=data.get("source_metrics", {}),
            created_at=data.get("created_at", _now_iso()),
        )


# ─── Phase-Gated Pipeline Helpers (chatdev-inspired) ────────────────────────


def evaluate_complexity(task_title: str, task_description: str = "", depends_on: list[str] | None = None) -> TaskComplexity:
    """Evaluate task complexity for phase-gated pipeline routing.

    Scoring heuristic (0-10 scale):
    - Title keywords indicating complexity: +2
    - Description length > 200 chars: +2
    - Has dependencies: +3
    - Priority critical/high: +2
    - Estimated token count (rough): +1 if > 500 chars
    """
    score = 0
    title_lower = task_title.lower()
    task_description = task_description or ""
    desc_len = len(task_description)

    # Complexity keywords in title (stacked for compound effects)
    # "implement" (2) + "architecture" (2) + "system" (2) = 6 for complex tasks
    for kw in ["architecture", "refactor", "pipeline", "workflow"]:
        if kw in title_lower:
            score += 2
    for kw in ["implement", "design", "build", "create", "system"]:
        if kw in title_lower:
            score += 1
    for kw in ["multi", "complex", "distributed"]:
        if kw in title_lower:
            score += 2

    simple_keywords = ["fix", "bump", "typo", "small", "quick", "simple", "minor", "update docs"]
    for kw in simple_keywords:
        if kw in title_lower:
            score -= 2

    # Description length (check higher thresholds first)
    if desc_len > 1000:
        score += 5
    elif desc_len > 500:
        score += 3
    elif desc_len > 200:
        score += 2

    # Has dependencies
    if depends_on and len(depends_on) > 0:
        score += 3

    # Clamp and map to complexity
    score = max(0, min(10, score))
    if score <= 2:
        return TaskComplexity.SIMPLE
    elif score <= 6:
        return TaskComplexity.NORMAL
    else:
        return TaskComplexity.COMPLEX


def get_next_phase(current_phase: Phase, complexity: TaskComplexity, decision: ReviewDecision = ReviewDecision.ACCEPT) -> Phase:
    """Determine the next phase based on current phase and complexity.

    For SIMPLE tasks: PENDING → EXECUTING → DONE (skip all reviews)
    For NORMAL tasks: PENDING → PLANNING → EXECUTING → DONE (skip PLAN_REVIEW)
    For COMPLEX tasks: full phase-gated pipeline
    """
    phase_order = {
        Phase.PENDING: Phase.PLANNING,
        Phase.PLANNING: Phase.PLAN_REVIEW,
        Phase.PLAN_REVIEW: Phase.EXECUTING,
        Phase.EXECUTING: Phase.EXECUTION_REVIEW,
        Phase.EXECUTION_REVIEW: Phase.DONE,
        Phase.DONE: Phase.DONE,
        Phase.REJECTED: Phase.REJECTED,
    }

    if complexity == TaskComplexity.SIMPLE:
        # Skip to EXECUTING from PENDING
        if current_phase == Phase.PENDING:
            return Phase.EXECUTING
        elif current_phase == Phase.EXECUTING:
            return Phase.DONE
    elif complexity == TaskComplexity.NORMAL:
        # Skip PLAN_REVIEW and EXECUTION_REVIEW
        if current_phase == Phase.PLANNING:
            return Phase.EXECUTING
        elif current_phase == Phase.EXECUTING:
            return Phase.DONE

    if decision == ReviewDecision.REJECT:
        return Phase.REJECTED

    return phase_order.get(current_phase, current_phase)


# ─── Hook/Plugin System ───────────────────────────────────────────────────────


class HookEvent(str, Enum):
    """Lifecycle events that plugins can subscribe to."""

    # Agent lifecycle
    AGENT_REGISTERED = "agent.registered"
    AGENT_DEREGISTERED = "agent.deregistered"
    AGENT_STATUS_CHANGED = "agent.status_changed"

    # Task lifecycle
    TASK_CREATED = "task.created"
    TASK_UPDATED = "task.updated"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_PHASE_CHANGED = "task.phase_changed"

    # Orchestration lifecycle
    ORCHESTRATION_CREATED = "orchestration.created"
    ORCHESTRATION_PHASE_CHANGED = "orchestration.phase_changed"
    ORCHESTRATION_COMPLETED = "orchestration.completed"

    # Skill lifecycle
    SKILL_REGISTERED = "skill.registered"
    SKILL_ENABLED = "skill.enabled"
    SKILL_DISABLED = "skill.disabled"

    # System
    WORKSPACE_INITIALIZED = "workspace.initialized"
    SYSTEM_READY = "system.ready"

    # Multi-Agent Protocol (Direction E)
    MESSAGE_SENT = "message.sent"
    MESSAGE_DELIVERED = "message.delivered"
    TASK_DISTRIBUTED = "task.distributed"
    TASK_ASSIGNED = "task.assigned"
    SESSION_CREATED = "session.created"
    SESSION_ENDED = "session.ended"
    CAPABILITY_MATCHED = "capability.matched"


@dataclass
class Plugin:
    """A plugin that subscribes to lifecycle events."""

    plugin_id: str
    name: str
    description: str = ""
    version: str = "1.0.0"
    enabled: bool = True
    hook_handlers: dict[HookEvent, list[str]] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "enabled": self.enabled,
            "hook_handlers": {e.value: hs for e, hs in self.hook_handlers.items()},
            "config": self.config,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Plugin":
        handlers_raw = data.get("hook_handlers", {})
        handlers = {}
        for e_str, hs in handlers_raw.items():
            try:
                handlers[HookEvent(e_str)] = hs
            except ValueError:
                pass
        return cls(
            plugin_id=data["plugin_id"],
            name=data["name"],
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            enabled=data.get("enabled", True),
            hook_handlers=handlers,
            config=data.get("config", {}),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


# ─── Multi-Agent Protocol ──────────────────────────────────────────────────────


class MessageType(str, Enum):
    """Agent-to-agent message types."""

    REQUEST_TASK = "request.task"         # coordinator → worker: please do this
    RESPONSE_RESULT = "response.result"   # worker → coordinator: done
    CAPABILITY_QUERY = "capability.query" # who can do X?
    CAPABILITY_ANNOUNCE = "capability.announce"  # I can do X
    STATE_SYNC = "state.sync"            # periodic heartbeat/state broadcast
    DELEGATION = "delegation"            # I assign this to you
    ACKNOWLEDGMENT = "acknowledgment"     # task received
    HEARTBEAT = "heartbeat"              # I'm alive
    ERROR_REPORT = "error.report"         # something went wrong


class MessageStatus(str, Enum):
    """Delivery status of an agent message."""

    PENDING = "pending"
    DELIVERED = "delivered"
    ACKed = "acked"       # acknowledged by receiver
    FAILED = "failed"
    EXPIRED = "expired"


class SessionStatus(str, Enum):
    """Lifecycle status of an agent session."""

    ACTIVE = "active"
    PAUSED = "paused"
    ENDED = "ended"


@dataclass
class AgentMessage:
    """A message sent between agents."""

    msg_id: str
    sender_id: str
    receiver_id: str | None  # None = broadcast
    msg_type: MessageType | str
    payload: dict[str, Any]
    session_id: str | None = None
    correlation_id: str | None = None
    timestamp: str = field(default_factory=_now_iso)
    ttl_seconds: int = 300
    status: MessageStatus | str = MessageStatus.PENDING

    def to_dict(self) -> dict[str, Any]:
        return {
            "msg_id": self.msg_id,
            "sender_id": self.sender_id,
            "receiver_id": self.receiver_id,
            "msg_type": self.msg_type.value if isinstance(self.msg_type, MessageType) else self.msg_type,
            "payload": self.payload,
            "session_id": self.session_id,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp,
            "ttl_seconds": self.ttl_seconds,
            "status": self.status.value if isinstance(self.status, MessageStatus) else self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentMessage":
        msg_type = data.get("msg_type", "request.task")
        if isinstance(msg_type, str):
            try:
                msg_type = MessageType(msg_type)
            except ValueError:
                msg_type = MessageType.REQUEST_TASK
        status = data.get("status", "pending")
        if isinstance(status, str):
            try:
                status = MessageStatus(status)
            except ValueError:
                status = MessageStatus.PENDING
        return cls(
            msg_id=data["msg_id"],
            sender_id=data["sender_id"],
            receiver_id=data.get("receiver_id"),
            msg_type=msg_type,
            payload=data.get("payload", {}),
            session_id=data.get("session_id"),
            correlation_id=data.get("correlation_id"),
            timestamp=data.get("timestamp", ""),
            ttl_seconds=data.get("ttl_seconds", 300),
            status=status,
        )


@dataclass
class AgentSession:
    """A collaborative session between multiple agents."""

    session_id: str
    participants: list[str]
    context: dict[str, Any] = field(default_factory=dict)
    messages: list[dict] = field(default_factory=list)  # recent messages (for history)
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    status: SessionStatus | str = SessionStatus.ACTIVE

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "participants": self.participants,
            "context": self.context,
            "messages": self.messages,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status.value if isinstance(self.status, SessionStatus) else self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentSession":
        status = data.get("status", "active")
        if isinstance(status, str):
            try:
                status = SessionStatus(status)
            except ValueError:
                status = SessionStatus.ACTIVE
        return cls(
            session_id=data["session_id"],
            participants=data.get("participants", []),
            context=data.get("context", {}),
            messages=data.get("messages", []),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            status=status,
        )


@dataclass
class DelegationPolicy:
    """Policy for how a task should be distributed to agents."""

    type: str = "capability_match"  # "broadcast" | "capability_match" | "指定"
    timeout_seconds: int = 120
    retry_count: int = 2
    min_confidence: float = 0.7

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "timeout_seconds": self.timeout_seconds,
            "retry_count": self.retry_count,
            "min_confidence": self.min_confidence,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DelegationPolicy":
        return cls(
            type=data.get("type", "capability_match"),
            timeout_seconds=data.get("timeout_seconds", 120),
            retry_count=data.get("retry_count", 2),
            min_confidence=data.get("min_confidence", 0.7),
        )


# Policy presets
DELEGATION_BROADCAST = DelegationPolicy(type="broadcast", timeout_seconds=60, retry_count=1, min_confidence=0.0)
DELEGATION_FIRST_RESPOND = DelegationPolicy(type="capability_match", timeout_seconds=120, retry_count=2, min_confidence=0.7)
DELEGATION_CAPABILITY_MATCH = DelegationPolicy(type="capability_match", timeout_seconds=180, retry_count=3, min_confidence=0.8)


@dataclass
class TaskDistribution:
    """Tracks how a task was distributed to agents."""

    distribution_id: str
    task_id: str
    delegation_policy: DelegationPolicy
    candidates: list[str] = field(default_factory=list)
    assigned_agents: list[str] = field(default_factory=list)
    distribution_result: dict[str, Any] | None = None
    created_at: str = field(default_factory=_now_iso)
    status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        return {
            "distribution_id": self.distribution_id,
            "task_id": self.task_id,
            "delegation_policy": self.delegation_policy.to_dict(),
            "candidates": self.candidates,
            "assigned_agents": self.assigned_agents,
            "distribution_result": self.distribution_result,
            "created_at": self.created_at,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskDistribution":
        return cls(
            distribution_id=data["distribution_id"],
            task_id=data["task_id"],
            delegation_policy=DelegationPolicy.from_dict(data.get("delegation_policy", {})),
            candidates=data.get("candidates", []),
            assigned_agents=data.get("assigned_agents", []),
            distribution_result=data.get("distribution_result"),
            created_at=data.get("created_at", ""),
            status=data.get("status", "pending"),
        )


@dataclass
class CapabilityMatchResult:
    """Result of a capability matching query."""

    query: str
    matched_agents: list[tuple[str, float]]  # (agent_id, confidence)
    best_candidate: str | None
    match_method: str = "capability_match"

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "matched_agents": self.matched_agents,
            "best_candidate": self.best_candidate,
            "match_method": self.match_method,
        }
