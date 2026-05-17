"""Dual-backend storage (JSON + SQLite) for the collaboration module.

JSON backend: thread-safe with fcntl file locking.
SQLite backend: WAL mode, MVCC concurrency, crash recovery.
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import sqlite3
import threading
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

_log = logging.getLogger(__name__)

T = TypeVar("T")

# ─── Storage backend abstract ────────────────────────────────────────────────


class StorageBackend(ABC):
    """Abstract storage backend interface."""

    @abstractmethod
    def list(self) -> list[T]:
        ...

    @abstractmethod
    def get(self, key: str) -> T | None:
        ...

    @abstractmethod
    def upsert(self, entity: T) -> T:
        ...

    @abstractmethod
    def delete(self, key: str) -> bool:
        ...

    def _key_field(self) -> str:
        """Return the primary key field name for the model type."""
        mapping = {
            "Task": "task_id",
            "Agent": "agent_id",
            "Skill": "skill_id",
            "Workspace": "workspace_id",
            "TaskOrchestration": "orchestration_id",
            "SubTask": "sub_task_id",
            "CriticReview": "review_id",
        }
        name = self._model_type.__name__
        field = mapping.get(name)
        if field:
            return field
        raise ValueError(f"Unknown model type: {name!r}")


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


class JsonFileStore(StorageBackend):
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
        # Accept both model instances and plain dicts — always store as dict
        if isinstance(entity, dict):
            key = entity.get(key_field)
            data = self._read_raw()
            for i, d in enumerate(data):
                if d.get(key_field) == key:
                    data[i] = entity
                    self._write_raw(data)
                    return entity
            data.append(entity)
            self._write_raw(data)
            return entity
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


# ─── SQLite Store ─────────────────────────────────────────────────────────────


def _open_sqlite(path: Path) -> sqlite3.Connection:
    """Open SQLite connection with WAL mode and safe pragmas."""
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# Map model type names to their table + column schemas
_TABLE_SCHEMAS = {
    "Agent": """
        CREATE TABLE IF NOT EXISTS agents (
            agent_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            role TEXT,
            status TEXT,
            system_prompt TEXT,
            capabilities TEXT,
            metadata TEXT,
            created_at REAL,
            updated_at REAL
        )""",
    "Task": """
        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT,
            priority INTEGER,
            complexity TEXT,
            phase TEXT,
            phase_history TEXT,
            assignee TEXT,
            depends_on TEXT,
            blockers TEXT,
            result TEXT,
            error TEXT,
            metadata TEXT,
            created_at REAL,
            updated_at REAL,
            completed_at REAL
        )""",
    "Skill": """
        CREATE TABLE IF NOT EXISTS skills (
            skill_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            commands TEXT,
            metadata TEXT,
            created_at REAL,
            updated_at REAL
        )""",
    "Workspace": """
        CREATE TABLE IF NOT EXISTS workspaces (
            workspace_id TEXT PRIMARY KEY,
            name TEXT,
            config TEXT,
            created_at REAL,
            updated_at REAL
        )""",
    "TaskOrchestration": """
        CREATE TABLE IF NOT EXISTS orchestrations (
            orchestration_id TEXT PRIMARY KEY,
            data TEXT,
            created_at REAL,
            updated_at REAL
        )""",
    "SubTask": """
        CREATE TABLE IF NOT EXISTS subtasks (
            sub_task_id TEXT PRIMARY KEY,
            parent_id TEXT,
            data TEXT,
            created_at REAL,
            updated_at REAL
        )""",
    "CriticReview": """
        CREATE TABLE IF NOT EXISTS reviews (
            review_id TEXT PRIMARY KEY,
            task_id TEXT,
            data TEXT,
            created_at REAL
        )""",
    "dict": """
        CREATE TABLE IF NOT EXISTS events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT,
            payload TEXT,
            created_at REAL
        )""",
}


class SQLiteStore(StorageBackend):
    """SQLite-backed storage with WAL mode.

    Provides CRUD operations on a single table per store instance.
    Thread-safe via connection per thread + WAL mode.
    """

    def __init__(self, db_path: Path, model_type: type[T], table_name: str | None = None):
        self._db_path = db_path
        self._model_type = model_type
        self._table_name = table_name or self._model_type.__name__.lower() + "s"
        self._local = threading.local()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        """Get thread-local SQLite connection."""
        if not hasattr(self._local, "conn"):
            self._local.conn = _open_sqlite(self._db_path)
        return self._local.conn

    def _init_db(self):
        """Create table if not exists."""
        schema_sql = _TABLE_SCHEMAS.get(self._model_type.__name__)
        if schema_sql:
            self._conn().execute(schema_sql)
            self._conn().commit()
        # Index on primary key (always exists), plus status/phase for tasks
        if self._table_name == "tasks":
            self._conn().execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
            self._conn().execute("CREATE INDEX IF NOT EXISTS idx_tasks_phase ON tasks(phase)")
            self._conn().commit()

    def _serialize(self, entity: T) -> dict[str, Any]:
        """Serialize entity to dict, handling nested JSON fields."""
        if isinstance(entity, dict):
            d = dict(entity)
        else:
            d = entity.to_dict()
        # JSON-serialize lists/dicts that SQLite can't store natively
        json_cols = {"capabilities", "metadata", "phase_history", "depends_on", "blockers", "config", "data", "commands"}
        for col in json_cols:
            if col in d and d[col] is not None and not isinstance(d[col], str):
                d[col] = json.dumps(d[col])
        return d

    def _deserialize(self, row: tuple, cols: list[str]) -> T:
        """Deserialize a DB row to model instance."""
        d = dict(zip(cols, row))
        # Parse JSON columns
        json_cols = {"capabilities", "metadata", "phase_history", "depends_on", "blockers", "config", "data", "commands"}
        for col in json_cols:
            if col in d and d[col] is not None:
                try:
                    d[col] = json.loads(d[col])
                except (json.JSONDecodeError, TypeError):
                    pass
        return self._model_type.from_dict(d)

    # ─── CRUD ─────────────────────────────────────────────────────────────────

    def list(self) -> list[T]:
        """Return all entities."""
        cols = self._cols()
        rows = self._conn().execute(f"SELECT * FROM {self._table_name}").fetchall()
        return [self._deserialize(row, cols) for row in rows]

    def get(self, key: str) -> T | None:
        """Fetch by primary key."""
        key_field = self._key_field()
        cols = self._cols()
        row = self._conn().execute(
            f"SELECT * FROM {self._table_name} WHERE {key_field} = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        return self._deserialize(row, cols)

    def upsert(self, entity: T) -> T:
        """Insert or replace an entity."""
        d = self._serialize(entity)
        key_field = self._key_field()
        # Filter to only columns that exist in the table
        table_cols = set(self._cols())
        d = {k: v for k, v in d.items() if k in table_cols}
        cols = list(d.keys())
        placeholders = ", ".join(["?"] * len(cols))
        sql = f"INSERT OR REPLACE INTO {self._table_name} ({', '.join(cols)}) VALUES ({placeholders})"
        self._conn().execute(sql, tuple(d.values()))
        self._conn().commit()
        return entity

    def delete(self, key: str) -> bool:
        """Delete by primary key."""
        key_field = self._key_field()
        cur = self._conn().execute(
            f"DELETE FROM {self._table_name} WHERE {key_field} = ?", (key,)
        )
        self._conn().commit()
        return cur.rowcount > 0

    def _cols(self) -> list[str]:
        """Return column names for the table."""
        rows = self._conn().execute(f"PRAGMA table_info({self._table_name})").fetchall()
        return [r[1] for r in rows]

    # ─── Events (append-only) ────────────────────────────────────────────────

    def append_event(self, event_type: str, payload: dict) -> int:
        """Append an event and return its rowid. For events table only."""
        now = datetime.now().timestamp()
        cur = self._conn().execute(
            "INSERT INTO events (event_type, payload, created_at) VALUES (?, ?, ?)",
            (event_type, json.dumps(payload), now)
        )
        self._conn().commit()
        return cur.lastrowid

    def list_events(self, limit: int = 100, offset: int = 0) -> list[dict]:
        """Return recent events as dicts."""
        rows = self._conn().execute(
            "SELECT event_type, payload, created_at FROM events ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset)
        ).fetchall()
        return [{"event_type": r[0], "payload": json.loads(r[1]), "created_at": r[2]} for r in rows]


# ─── Dual-backend factory ──────────────────────────────────────────────────────


def get_storage_backend(workspace_path: Path, model_type: type[T], json_filename: str) -> StorageBackend:
    """Factory: return SQLiteStore or JsonFileStore based on workspace config.

    Reads `storage_backend` from workspace config.json.
    Defaults to JsonFileStore for backward compatibility.
    """
    config_path = workspace_path / "config.json"
    backend = "json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
            backend = config.get("storage_backend", "json")
        except Exception:
            pass

    if backend == "sqlite":
        db_path = workspace_path / ".hermes_collab.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        table_map = {
            "tasks": "tasks",
            "agents": "agents",
            "skills": "skills",
            "workspace.json": "workspaces",
            "orchestrations.json": "orchestrations",
            "subtasks.json": "subtasks",
            "reviews.json": "reviews",
            "events.json": "events",
            "templates.json": "templates",
        }
        table_name = table_map.get(json_filename)
        return SQLiteStore(db_path, model_type, table_name)
    else:
        return JsonFileStore(workspace_path / json_filename, model_type)


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
    for filename in ["tasks.json", "agents.json", "skills.json", "workspace.json", "config.json",
                    "orchestrations.json", "subtasks.json", "reviews.json", "events.json",
                    "templates.json"]:
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


def for_orchestrations(ws_path: Path) -> JsonFileStore:
    """JsonFileStore for orchestrations.json."""
    from collaboration.models import TaskOrchestration
    return JsonFileStore(ws_path / "orchestrations.json", TaskOrchestration)


def for_subtasks(ws_path: Path) -> JsonFileStore:
    """JsonFileStore for subtasks.json."""
    from collaboration.models import SubTask
    return JsonFileStore(ws_path / "subtasks.json", SubTask)


def for_reviews(ws_path: Path) -> JsonFileStore:
    """JsonFileStore for reviews.json."""
    from collaboration.models import CriticReview
    return JsonFileStore(ws_path / "reviews.json", CriticReview)


def for_events(ws_path: Path) -> JsonFileStore:
    """JsonFileStore for events.json (stores all emitted events for replay)."""
    return JsonFileStore(ws_path / "events.json", dict)  # events stored as plain dicts


def for_templates(ws_path: Path) -> JsonFileStore:
    """JsonFileStore for templates.json."""
    return JsonFileStore(ws_path / "templates.json", dict)