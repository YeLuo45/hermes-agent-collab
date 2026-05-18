"""Pydantic models mirroring hermes-agent-collab REST API."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ─── Shared ───────────────────────────────────────────────────────────────────

class AgentMetadata(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    skills: list[str] = Field(default_factory=list)
    status: str = "offline"
    system_id: Optional[str] = None
    updated_at: Optional[str] = None


class AgentResponse(AgentMetadata):
    agent_id: str
    created_at: str


class TaskResponse(BaseModel):
    task_id: str
    title: str
    description: Optional[str] = None
    status: str = "pending"
    priority: str = "medium"
    complexity: Optional[str] = None
    assignee_id: Optional[str] = None
    subtasks: list[dict[str, Any]] = Field(default_factory=list)
    phase: Optional[str] = None
    phase_history: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: Optional[str] = None


class TaskCreateRequest(BaseModel):
    title: str
    description: Optional[str] = None
    priority: str = "medium"
    complexity: Optional[str] = None
    assignee_id: Optional[str] = None


class SkillResponse(BaseModel):
    skill_id: str
    name: str
    category: str
    description: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class SkillCreateRequest(BaseModel):
    name: str
    category: str
    description: str = ""
    config: dict[str, Any] = Field(default_factory=dict)


class OrchestrationResponse(BaseModel):
    orchestration_id: str
    title: str
    phase: str = "planning"
    complexity: Optional[str] = None
    subtasks: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str
    updated_at: Optional[str] = None


class OrchestrationCreateRequest(BaseModel):
    title: str
    complexity: Optional[str] = "normal"


class MessageResponse(BaseModel):
    msg_id: str
    sender_id: str
    receiver_id: Optional[str] = None
    content: str
    msg_type: str = "text"
    timestamp: str


class MessageSendRequest(BaseModel):
    content: str
    receiver_id: Optional[str] = None
    msg_type: str = "text"


class SessionResponse(BaseModel):
    session_id: str
    participants: list[str] = Field(default_factory=list)
    created_at: str


class WorkspaceResponse(BaseModel):
    workspace_id: str
    name: str
    description: str = ""
    created_at: str


class ApiKeyResponse(BaseModel):
    key_id: str
    name: str
    workspace_id: str
    scopes: list[str]
    created_at: str
    last_used_at: Optional[str] = None
    is_active: bool
    key_secret: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    timestamp: str
    uptime_seconds: float
    version: str = "1.0.0"


class Event(BaseModel):
    event_type: str
    workspace_id: Optional[str] = None
    timestamp: str
    payload: dict[str, Any] = Field(default_factory=dict)
    cursor: Optional[str] = None

    class Config:
        extra = "allow"
