"""API Key authentication for hermes-agent-collab.

Provides API key creation, validation, and workspace-scoped access control.
No external dependencies — uses stdlib hashlib for key hashing.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from .storage import JsonFileStore
except ImportError:
    from collaboration.storage import JsonFileStore


# ─── Constants ────────────────────────────────────────────────────────────────

HASH_ITERATIONS = 100_000
HASH_ALGORITHM = "sha256"
KEY_ID_LENGTH = 16
KEY_SECRET_LENGTH = 32


# ─── Scopes ──────────────────────────────────────────────────────────────────

class Scope:
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"

    ALL = {READ, WRITE, ADMIN}

    @staticmethod
    def coverage(required: set[str], provided: set[str]) -> bool:
        """Check if provided scopes satisfy required scopes.

        Admin covers everything, write covers read, read only covers read.
        """
        if "admin" in provided:
            return True
        if "admin" in required:
            return False
        if "write" in provided:
            return True
        if "write" in required:
            return False
        return "read" in provided


# ─── Data Models ─────────────────────────────────────────────────────────────

@dataclass
class ApiKey:
    key_id: str
    key_secret_hash: str  # PBKDF2-HMAC-SHA256
    salt: str
    name: str
    workspace_id: str
    scopes: list[str]
    created_at: str
    last_used_at: Optional[str] = None
    is_active: bool = True

    def to_dict(self) -> dict:
        return {
            "key_id": self.key_id,
            "key_secret_hash": self.key_secret_hash,
            "salt": self.salt,
            "name": self.name,
            "workspace_id": self.workspace_id,
            "scopes": self.scopes,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
            "is_active": self.is_active,
        }

    @staticmethod
    def from_dict(data: dict) -> ApiKey:
        return ApiKey(
            key_id=data["key_id"],
            key_secret_hash=data["key_secret_hash"],
            salt=data["salt"],
            name=data["name"],
            workspace_id=data["workspace_id"],
            scopes=data.get("scopes", [Scope.READ]),
            created_at=data.get("created_at", ""),
            last_used_at=data.get("last_used_at"),
            is_active=data.get("is_active", True),
        )


# ─── ApiKeyStore ─────────────────────────────────────────────────────────────

class ApiKeyStore:
    """Persistent storage for API keys."""

    def __init__(self, ws_path: Path):
        self._store = JsonFileStore(ws_path / "api_keys.json", ApiKey)

    def create(self, name: str, workspace_id: str, scopes: list[str]) -> tuple[ApiKey, str]:
        """Create a new API key.

        Returns (ApiKey, raw_secret) — raw_secret is only available at creation time.
        """
        key_id = f"ak_{secrets.token_urlsafe(KEY_ID_LENGTH)}"
        raw_secret = secrets.token_urlsafe(KEY_SECRET_LENGTH)
        salt = secrets.token_urlsafe(16)
        secret_hash = self._hash_secret(raw_secret, salt)

        now = _utc_now()
        key = ApiKey(
            key_id=key_id,
            key_secret_hash=secret_hash,
            salt=salt,
            name=name,
            workspace_id=workspace_id,
            scopes=scopes,
            created_at=now,
            is_active=True,
        )
        self._store.upsert(key.to_dict())
        return key, raw_secret

    def get(self, key_id: str) -> Optional[ApiKey]:
        """Get an API key by ID."""
        key_data = self._store.get(key_id)
        if not key_data:
            return None
        if isinstance(key_data, ApiKey):
            return key_data
        return ApiKey.from_dict(key_data)

    def verify(self, raw_secret: str, key_id: str) -> Optional[ApiKey]:
        """Verify a raw secret against a key_id. Returns ApiKey if valid."""
        key = self.get(key_id)
        if not key or not key.is_active:
            return None
        expected_hash = self._hash_secret(raw_secret, key.salt)
        if not hmac.compare_digest(expected_hash, key.key_secret_hash):
            return None
        # Update last_used_at
        key.last_used_at = _utc_now()
        self._store.upsert(key.to_dict())
        return key

    def list(self, workspace_id: Optional[str] = None) -> list[ApiKey]:
        """List all keys, optionally filtered by workspace."""
        raw_keys = self._store.list()
        result = []
        for data in raw_keys:
            if isinstance(data, ApiKey):
                k = data
            else:
                k = ApiKey.from_dict(data)
            if workspace_id and k.workspace_id != workspace_id:
                continue
            result.append(k)
        return result

    def revoke(self, key_id: str) -> bool:
        """Revoke (deactivate) an API key."""
        key = self.get(key_id)
        if not key:
            return False
        key.is_active = False
        self._store.upsert(key.to_dict())
        return True

    def delete(self, key_id: str) -> bool:
        """Permanently delete an API key."""
        return self._store.delete(key_id)

    @staticmethod
    def _hash_secret(raw_secret: str, salt: str) -> str:
        """Hash a raw secret with PBKDF2-HMAC-SHA256."""
        return hashlib.pbkdf2_hmac(
            HASH_ALGORITHM,
            raw_secret.encode("utf-8"),
            salt.encode("utf-8"),
            HASH_ITERATIONS,
        ).hex()


# ─── Auth Service ────────────────────────────────────────────────────────────

class AuthService:
    """High-level authentication service combining API keys + workspace context."""

    def __init__(self, ws_path: Path):
        self._store = ApiKeyStore(ws_path)

    def create_key(
        self, name: str, workspace_id: str, scopes: list[str]
    ) -> tuple[ApiKey, str]:
        """Create a new API key. Returns (ApiKey, raw_secret)."""
        return self._store.create(name, workspace_id, scopes)

    def list_keys(self, workspace_id: Optional[str] = None) -> list[ApiKey]:
        """List API keys for a workspace (secrets always masked)."""
        return self._store.list(workspace_id)

    def get_key(self, key_id: str) -> Optional[ApiKey]:
        """Get key metadata."""
        return self._store.get(key_id)

    def revoke_key(self, key_id: str) -> bool:
        """Revoke a key."""
        return self._store.revoke(key_id)

    def delete_key(self, key_id: str) -> bool:
        """Permanently delete a key."""
        return self._store.delete(key_id)

    def verify_request(
        self, raw_key: str, key_id: str, required_scopes: Optional[set[str]] = None
    ) -> tuple[bool, Optional[str], Optional[str]]:
        """Verify an incoming request's API key.

        Returns (success, error_message, workspace_id).
        If success=True, workspace_id is the authenticated workspace.
        """
        key = self._store.verify(raw_key, key_id)
        if not key:
            return False, "Invalid or inactive API key", None

        workspace_id = key.workspace_id

        if required_scopes:
            if not Scope.coverage(required_scopes, set(key.scopes)):
                return False, "Insufficient scope", workspace_id

        return True, None, workspace_id


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_key_id() -> str:
    return f"ak_{secrets.token_urlsafe(KEY_ID_LENGTH)}"


def mask_key(key_id: str) -> str:
    """Return a masked version of a key_id for display."""
    if len(key_id) <= 8:
        return f"{key_id[:2]}****"
    return f"{key_id[:6]}****{key_id[-2:]}"
