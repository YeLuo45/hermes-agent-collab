"""HermesCollab Python SDK — main client class."""

from __future__ import annotations

import os
import logging
from typing import Any, Optional

import httpx
from pydantic import BaseModel

from .exceptions import AuthError, HermesCollabError, NetworkError, NotFoundError, ValidationError
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

_log = logging.getLogger(__name__)


class Config(BaseModel):
    """SDK configuration."""

    api_key: Optional[str] = None
    base_url: str = "http://localhost:8000/api/collab/v1"
    timeout: float = 30.0
    verify_ssl: bool = True


class _Agents:
    def __init__(self, client: "HermesCollab"):
        self._c = client

    def list(self) -> list[AgentResponse]:
        r = self._c._get("/agents")
        return [AgentResponse(**a) for a in r.get("agents", [])]

    def get(self, agent_id: str) -> AgentResponse:
        r = self._c._get(f"/agents/{agent_id}")
        return AgentResponse(**r)

    def register(
        self,
        name: str,
        role: str = "executor",
        skills: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> AgentResponse:
        payload = {"name": name, "role": role, "skills": skills or [], "metadata": metadata or {}}
        r = self._c._post("/agents/register", payload)
        return AgentResponse(**r)

    def deregister(self, agent_id: str) -> dict[str, Any]:
        return self._c._post(f"/agents/{agent_id}/deregister", {})

    def update_status(self, agent_id: str, status: str) -> AgentResponse:
        r = self._c._put(f"/agents/{agent_id}/status", {"status": status})
        return AgentResponse(**r)


class _Tasks:
    def __init__(self, client: "HermesCollab"):
        self._c = client

    def list(self, status: Optional[str] = None, limit: int = 100) -> list[TaskResponse]:
        params = {"limit": limit}
        if status:
            params["status"] = status
        r = self._c._get("/tasks", params=params)
        return [TaskResponse(**t) for t in r.get("tasks", [])]

    def get(self, task_id: str) -> TaskResponse:
        r = self._c._get(f"/tasks/{task_id}")
        return TaskResponse(**r)

    def create(
        self,
        title: str,
        description: Optional[str] = None,
        priority: str = "medium",
        complexity: Optional[str] = None,
        assignee_id: Optional[str] = None,
    ) -> TaskResponse:
        payload = TaskCreateRequest(
            title=title,
            description=description,
            priority=priority,
            complexity=complexity,
            assignee_id=assignee_id,
        )
        r = self._c._post("/tasks", payload.model_dump())
        return TaskResponse(**r)

    def update_status(self, task_id: str, status: str) -> TaskResponse:
        r = self._c._put(f"/tasks/{task_id}/status", {"status": status})
        return TaskResponse(**r)

    def complete(self, task_id: str) -> TaskResponse:
        r = self._c._post(f"/tasks/{task_id}/complete", {})
        return TaskResponse(**r)

    def fail(self, task_id: str, reason: Optional[str] = None) -> TaskResponse:
        r = self._c._post(f"/tasks/{task_id}/fail", {"reason": reason})
        return TaskResponse(**r)


class _Skills:
    def __init__(self, client: "HermesCollab"):
        self._c = client

    def list(self) -> list[SkillResponse]:
        r = self._c._get("/skills")
        return [SkillResponse(**s) for s in r.get("skills", [])]

    def register(
        self,
        name: str,
        category: str,
        description: str = "",
        config: Optional[dict[str, Any]] = None,
    ) -> SkillResponse:
        payload = SkillCreateRequest(name=name, category=category, description=description, config=config or {})
        r = self._c._post("/skills", payload.model_dump())
        return SkillResponse(**r)

    def get(self, skill_id: str) -> SkillResponse:
        r = self._c._get(f"/skills/{skill_id}")
        return SkillResponse(**r)

    def update(self, skill_id: str, **kwargs) -> SkillResponse:
        r = self._c._patch(f"/skills/{skill_id}", kwargs)
        return SkillResponse(**r)


class _Orchestrations:
    def __init__(self, client: "HermesCollab"):
        self._c = client

    def list(self) -> list[OrchestrationResponse]:
        r = self._c._get("/orchestrations")
        return [OrchestrationResponse(**o) for o in r.get("orchestrations", [])]

    def get(self, orchestration_id: str) -> OrchestrationResponse:
        r = self._c._get(f"/orchestrations/{orchestration_id}")
        return OrchestrationResponse(**r)

    def create(self, title: str, complexity: Optional[str] = "normal") -> OrchestrationResponse:
        payload = OrchestrationCreateRequest(title=title, complexity=complexity)
        r = self._c._post("/orchestrations", payload.model_dump())
        return OrchestrationResponse(**r)

    def start(self, orchestration_id: str) -> OrchestrationResponse:
        r = self._c._post(f"/orchestrations/{orchestration_id}/start", {})
        return OrchestrationResponse(**r)

    def next_phase(self, orchestration_id: str) -> OrchestrationResponse:
        r = self._c._post(f"/orchestrations/{orchestration_id}/next-phase", {})
        return OrchestrationResponse(**r)


class _Messages:
    def __init__(self, client: "HermesCollab"):
        self._c = client

    def send(
        self,
        content: str,
        receiver_id: Optional[str] = None,
        msg_type: str = "text",
    ) -> MessageResponse:
        payload = MessageSendRequest(content=content, receiver_id=receiver_id, msg_type=msg_type)
        r = self._c._post("/messages/send", payload.model_dump())
        return MessageResponse(**r)

    def list(self, session_id: Optional[str] = None) -> list[MessageResponse]:
        params = {"session_id": session_id} if session_id else {}
        r = self._c._get("/messages", params=params)
        return [MessageResponse(**m) for m in r.get("messages", [])]


class _Sessions:
    def __init__(self, client: "HermesCollab"):
        self._c = client

    def create(self, participant_ids: Optional[list[str]] = None) -> SessionResponse:
        r = self._c._post("/sessions", {"participant_ids": participant_ids or []})
        return SessionResponse(**r)

    def get(self, session_id: str) -> SessionResponse:
        r = self._c._get(f"/sessions/{session_id}")
        return SessionResponse(**r)


class _Workspaces:
    def __init__(self, client: "HermesCollab"):
        self._c = client

    def list(self) -> list[WorkspaceResponse]:
        r = self._c._get("/workspaces")
        return [WorkspaceResponse(**ws) for ws in r.get("workspaces", [])]

    def create(self, workspace_id: str, name: str, description: str = "") -> WorkspaceResponse:
        r = self._c._post("/workspaces", {"workspace_id": workspace_id, "name": name, "description": description})
        return WorkspaceResponse(**r)

    def get(self, workspace_id: str) -> WorkspaceResponse:
        r = self._c._get(f"/workspaces/{workspace_id}")
        return WorkspaceResponse(**r)


class _Auth:
    def __init__(self, client: "HermesCollab"):
        self._c = client

    def create_key(
        self,
        name: str,
        workspace_id: str = "default",
        scopes: Optional[list[str]] = None,
    ) -> ApiKeyResponse:
        r = self._c._post(
            "/auth/keys",
            {"name": name, "workspace_id": workspace_id, "scopes": scopes or ["read"]},
        )
        return ApiKeyResponse(**r)

    def list_keys(self, workspace_id: str = "default") -> list[ApiKeyResponse]:
        r = self._c._get("/auth/keys", params={"workspace_id": workspace_id})
        return [ApiKeyResponse(**k) for k in r.get("keys", [])]

    def revoke_key(self, key_id: str, workspace_id: str = "default") -> dict[str, Any]:
        return self._c._delete(f"/auth/keys/{key_id}", params={"workspace_id": workspace_id})


class _Events:
    def __init__(self, client: "HermesCollab"):
        self._c = client

    def stream(
        self,
        workspace_id: Optional[str] = None,
        timeout: int = 60,
        event_types: Optional[list[str]] = None,
    ):
        """Yield events from SSE stream as an iterator."""
        params = {"timeout": timeout}
        if workspace_id:
            params["workspace_id"] = workspace_id
        if event_types:
            params["event_types"] = ",".join(event_types)

        url = f"{self._c._base_url}/sse"
        headers = self._c._auth_headers

        with self._c._session.stream("GET", url, params=params, headers=headers, timeout=float(timeout + 5)) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line or line.startswith(":"):
                    continue
                if line.startswith("data:"):
                    import json as _json

                    data = line[5:].strip()
                    if data:
                        try:
                            yield Event(**_json.loads(data))
                        except Exception:
                            pass


class HermesCollab:
    """Python SDK for hermes-agent-collab REST API.

    Usage::

        from hermes_agent_collab import HermesCollab, Config

        client = HermesCollab(Config(
            api_key="default:sk_xxx",
            base_url="http://localhost:8000/api/collab/v1",
        ))

        agents = client.agents.list()
        task = client.tasks.create(title="Build feature", priority="high")
        orch = client.orchestrations.create(title="Deploy", complexity="normal")
        client.orchestrations.start(orch.orchestration_id)

        for event in client.events.stream():
            print(event.event_type, event.payload)
    """

    def __init__(self, config: Optional[Config] = None, **kwargs):
        if config is None:
            config = Config(**kwargs)
        self._config = config
        self._base_url = config.base_url.rstrip("/")
        self._timeout = config.timeout

        # Build auth headers
        self._auth_headers = {}
        api_key = config.api_key or os.environ.get("HERMES_COLLAB_API_KEY", "")
        if api_key:
            self._auth_headers["X-API-Key"] = api_key

        self._session = httpx.Client(
            base_url=self._base_url,
            timeout=config.timeout,
            verify=config.verify_ssl,
            headers=self._auth_headers,
        )

        # Sub-resources
        self.agents = _Agents(self)
        self.tasks = _Tasks(self)
        self.skills = _Skills(self)
        self.orchestrations = _Orchestrations(self)
        self.messages = _Messages(self)
        self.sessions = _Sessions(self)
        self.workspaces = _Workspaces(self)
        self.auth = _Auth(self)
        self.events = _Events(self)

    def close(self):
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def websocket(
        self,
        workspace_id: str = "default",
        on_message: Optional[callable] = None,
    ) -> WebSocketClient:
        """Return a WebSocket client for bidirectional communication."""
        ws_url = self._base_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/ws/{workspace_id}"
        return WebSocketClient(
            url=ws_url,
            on_message=on_message,
        )

    def health(self) -> HealthResponse:
        r = self._get("/health")
        return HealthResponse(**r)

    # ─── HTTP helpers ────────────────────────────────────────────────────────

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            resp = self._session.request(method, url, **kwargs)
        except httpx.ConnectError as e:
            raise NetworkError(f"Connection failed: {e}") from e
        except httpx.TimeoutException as e:
            raise NetworkError(f"Request timed out: {e}") from e

        if resp.status_code == 401:
            raise AuthError(resp.text)
        if resp.status_code == 404:
            raise NotFoundError(resp.text)
        if resp.status_code == 422:
            raise ValidationError(resp.text)

        if not resp.is_success:
            raise HermesCollabError(f"HTTP {resp.status_code}: {resp.text}")

        if resp.content:
            return resp.json()
        return {}

    def _get(self, path: str, params: Optional[dict] = None) -> dict[str, Any]:
        return self._request("GET", path, params=params)

    def _post(self, path: str, data: dict) -> dict[str, Any]:
        return self._request("POST", path, json=data)

    def _put(self, path: str, data: dict) -> dict[str, Any]:
        return self._request("PUT", path, json=data)

    def _patch(self, path: str, data: dict) -> dict[str, Any]:
        return self._request("PATCH", path, json=data)

    def _delete(self, path: str, params: Optional[dict] = None) -> dict[str, Any]:
        return self._request("DELETE", path, params=params)
