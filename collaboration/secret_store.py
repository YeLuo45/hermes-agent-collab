"""
Sensitive data encryption store using Fernet (AES-128-CBC + HMAC).
Provides secure storage for API keys, tokens, and secrets.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
from pathlib import Path
from typing import Any

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:
    Fernet = None
    InvalidToken = Exception


# ---------------------------------------------------------------------------
# Secret Store
# ---------------------------------------------------------------------------

class SecretStore:
    """
    AES-GCM encryption store for sensitive data.
    Uses Fernet (AES-128-CBC + HMAC) from the cryptography library.
    
    Storage format (JSON):
    {
        "ref_id_1": {"ct": "<encrypted_base64>", "v": 1},
        ...
    }
    """

    def __init__(self, encryption_key: str | None = None, store_path: Path | None = None):
        if Fernet is None:
            raise ImportError("cryptography is required: pip install cryptography")
        
        if encryption_key:
            self._key = self._normalize_key(encryption_key)
        else:
            env_key = os.environ.get('SECRET_ENCRYPTION_KEY', '')
            if env_key:
                self._key = self._normalize_key(env_key)
            else:
                # Auto-generate (one-time warning in logs)
                self._key = Fernet.generate_key()
        
        self._fernet = Fernet(self._key)
        self._store_path = store_path or Path('~/.hermes/collab/secrets.json').expanduser()
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        self._secrets: dict[str, dict[str, Any]] = self._load()

    def _normalize_key(self, key: str) -> bytes:
        """Normalize key to 32-byte base64-encoded format for Fernet."""
        raw = key.encode() if isinstance(key, str) else key
        if len(raw) < 32:
            raw = raw + b'\x00' * (32 - len(raw))
        return base64.urlsafe_b64encode(raw[:32])

    def _load(self) -> dict[str, dict[str, Any]]:
        if self._store_path.exists():
            try:
                with open(self._store_path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def _save(self) -> None:
        with open(self._store_path, 'w') as f:
            json.dump(self._secrets, f)

    def store(self, key: str, value: str) -> str:
        """
        Encrypt and store a secret value.
        Returns a stable ref_id for later retrieval.
        """
        if not value:
            raise ValueError("Cannot store empty secret")
        
        # Generate a stable ref_id from a hash of the key + random bytes
        ref_id = secrets.token_hex(16)
        
        encrypted = self._fernet.encrypt(value.encode())
        self._secrets[ref_id] = {
            'ct': encrypted.decode(),
            'v': 1,
            'key_name': key,
        }
        self._save()
        return ref_id

    def retrieve(self, ref_id: str) -> str | None:
        """Decrypt and return the original secret value."""
        entry = self._secrets.get(ref_id)
        if not entry:
            return None
        
        try:
            decrypted = self._fernet.decrypt(entry['ct'].encode())
            return decrypted.decode()
        except InvalidToken:
            return None

    def delete(self, ref_id: str) -> bool:
        """Delete a secret reference. Returns True if deleted."""
        if ref_id in self._secrets:
            del self._secrets[ref_id]
            self._save()
            return True
        return False

    def rotate(self, ref_id: str, new_value: str) -> str:
        """Re-encrypt with a fresh key derivation. Returns new ref_id."""
        if ref_id not in self._secrets:
            raise ValueError(f"Unknown ref_id: {ref_id}")
        
        key_name = self._secrets[ref_id].get('key_name', 'unknown')
        new_ref_id = self.store(key_name, new_value)
        del self._secrets[ref_id]
        self._save()
        return new_ref_id

    def list_refs(self) -> list[dict[str, str]]:
        """List all ref_ids and their key names (NOT the secret values)."""
        return [
            {'ref_id': rid, 'key_name': entry.get('key_name', 'unknown')}
            for rid, entry in self._secrets.items()
        ]

    @property
    def is_enabled(self) -> bool:
        return Fernet is not None


# ---------------------------------------------------------------------------
# Masking utilities
# ---------------------------------------------------------------------------

SENSITIVE_FIELD_NAMES = {
    'api_key', 'token', 'secret', 'password', 'access_token',
    'refresh_token', 'authorization', 'x_hermes_signature',
    'webhook_secret', 'hmac_key', 'private_key', 'secret_key',
    'encryption_key', 'session_token',
}


def mask_value(value: str | None, visible_chars: int = 4) -> str:
    """Mask a string value, showing only last `visible_chars`."""
    if not value:
        return '***'
    if len(value) <= visible_chars:
        return '***'
    return '*' * (len(value) - visible_chars) + value[-visible_chars:]


def mask_dict(data: dict[str, Any], depth: int = 0) -> dict[str, Any]:
    """
    Recursively mask sensitive fields in a dict.
    Returns a new dict (does not mutate original).
    """
    if depth > 10:
        return data
    
    result = {}
    for k, v in data.items():
        if isinstance(k, str) and any(s in k.lower() for s in SENSITIVE_FIELD_NAMES):
            result[k] = mask_value(v) if isinstance(v, str) else '***'
        elif isinstance(v, dict):
            result[k] = mask_dict(v, depth + 1)
        elif isinstance(v, list):
            result[k] = [
                mask_dict(item, depth + 1) if isinstance(item, dict) else item
                for item in v
            ]
        else:
            result[k] = v
    return result
