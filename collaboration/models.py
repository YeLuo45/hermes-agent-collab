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


# ─── Agent ────────────────────────────────────────────────────────────────────


@dataclass
class Agent:
    """Agent profile representing a team member (human or AI)."""

    agent_id: str
    name: str
    role: AgentRole | str
    status: AgentStatus | str = AgentStatus.IDLE
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
