"""
Log filtering for sensitive data redaction.
Prevents API keys, tokens, and secrets from leaking into logs.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any


SENSITIVE_PATTERNS = [
    # Generic patterns
    (re.compile(r'(api[_-]?key|token|secret|password|authorization)\s*[=:]\s*["\']?([\w\-\.]+)["\']?', re.IGNORECASE), r'\1=***'),
    # Bearer tokens
    (re.compile(r'Bearer\s+([\w\-\.]+)', re.IGNORECASE), 'Bearer ***'),
    # Basic auth
    (re.compile(r'Basic\s+([\w+/=]+)', re.IGNORECASE), 'Basic ***'),
    # HMAC signatures
    (re.compile(r'X-Hermes-Signature:\s*[\w+/=]+', re.IGNORECASE), 'X-Hermes-Signature: ***'),
    # Fernet tokens
    (re.compile(r'gAAAAA[\w\-]+', re.IGNORECASE), '***FERNET***'),
    # Hex API keys (32+ chars)
    (re.compile(r'(["\'])((?:[0-9a-fA-F]{32,}))(["\'])'), r'\1***HEX***\3'),
    # URL with credentials
    (re.compile(r'https?://[^:]+:[^@]+@[^\s]+'), '***URLcreds***'),
]


class SecretRedactingFilter(logging.Filter):
    """
    Logging filter that redacts sensitive values from log messages.
    
    Usage:
        handler.addFilter(SecretRedactingFilter())
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, 'msg'):
            return True
        
        msg = record.getMessage() if record.msg else ''
        
        # Redact patterns in message
        for pattern, replacement in SENSITIVE_PATTERNS:
            msg = pattern.sub(replacement, msg)
        
        # Also redact in extra args
        if record.args:
            new_args = tuple(self._redact_arg(arg) for arg in record.args)
            record.args = new_args
        
        # Store redacted message back
        if record.msg:
            record.msg = msg
        
        return True

    def _redact_arg(self, arg: Any) -> Any:
        """Recursively redact sensitive data in an argument."""
        if isinstance(arg, str):
            result = arg
            for pattern, replacement in SENSITIVE_PATTERNS:
                result = pattern.sub(replacement, result)
            return result
        elif isinstance(arg, dict):
            return self._redact_dict(arg)
        elif isinstance(arg, (list, tuple)):
            return type(arg)(self._redact_arg(item) for item in arg)
        return arg

    def _redact_dict(self, d: dict[str, Any], depth: int = 0) -> dict[str, Any]:
        """Recursively redact sensitive fields in a dict."""
        if depth > 8:
            return d
        
        SENSITIVE_KEYS = {
            'api_key', 'token', 'secret', 'password', 'access_token',
            'refresh_token', 'authorization', 'x_hermes_signature',
            'webhook_secret', 'hmac_key', 'private_key', 'encryption_key',
            'session_token', 'bearer', 'credentials',
        }
        
        result = {}
        for k, v in d.items():
            if isinstance(k, str) and any(s in k.lower() for s in SENSITIVE_KEYS):
                result[k] = '***'
            elif isinstance(v, dict):
                result[k] = self._redact_dict(v, depth + 1)
            elif isinstance(v, (list, tuple)):
                result[k] = type(v)(self._redact_arg(item) for item in v)
            elif isinstance(v, str):
                result[k] = self._redact_arg(v)
            else:
                result[k] = v
        return result
