"""PostgreSQL storage backend for hermes-agent-collab.

Supports:
- Async CRUD via asyncpg (FastAPI routes)
- Sync CRUD via psycopg2 (background tasks)
- LISTEN/NOTIFY for real-time event streaming
- JSONB columns with GIN indexes for complex fields
- Connection pooling and thread-local sync connections
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

try:
    import asyncpg
except ImportError:
    asyncpg = None

try:
    import psycopg2
    import psycopg2.pool
except ImportError:
    psycopg2 = None

from collaboration.storage import StorageBackend

_log = logging.getLogger(__name__)
T = TypeVar("T")

# ─── Table & DDL definitions ──────────────────────────────────────────────────

_TABLE_DDL = {
    "agents": """
        CREATE TABLE IF NOT EXISTS agents (
            agent_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            role TEXT,
            status TEXT,
            system_prompt TEXT,
            capabilities JSONB DEFAULT '[]',
            metadata JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )""",
    "tasks": """
        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT,
            priority INTEGER,
            complexity TEXT,
            phase TEXT,
            phase_history JSONB DEFAULT '[]',
            assignee TEXT,
            depends_on JSONB DEFAULT '[]',
            blockers JSONB DEFAULT '[]',
            result TEXT,
            error TEXT,
            metadata JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            completed_at TIMESTAMPTZ
        );
        CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
        CREATE INDEX IF NOT EXISTS idx_tasks_phase ON tasks(phase);
        CREATE INDEX IF NOT EXISTS idx_tasks_metadata ON tasks USING GIN(metadata)""",
    "skills": """
        CREATE TABLE IF NOT EXISTS skills (
            skill_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            commands JSONB DEFAULT '[]',
            metadata JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )""",
    "workspaces": """
        CREATE TABLE IF NOT EXISTS workspaces (
            workspace_id TEXT PRIMARY KEY,
            name TEXT,
            config JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )""",
    "orchestrations": """
        CREATE TABLE IF NOT EXISTS orchestrations (
            orchestration_id TEXT PRIMARY KEY,
            data JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )""",
    "subtasks": """
        CREATE TABLE IF NOT EXISTS subtasks (
            sub_task_id TEXT PRIMARY KEY,
            parent_id TEXT,
            data JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )""",
    "reviews": """
        CREATE TABLE IF NOT EXISTS reviews (
            review_id TEXT PRIMARY KEY,
            task_id TEXT,
            data JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT NOW()
        )""",
    "messages": """
        CREATE TABLE IF NOT EXISTS messages (
            msg_id TEXT PRIMARY KEY,
            from_agent_id TEXT,
            to_agent_id TEXT,
            msg_type TEXT,
            payload JSONB DEFAULT '{}',
            acknowledged BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )""",
    "sessions": """
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            participant_ids JSONB DEFAULT '[]',
            context JSONB DEFAULT '{}',
            status TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )""",
    "distributions": """
        CREATE TABLE IF NOT EXISTS distributions (
            distribution_id TEXT PRIMARY KEY,
            task_id TEXT,
            policy TEXT,
            required_capabilities JSONB DEFAULT '[]',
            assigned_agent_id TEXT,
            status TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )""",
    "events": """
        CREATE TABLE IF NOT EXISTS events (
            event_id SERIAL PRIMARY KEY,
            event_type TEXT NOT NULL,
            payload JSONB NOT NULL,
            workspace_id TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
        CREATE INDEX IF NOT EXISTS idx_events_workspace ON events(workspace_id);
        CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at DESC)""",
}

# Map json_filename → table name (matches get_storage_backend's convention)
_TABLE_MAP = {
    "tasks.json": "tasks",
    "agents.json": "agents",
    "skills.json": "skills",
    "workspace.json": "workspaces",
    "orchestrations.json": "orchestrations",
    "subtasks.json": "subtasks",
    "reviews.json": "reviews",
    "messages.json": "messages",
    "sessions.json": "sessions",
    "distributions.json": "distributions",
    "events.json": "events",
}


def _build_dsn(config: dict) -> str:
    """Build PostgreSQL DSN from config dict."""
    host = config.get("host", "localhost")
    port = config.get("port", 5432)
    database = config.get("database", "hermes_collab")
    user = config.get("user", "hermes")
    password = config.get("password", "")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


# ─── PostgreSQL Store ─────────────────────────────────────────────────────────


class PostgreSQLStore(StorageBackend):
    """PostgreSQL-backed storage with async/sync dual interface.

    Async via asyncpg for FastAPI routes.
    Sync via psycopg2 for background tasks.
    Connection pool shared by DSN across all instances.
    """

    # Shared async pools: dsn → pool
    _async_pools: dict[str, asyncpg.Pool] = {}
    # Shared sync pools: dsn → pool
    _sync_pools: dict[str, psycopg2.pool.ThreadedConnectionPool] = {}

    def __init__(
        self,
        dsn: str,
        model_type: type[T],
        table_name: str,
        *,
        pool_size: int = 10,
    ):
        self._dsn = dsn
        self._model_type = model_type
        self._table_name = table_name
        self._pool_size = pool_size
        self._local = threading.local()

        # Ensure pool exists
        self._ensure_async_pool(dsn, pool_size)
        self._ensure_sync_pool(dsn, pool_size)
        # Init schema
        asyncio.get_event_loop().run_until_complete(self._init_schema())

    # ─── Pool management ─────────────────────────────────────────────────────

    @classmethod
    def _ensure_async_pool(cls, dsn: str, pool_size: int):
        if dsn not in cls._async_pools:
            _log.info("Creating asyncpg pool for DSN %s (size=%d)", dsn[:20], pool_size)
            cls._async_pools[dsn] = None  # placeholder until created

    @classmethod
    async def _create_async_pool(cls, dsn: str, pool_size: int) -> asyncpg.Pool:
        _log.info("Connecting asyncpg pool for DSN %s", dsn[:20])
        pool = await asyncpg.create_pool(
            dsn,
            min_size=1,
            max_size=pool_size,
            command_timeout=60,
        )
        cls._async_pools[dsn] = pool
        return pool

    @classmethod
    def _ensure_sync_pool(cls, dsn: str, pool_size: int):
        if dsn not in cls._sync_pools or cls._sync_pools[dsn] is None:
            _log.info("Creating psycopg2 pool for DSN %s (size=%d)", dsn[:20], pool_size)
            try:
                cls._sync_pools[dsn] = psycopg2.pool.ThreadedConnectionPool(
                    1, pool_size, dsn
                )
            except psycopg2.OperationalError as e:
                _log.warning("psycopg2 pool creation failed (DSN %s): %s", dsn[:20], e)
                cls._sync_pools[dsn] = None

    async def _async_pool(self) -> asyncpg.Pool:
        pool = PostgreSQLStore._async_pools.get(self._dsn)
        if pool is None:
            pool = await self._create_async_pool(self._dsn, self._pool_size)
        return pool

    def _sync_conn(self):
        """Get thread-local sync connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            pool = PostgreSQLStore._sync_pools.get(self._dsn)
            if pool is None:
                raise RuntimeError(
                    f"Sync pool not available for DSN {self._dsn[:20]}. "
                    "Is psycopg2 installed and did a connection succeed?"
                )
            self._local.conn = pool.getconn()
            self._local.conn.autocommit = False
        return self._local.conn

    def _return_sync_conn(self, conn):
        """Return connection to pool."""
        pool = PostgreSQLStore._sync_pools.get(self._dsn)
        if pool and conn:
            pool.putconn(conn)
        self._local.conn = None

    # ─── Schema init ─────────────────────────────────────────────────────────

    async def _init_schema(self):
        """Run CREATE TABLE IF NOT EXISTS for this table."""
        ddl = _TABLE_DDL.get(self._table_name)
        if not ddl:
            _log.warning("No DDL defined for table %s", self._table_name)
            return
        pool = await self._async_pool()
        async with pool.acquire() as conn:
            # Split by semicolons and execute each statement
            for stmt in ddl.split(";"):
                stmt = stmt.strip()
                if stmt:
                    await conn.execute(stmt)

    # ─── Serialisation helpers ───────────────────────────────────────────────

    def _serialize(self, entity: T) -> dict[str, Any]:
        """Serialize entity to dict, converting non-string fields to JSON."""
        if isinstance(entity, dict):
            d = dict(entity)
        else:
            d = entity.to_dict()

        json_cols = {
            "capabilities", "metadata", "phase_history", "depends_on",
            "blockers", "config", "data", "commands", "payload",
            "participant_ids", "context", "required_capabilities",
        }
        for col in json_cols:
            if col in d and d[col] is not None and not isinstance(d[col], str):
                d[col] = json.dumps(d[col])
        # timestamps
        for ts_col in ("created_at", "updated_at", "completed_at"):
            if ts_col in d and isinstance(d[ts_col], datetime):
                d[ts_col] = d[ts_col]
        return d

    def _deserialize(self, row: asyncpg.Record) -> T:
        """Deserialize a DB row to model instance."""
        d = dict(row)
        # Parse JSONB columns
        json_cols = {
            "capabilities", "metadata", "phase_history", "depends_on",
            "blockers", "config", "data", "commands", "payload",
            "participant_ids", "context", "required_capabilities",
        }
        for col in json_cols:
            if col in d and d[col] is not None:
                if isinstance(d[col], str):
                    try:
                        d[col] = json.loads(d[col])
                    except (json.JSONDecodeError, TypeError):
                        pass
        return self._model_type.from_dict(d)

    def _deserialize_dict(self, row: tuple, cols: list[str]) -> dict[str, Any]:
        """Deserialize a sync (psycopg2) row to dict."""
        d = dict(zip(cols, row))
        json_cols = {
            "capabilities", "metadata", "phase_history", "depends_on",
            "blockers", "config", "data", "commands", "payload",
            "participant_ids", "context", "required_capabilities",
        }
        for col in json_cols:
            if col in d and d[col] is not None and isinstance(d[col], str):
                try:
                    d[col] = json.loads(d[col])
                except (json.JSONDecodeError, TypeError):
                    pass
        return d

    # ─── Async CRUD (for FastAPI) ─────────────────────────────────────────────

    async def list_async(self) -> list[T]:
        """Return all entities (async)."""
        pool = await self._async_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(f'SELECT * FROM "{self._table_name}"')
        return [self._deserialize(row) for row in rows]

    async def get_async(self, key: str) -> T | None:
        """Fetch by primary key (async)."""
        key_field = self._key_field()
        pool = await self._async_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f'SELECT * FROM "{self._table_name}" WHERE "{key_field}" = $1', key
            )
        if row is None:
            return None
        return self._deserialize(row)

    async def upsert_async(self, entity: T) -> T:
        """Insert or replace (async)."""
        d = self._serialize(entity)
        key_field = self._key_field()
        table_cols = await self._get_columns()
        d = {k: v for k, v in d.items() if k in table_cols}
        cols = list(d.keys())
        placeholders = ", ".join([f"${i + 1}" for i in range(len(cols))])
        sql = (
            f'INSERT INTO "{self._table_name}" ({", ".join(cols)}) '
            f"VALUES ({placeholders}) "
            f"ON CONFLICT ({key_field}) DO UPDATE SET "
            + ", ".join([f'"{c}" = EXCLUDED."{c}"' for c in cols])
        )
        pool = await self._async_pool()
        async with pool.acquire() as conn:
            await conn.execute(sql, tuple(d.values()))
        return entity

    async def delete_async(self, key: str) -> bool:
        """Delete by primary key (async)."""
        key_field = self._key_field()
        pool = await self._async_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                f'DELETE FROM "{self._table_name}" WHERE "{key_field}" = $1', key
            )
        return "DELETE" in result

    async def _get_columns(self) -> set[str]:
        """Return column names for the table (async)."""
        pool = await self._async_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = $1", self._table_name
            )
        return {r["column_name"] for r in rows}

    # ─── Sync CRUD (for background tasks) ────────────────────────────────────

    def list(self) -> list[T]:
        """Return all entities (sync)."""
        conn = self._sync_conn()
        try:
            cur = conn.cursor()
            cur.execute(f'SELECT * FROM "{self._table_name}"')
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            return [self._model_type.from_dict(self._deserialize_dict(row, cols)) for row in rows]
        finally:
            self._return_sync_conn(conn)

    def get(self, key: str) -> T | None:
        """Fetch by primary key (sync)."""
        key_field = self._key_field()
        conn = self._sync_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                f'SELECT * FROM "{self._table_name}" WHERE "{key_field}" = %s', (key,)
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d[0] for d in cur.description]
            return self._model_type.from_dict(self._deserialize_dict(row, cols))
        finally:
            self._return_sync_conn(conn)

    def upsert(self, entity: T) -> T:
        """Insert or replace (sync)."""
        d = self._serialize(entity)
        key_field = self._key_field()
        # Filter to existing columns
        conn = self._sync_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = %s", (self._table_name,)
            )
            table_cols = {r[0] for r in cur.fetchall()}
        finally:
            self._return_sync_conn(conn)

        d = {k: v for k, v in d.items() if k in table_cols}
        cols = list(d.keys())
        placeholders = ", ".join(["%s"] * len(cols))
        sql = (
            f'INSERT INTO "{self._table_name}" ({", ".join(cols)}) '
            f"VALUES ({placeholders}) "
            f"ON CONFLICT ({key_field}) DO UPDATE SET "
            + ", ".join([f'"{c}" = EXCLUDED."{c}"' for c in cols])
        )
        conn = self._sync_conn()
        try:
            cur = conn.cursor()
            cur.execute(sql, tuple(d.values()))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._return_sync_conn(conn)
        return entity

    def delete(self, key: str) -> bool:
        """Delete by primary key (sync)."""
        key_field = self._key_field()
        conn = self._sync_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                f'DELETE FROM "{self._table_name}" WHERE "{key_field}" = %s', (key,)
            )
            conn.commit()
            return cur.rowcount > 0
        except Exception:
            conn.rollback()
            raise
        finally:
            self._return_sync_conn(conn)

    # ─── Events (append-only) ────────────────────────────────────────────────

    async def append_event_async(
        self, event_type: str, payload: dict, workspace_id: str | None = None
    ) -> int:
        """Append an event and return its event_id (async)."""
        pool = await self._async_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO events (event_type, payload, workspace_id) "
                "VALUES ($1, $2, $3) RETURNING event_id",
                event_type, json.dumps(payload), workspace_id
            )
        return row["event_id"]

    async def list_events_async(
        self, limit: int = 100, offset: int = 0, workspace_id: str | None = None
    ) -> list[dict]:
        """Return recent events as dicts (async)."""
        pool = await self._async_pool()
        async with pool.acquire() as conn:
            if workspace_id:
                rows = await conn.fetch(
                    "SELECT event_type, payload, created_at FROM events "
                    "WHERE workspace_id = $1 "
                    "ORDER BY created_at DESC LIMIT $2 OFFSET $3",
                    workspace_id, limit, offset
                )
            else:
                rows = await conn.fetch(
                    "SELECT event_type, payload, created_at FROM events "
                    "ORDER BY created_at DESC LIMIT $1 OFFSET $2",
                    limit, offset
                )
        return [
            {"event_type": r["event_type"], "payload": r["payload"], "created_at": r["created_at"]}
            for r in rows
        ]

    # ─── LISTEN / NOTIFY (real-time streaming) ───────────────────────────────

    async def listen_async(
        self,
        channel: str,
        callback: "callable[[str, str], None]" | None = None,
    ):
        """Return an async iterator over NOTIFY messages on the channel.

        If callback is provided it is called for each notification.
        The iterator yields (channel, payload) tuples.
        """
        pool = await self._async_pool()
        conn = await pool.acquire()
        try:
            await conn.add_listener(channel, callback or _default_notify_callback)
            yield conn
        finally:
            await pool.release(conn)

    async def notify_async(self, channel: str, payload: dict | str):
        """Send a NOTIFY on the channel (async)."""
        pool = await self._async_pool()
        payload_str = json.dumps(payload) if isinstance(payload, dict) else payload
        async with pool.acquire() as conn:
            await conn.execute(f"NOTIFY {channel}, %s", (payload_str,))


_default_notify_callbacks: dict[str, list] = {}


def _default_notify_callback(connection, pid, channel, payload):
    _default_notify_callbacks.setdefault(channel, []).append((channel, payload))


# ─── Factory helpers (to match storage.py pattern) ───────────────────────────


def for_tasks_pg(dsn: str) -> PostgreSQLStore:
    from collaboration.models import Task
    return PostgreSQLStore(dsn, Task, "tasks")


def for_agents_pg(dsn: str) -> PostgreSQLStore:
    from collaboration.models import Agent
    return PostgreSQLStore(dsn, Agent, "agents")


def for_skills_pg(dsn: str) -> PostgreSQLStore:
    from collaboration.models import Skill
    return PostgreSQLStore(dsn, Skill, "skills")


def for_workspace_meta_pg(dsn: str) -> PostgreSQLStore:
    from collaboration.models import Workspace
    return PostgreSQLStore(dsn, Workspace, "workspaces")


def for_orchestrations_pg(dsn: str) -> PostgreSQLStore:
    from collaboration.models import TaskOrchestration
    return PostgreSQLStore(dsn, TaskOrchestration, "orchestrations")


def for_subtasks_pg(dsn: str) -> PostgreSQLStore:
    from collaboration.models import SubTask
    return PostgreSQLStore(dsn, SubTask, "subtasks")


def for_reviews_pg(dsn: str) -> PostgreSQLStore:
    from collaboration.models import CriticReview
    return PostgreSQLStore(dsn, CriticReview, "reviews")


def for_messages_pg(dsn: str) -> PostgreSQLStore:
    from collaboration.models import AgentMessage
    return PostgreSQLStore(dsn, AgentMessage, "messages")


def for_sessions_pg(dsn: str) -> PostgreSQLStore:
    from collaboration.models import AgentSession
    return PostgreSQLStore(dsn, AgentSession, "sessions")


def for_distributions_pg(dsn: str) -> PostgreSQLStore:
    from collaboration.models import TaskDistribution
    return PostgreSQLStore(dsn, TaskDistribution, "distributions")


def for_events_pg(dsn: str) -> PostgreSQLStore:
    return PostgreSQLStore(dsn, dict, "events")
