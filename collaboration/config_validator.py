"""
JSON Schema validator for workspace configuration.
Provides pre-apply validation for hot-reload safety.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default embedded schema
# ---------------------------------------------------------------------------

DEFAULT_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "HermesAgentCollabWorkspaceConfig",
    "type": "object",
    "required": ["version", "limits", "features"],
    "properties": {
        "version": {
            "type": "string",
            "pattern": r"^\d+\.\d+\.\d+$",
            "description": "Config format version (semver)",
        },
        "limits": {
            "type": "object",
            "description": "Resource limits for the workspace",
            "properties": {
                "max_agents": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10000,
                    "description": "Maximum number of agents",
                },
                "max_tasks_per_agent": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Maximum concurrent tasks per agent",
                },
                "max_workspace_memory_mb": {
                    "type": "integer",
                    "minimum": 64,
                    "description": "Max memory per workspace in MB",
                },
                "rate_limit_per_minute": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "API rate limit per minute",
                },
                "max_concurrent_tasks": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Max concurrent tasks in workspace",
                },
            },
        },
        "features": {
            "type": "object",
            "description": "Feature toggles",
            "properties": {
                "webhooks_enabled": {"type": "boolean"},
                "grpc_enabled": {"type": "boolean"},
                "telemetry_enabled": {"type": "boolean"},
                "multi_tenant": {"type": "boolean"},
                "task_cache_enabled": {"type": "boolean"},
                "config_hotreload_enabled": {"type": "boolean"},
            },
        },
        "quotas": {
            "type": "object",
            "description": "Per-resource quota limits",
            "additionalProperties": {
                "type": "object",
                "properties": {
                    "max_count": {"type": "integer", "minimum": 0},
                    "window_seconds": {"type": "integer", "minimum": 1},
                    "burst": {"type": "integer", "minimum": 0},
                },
                "required": ["max_count"],
            },
        },
        "notifications": {
            "type": "object",
            "description": "Notification channel configuration",
            "properties": {
                "slack_enabled": {"type": "boolean"},
                "slack_webhook_url": {"type": "string", "format": "uri"},
                "email_enabled": {"type": "boolean"},
                "email_recipients": {"type": "array", "items": {"type": "string", "format": "email"}},
            },
        },
        "security": {
            "type": "object",
            "properties": {
                "require_api_key": {"type": "boolean"},
                "allowed_origins": {"type": "array", "items": {"type": "string"}},
                "max_request_size_mb": {"type": "integer", "minimum": 1},
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------

@dataclass
class ValidationError:
    path: str          # JSON path, e.g. "limits.max_agents"
    message: str
    value: Any = None


@dataclass
class ValidationResult:
    valid: bool
    errors: list[ValidationError] = field(default_factory=list)

    @property
    def error_summary(self) -> str:
        if self.valid:
            return "valid"
        return "; ".join(f"{e.path}: {e.message}" for e in self.errors)


# ---------------------------------------------------------------------------
# Schema validator
# ---------------------------------------------------------------------------

class ConfigSchemaValidator:
    """
    Validates workspace configuration against JSON Schema.
    
    Usage:
        validator = ConfigSchemaValidator()
        result = validator.validate(config_dict)
        if not result.valid:
            for err in result.errors:
                print(f"{err.path}: {err.message}")
    """

    def __init__(self, schema_path: str | Path | None = None):
        self._schema: dict[str, Any] = self._load_schema(schema_path)
        self._validator_impl = None  # Lazy-loaded

    def _load_schema(self, schema_path: str | Path | None) -> dict[str, Any]:
        """Load schema from path or return embedded default."""
        if schema_path:
            p = Path(schema_path)
            if p.exists():
                with open(p) as f:
                    return json.load(f)
            _log.warning(f"Schema path {p} not found, using embedded default")
        return DEFAULT_SCHEMA

    @property
    def validator(self):
        """Lazy-load jsonschema validator (avoids hard dependency)."""
        if self._validator_impl is None:
            try:
                import jsonschema
                import referencing
                # Enable dynamic reference resolution
                registry = referencing.Registry()
                registry = registry.with_resource(
                    "http://json-schema.org/draft-07/schema#",
                    referencing.Resource.from_contents(DEFAULT_SCHEMA),
                )
                self._validator_impl = jsonschema.Draft7Validator
                self._jsonschema = jsonschema
            except ImportError:
                _log.warning("jsonschema not installed — using fallback regex validator")
                self._validator_impl = None
        return self._validator_impl

    def validate(self, config: dict[str, Any]) -> ValidationResult:
        """
        Fully validate a configuration dict against the schema.
        Returns ValidationResult with errors list if invalid.
        """
        validator = self.validator
        if validator is None:
            return self._fallback_validate(config)

        try:
            errors: list[ValidationError] = []
            for error in validator(self._schema).iter_errors(config):
                path = ".".join(str(p) for p in error.path) if error.path else "root"
                errors.append(ValidationError(
                    path=path,
                    message=error.message,
                    value=error.instance,
                ))
            return ValidationResult(valid=len(errors) == 0, errors=errors)
        except Exception as e:
            _log.error(f"Schema validation error: {e}")
            return ValidationResult(valid=False, errors=[
                ValidationError(path="root", message=f"Validation exception: {e}")
            ])

    def validate_partial(
        self,
        config: dict[str, Any],
        changed_keys: set[str],
    ) -> ValidationResult:
        """
        Validate only the changed keys of a configuration.
        Used by hot-reload to avoid full re-validation.
        
        Args:
            config: Full configuration dict
            changed_keys: Set of top-level keys that changed
        """
        if not changed_keys:
            return ValidationResult(valid=True)

        # Build a partial config with only changed keys
        partial: dict[str, Any] = {}
        for key in changed_keys:
            if key in config:
                partial[key] = config[key]

        if not partial:
            return ValidationResult(valid=True)

        # Use jsonschema $data reference trick for partial validation
        # OR: simply validate the partial subtree(s)
        validator = self.validator
        if validator is None:
            return self._fallback_validate(config)

        errors: list[ValidationError] = []
        for key in changed_keys:
            if key not in config:
                continue
            # Find schema property for this key
            schema_prop = self._schema.get("properties", {}).get(key, {})
            if not schema_prop:
                continue  # Unknown key, skip
            for error in validator(schema_prop).iter_errors(config[key]):
                path = f"{key}." + ".".join(str(p) for p in error.path) if error.path else key
                errors.append(ValidationError(
                    path=path,
                    message=error.message,
                    value=error.instance,
                ))

        return ValidationResult(valid=len(errors) == 0, errors=errors)

    def _fallback_validate(self, config: dict[str, Any]) -> ValidationResult:
        """
        Fallback validator when jsonschema is not available.
        Performs basic type and range checks only.
        """
        errors: list[ValidationError] = []
        schema = self._schema

        # Required fields
        for required in schema.get("required", []):
            if required not in config or config[required] is None:
                errors.append(ValidationError(
                    path=required,
                    message=f"Required field '{required}' is missing",
                ))

        # Version format
        version = config.get("version")
        if version is not None:
            import re
            if not re.match(r"^\d+\.\d+\.\d+$", str(version)):
                errors.append(ValidationError(
                    path="version",
                    message="Version must match semver pattern (e.g. 1.0.0)",
                    value=version,
                ))

        # Limits range checks
        limits = config.get("limits", {})
        if isinstance(limits, dict):
            if "max_agents" in limits:
                v = limits["max_agents"]
                if not isinstance(v, int) or v < 1 or v > 10000:
                    errors.append(ValidationError(
                        path="limits.max_agents",
                        message="max_agents must be integer 1-10000",
                        value=v,
                    ))
            if "rate_limit_per_minute" in limits:
                v = limits["rate_limit_per_minute"]
                if not isinstance(v, int) or v < 1:
                    errors.append(ValidationError(
                        path="limits.rate_limit_per_minute",
                        message="rate_limit_per_minute must be positive integer",
                        value=v,
                    ))

        # Features boolean checks
        features = config.get("features", {})
        if isinstance(features, dict):
            for key, val in features.items():
                if not isinstance(val, bool):
                    errors.append(ValidationError(
                        path=f"features.{key}",
                        message=f"Feature '{key}' must be boolean",
                        value=val,
                    ))

        return ValidationResult(valid=len(errors) == 0, errors=errors)

    def is_valid_config(self, config: dict[str, Any]) -> bool:
        """Quick boolean check — returns True if config is valid."""
        return self.validate(config).valid
