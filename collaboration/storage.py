"""JSON file-based storage with file locking for the collaboration module."""

import fcntl
import json
import logging
import os
from pathlib import Path
from typing import Any, TypeVar

_log = logging.getLogger(__name__)

T = TypeVar("T")

# ─── Storage lock ─────────────────────────────────────────────────────────────


class StorageLock:
    """File lock wrapper using fcntl (Unix-only). Context manager style."""

    def __init__(self, path: Path):
        self.path = path
        self._fd = None

    def __enter__(self):
        self._fd = open(self.path, "a")
        fcntl.flock(self._fd.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *_: Any):
        if self._fd:
            fcntl.flock(self._fd.fileno(), fcntl.LOCK_UN)
            self._fd.close()
            self._fd = None


# ─── JSON File Store ──────────────────────────────────────────────────────────


class JsonFileStore:
    """Thread-safe JSON file store with file locking and model-type awareness.

    Handles lists of model objects stored in a single JSON file. Provides
    CRUD operations via upsert/get/list/delete, all guarded by exclusive
    file locks to prevent corruption on concurrent access.
    """

    def __init__(self, file_path: Path | str, model_type: type[T]):
        self._path = Path(file_path)
        self._model_type = model_type
        self._ensure_dir()

    def _ensure_dir(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._write_raw([])

    def _read_raw(self) -> list[dict[str, Any]]:
        with StorageLock(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                _log.warning("Corrupt JSON in %s — resetting to []", self._path)
                return []

    def _write_raw(self, data: list[dict[str, Any]]):
        with StorageLock(self._path):
            tmp = self._path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            tmp.replace(self._path)

    # ─── CRUD ─────────────────────────────────────────────────────────────────

    def list(self) -> list[T]:
        """Return all entities deserialised from the file."""
        return [self._model_type.from_dict(d) for d in self._read_raw()]

    def get(self, key: str) -> T | None:
        """Fetch a single entity by its primary key field (e.g. task_id)."""
        key_field = self._key_field()
        for d in self._read_raw():
            if d.get(key_field) == key:
                return self._model_type.from_dict(d)
        return None

    def upsert(self, entity: T) -> T:
        """Insert or replace an entity. Returns the same entity."""
        key_field = self._key_field()
        key = getattr(entity, key_field)
        data = self._read_raw()
        for i, d in enumerate(data):
            if d.get(key_field) == key:
                data[i] = entity.to_dict()
                self._write_raw(data)
                return entity
        data.append(entity.to_dict())
        self._write_raw(data)
        return entity

    def delete(self, key: str) -> bool:
        """Delete by primary key. Returns True if found and removed."""
        key_field = self._key_field()
        data = self._read_raw()
        new_data = [d for d in data if d.get(key_field) != key]
        if len(new_data) == len(data):
            return False
        self._write_raw(new_data)
        return True

    def _key_field(self) -> str:
        """Return the primary key field name for the model type."""
        mapping = {
            "Task": "task_id",
            "Agent": "agent_id",
            "Skill": "skill_id",
            "Workspace": "workspace_id",
        }
        name = self._model_type.__name__
        field = mapping.get(name)
        if field:
            return field
        raise ValueError(f"Unknown model type: {name!r}")

    # ─── Factory constructors ────────────────────────────────────────────────

    @classmethod
    def for_tasks(cls, workspace_path: Path) -> "JsonFileStore":
        from collaboration.models import Task
        return cls(workspace_path / "tasks.json", Task)

    @classmethod
    def for_agents(cls, workspace_path: Path) -> "JsonFileStore":
        from collaboration.models import Agent
        return cls(workspace_path / "agents.json", Agent)

    @classmethod
    def for_skills(cls, workspace_path: Path) -> "JsonFileStore":
        from collaboration.models import Skill
        return cls(workspace_path / "skills.json", Skill)

    @classmethod
    def for_workspace_meta(cls, workspace_path: Path) -> "JsonFileStore":
        from collaboration.models import Workspace
        return cls(workspace_path / "workspace.json", Workspace)


# ─── Workspaces root helpers ─────────────────────────────────────────────────


HERMES_HOME = Path(os.getenv("HERMES_HOME", Path.home() / ".hermes"))
WORKSPACES_DIR = HERMES_HOME / "workspaces"
CURRENT_WS_FILE = WORKSPACES_DIR / ".current"


def get_workspace_path(workspace_id: str) -> Path:
    """Return the filesystem directory for a workspace."""
    return WORKSPACES_DIR / workspace_id


def ensure_workspace_files(workspace_id: str) -> Path:
    """Create workspace directory and all JSON data files if they don't exist.

    Returns the workspace Path. Safe to call repeatedly.
    """
    ws_path = get_workspace_path(workspace_id)
    ws_path.mkdir(parents=True, exist_ok=True)
    for filename in ["tasks.json", "agents.json", "skills.json", "workspace.json", "config.json"]:
        fp = ws_path / filename
        if not fp.exists():
            fp.write_text("[]" if filename != "config.json" else "{}")
    return ws_path


def get_current_workspace_id() -> str | None:
    """Read the active workspace ID from ~/.hermes/workspaces/.current."""
    if not CURRENT_WS_FILE.exists():
        return None
    try:
        return CURRENT_WS_FILE.read_text(encoding="utf-8").strip() or None
    except Exception:
        return None


def set_current_workspace_id(workspace_id: str | None) -> None:
    """Set or clear the active workspace ID."""
    WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)
    if workspace_id is None:
        if CURRENT_WS_FILE.exists():
            CURRENT_WS_FILE.unlink()
    else:
        CURRENT_WS_FILE.write_text(workspace_id, encoding="utf-8")
