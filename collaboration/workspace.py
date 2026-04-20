"""Workspace management for the collaboration module.

Provides WorkspaceManager for CRUD operations on workspaces, including
listing, creating, switching, and deleting workspaces at the ~/.hermes/workspaces/ directory.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from collaboration.events import Event, EventType, get_event_bus
from collaboration.models import Agent, AgentRole, Workspace
from collaboration.storage import (
    HERMES_HOME,
    WORKSPACES_DIR,
    CURRENT_WS_FILE,
    JsonFileStore,
    ensure_workspace_files,
    get_current_workspace_id,
    get_workspace_path,
    set_current_workspace_id,
)

_log = logging.getLogger(__name__)


class WorkspaceManager:
    """Manages workspace lifecycle.

    All mutating methods emit events via the collaboration event bus.
    """

    def __init__(self, base_path: str = None):
        self._bus = get_event_bus()
        if base_path:
            global WORKSPACES_DIR
            WORKSPACES_DIR = Path(base_path).expanduser() / "workspaces"
        WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)

    # ─── CRUD ─────────────────────────────────────────────────────────────────

    def list(self) -> list[Workspace]:
        """List all workspaces."""
        if not WORKSPACES_DIR.exists():
            return []
        stores = []
        for subdir in WORKSPACES_DIR.iterdir():
            if subdir.is_dir() and subdir.name != ".current":
                ws_file = subdir / "workspace.json"
                if ws_file.exists():
                    store = JsonFileStore(ws_file, Workspace)
                    stores.append(store)
        # Also check root-level workspace.json for default workspace
        root_ws = WORKSPACES_DIR / "workspace.json"
        if root_ws.exists() and root_ws not in [s._path for s in stores]:
            store = JsonFileStore(root_ws, Workspace)
            stores.append(store)
        result = []
        seen_ids = set()
        for store in stores:
            for ws in store.list():
                if ws.workspace_id not in seen_ids:
                    result.append(ws)
                    seen_ids.add(ws.workspace_id)
        return result

    def get(self, workspace_id: str) -> Workspace | None:
        """Get a workspace by ID."""
        ws_path = get_workspace_path(workspace_id)
        ws_file = ws_path / "workspace.json"
        if not ws_file.exists():
            return None
        store = JsonFileStore(ws_file, Workspace)
        return store.get(workspace_id)

    def create(self, name: str, description: str = "") -> Workspace:
        """Create a new workspace."""
        workspace = Workspace.new(name=name, description=description)
        ws_path = ensure_workspace_files(workspace.workspace_id)
        store = JsonFileStore(ws_path / "workspace.json", Workspace)
        store.upsert(workspace)
        self._bus.emit_sync(Event(
            EventType.WORKSPACE_CREATED,
            workspace_id=workspace.workspace_id,
            payload=workspace.to_dict(),
        ))
        # Auto-switch to new workspace
        set_current_workspace_id(workspace.workspace_id)
        # Register the creator agent as the first agent in the workspace
        self._register_default_agent(workspace.workspace_id, name)
        return workspace

    def update(self, workspace_id: str, **fields) -> Workspace:
        """Update workspace fields."""
        ws_path = get_workspace_path(workspace_id)
        ws_file = ws_path / "workspace.json"
        if not ws_file.exists():
            raise KeyError(f"Workspace {workspace_id} not found")
        store = JsonFileStore(ws_file, Workspace)
        workspace = store.get(workspace_id)
        if not workspace:
            raise KeyError(f"Workspace {workspace_id} not found")
        for key, value in fields.items():
            if hasattr(workspace, key) and key not in ("workspace_id",):
                setattr(workspace, key, value)
        from datetime import datetime, timezone
        workspace.updated_at = datetime.now(timezone.utc).isoformat()
        store.upsert(workspace)
        self._bus.emit_sync(Event(
            EventType.WORKSPACE_CREATED,  # reuse event type for update
            workspace_id=workspace.workspace_id,
            payload=workspace.to_dict(),
        ))
        return workspace

    def delete(self, workspace_id: str) -> bool:
        """Delete a workspace and all its data."""
        ws_path = get_workspace_path(workspace_id)
        if not ws_path.exists():
            return False
        shutil.rmtree(ws_path)
        # If this was the current workspace, clear the current marker
        if get_current_workspace_id() == workspace_id:
            if CURRENT_WS_FILE.exists():
                CURRENT_WS_FILE.unlink()
        self._bus.emit_sync(Event(
            EventType.WORKSPACE_DELETED,
            workspace_id=workspace_id,
            payload={"workspace_id": workspace_id},
        ))
        return True

    # ─── CLI compatibility aliases ───────────────────────────────────────────

    def list_workspaces(self, owner_id: str = None, is_active: bool = True) -> list[Workspace]:
        """List workspaces (CLI compatibility)."""
        # Note: Workspace model doesn't have owner_id/is_active fields,
        # so we just return all workspaces
        return self.list()

    def create_workspace(self, name: str, owner_id: str, description: str = "") -> Workspace:
        """Create workspace (CLI compatibility)."""
        return self.create(name=name, description=description)

    def get_workspace(self, workspace_id: str) -> Workspace | None:
        """Get workspace (CLI compatibility)."""
        return self.get(workspace_id)

    def delete_workspace(self, workspace_id: str, force: bool = False) -> bool:
        """Delete workspace (CLI compatibility)."""
        return self.delete(workspace_id)

    def switch_to(self, workspace_id: str) -> Workspace:
        """Switch the current workspace."""
        workspace = self.get(workspace_id)
        if not workspace:
            raise KeyError(f"Workspace {workspace_id} not found")
        set_current_workspace_id(workspace_id)
        return workspace

    def get_current(self) -> Workspace | None:
        """Get the currently active workspace."""
        ws_id = get_current_workspace_id()
        if not ws_id:
            return None
        return self.get(ws_id)

    def get_current_or_default(self) -> Workspace:
        """Get current workspace or create a default one."""
        ws = self.get_current()
        if ws:
            return ws
        # Create a default workspace if none exists
        return self.create("default", description="Default workspace")

    # ─── Agent helpers ─────────────────────────────────────────────────────────

    def _register_default_agent(self, workspace_id: str, workspace_name: str):
        """Register a default agent for a new workspace."""
        ws_path = get_workspace_path(workspace_id)
        agent_store = JsonFileStore(ws_path / "agents.json", Agent)
        default_agent = Agent.new(
            name=f"{workspace_name}-agent",
            role=AgentRole.DEVELOPER,
            capabilities=[],
        )
        agent_store.upsert(default_agent)
