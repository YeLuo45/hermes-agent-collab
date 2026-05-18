"""hermes-agent-collab Python SDK.

A Python client library for hermes-agent-collab multi-agent collaboration system.

Usage::

    from hermes_agent_collab import HermesCollab, Config

    client = HermesCollab(Config(
        api_key="default:sk_xxx",
        base_url="http://localhost:8000/api/collab/v1",
    ))

    # List agents
    agents = client.agents.list()

    # Create a task
    task = client.tasks.create(title="Build API", priority="high")

    # Start an orchestration
    orch = client.orchestrations.create(title="Deploy", complexity="normal")
    client.orchestrations.start(orch.orchestration_id)

    # Stream events
    for event in client.events.stream():
        print(event.event_type, event.payload)
"""

from .client import Config, HermesCollab
from .exceptions import (
    AuthError,
    HermesCollabError,
    NetworkError,
    NotFoundError,
    ValidationError,
    WebSocketError,
)
from .models import (
    AgentMetadata,
    AgentResponse,
    ApiKeyResponse,
    Event,
    HealthResponse,
    MessageResponse,
    MessageSendRequest,
    OrchestrationCreateRequest,
    OrchestrationResponse,
    SessionResponse,
    SkillCreateRequest,
    SkillResponse,
    TaskCreateRequest,
    TaskResponse,
    WorkspaceResponse,
)
from .websocket import WebSocketClient

__all__ = [
    # Client
    "HermesCollab",
    "Config",
    # Exceptions
    "HermesCollabError",
    "AuthError",
    "NotFoundError",
    "ValidationError",
    "NetworkError",
    "WebSocketError",
    # Models
    "AgentMetadata",
    "AgentResponse",
    "ApiKeyResponse",
    "Event",
    "HealthResponse",
    "MessageResponse",
    "MessageSendRequest",
    "OrchestrationCreateRequest",
    "OrchestrationResponse",
    "SessionResponse",
    "SkillCreateRequest",
    "SkillResponse",
    "TaskCreateRequest",
    "TaskResponse",
    "WorkspaceResponse",
    # WebSocket
    "WebSocketClient",
]

__version__ = "1.0.0"
