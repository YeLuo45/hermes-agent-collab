"""Configuration diff utility — detect and compute changes between config snapshots."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any


@dataclass
class ConfigDiff:
    """Immutable record of a configuration change."""

    reload_id: str
    changed_keys: list[str]
    old_values: dict[str, Any]
    new_values: dict[str, Any]
    requester: str

    def summary(self) -> str:
        if not self.changed_keys:
            return "No changes"
        lines = [f"  {k}: {self.old_values[k]!r} → {self.new_values[k]!r}" for k in self.changed_keys]
        return "\n".join(lines)


def compute_diff(
    old_config: Any,
    new_config: Any,
    reload_id: str,
    requester: str,
) -> ConfigDiff:
    """
    Compute the diff between two config objects.

    Uses dataclass fields to iterate all keys.
    Returns a ConfigDiff with only the keys that actually changed.
    """
    changed_keys: list[str] = []
    old_values: dict[str, Any] = {}
    new_values: dict[str, Any] = {}

    # Handle the case where old/new are dicts instead of dataclasses
    if isinstance(old_config, dict):
        old_keys = set(old_config.keys())
        old_getter = old_config.__getitem__
    else:
        old_keys = {f.name for f in fields(old_config)}
        old_getter = lambda k: getattr(old_config, k)

    if isinstance(new_config, dict):
        new_keys = set(new_config.keys())
        new_getter = new_config.__getitem__
    else:
        new_keys = {f.name for f in fields(new_config)}
        new_getter = lambda k: getattr(new_config, k)

    all_keys = old_keys | new_keys

    for key in all_keys:
        old_val = old_getter(key) if key in old_keys else None
        new_val = new_getter(key) if key in new_keys else None
        if old_val != new_val:
            changed_keys.append(key)
            old_values[key] = old_val
            new_values[key] = new_val

    return ConfigDiff(
        reload_id=reload_id,
        changed_keys=changed_keys,
        old_values=old_values,
        new_values=new_values,
        requester=requester,
    )


def apply_diff(current_config: Any, diff: ConfigDiff) -> Any:
    """
    Apply a ConfigDiff to a config object, returning a new instance.
    For dict configs, returns a new dict. For dataclass configs,
    returns a new instance with updated field values.
    """
    if isinstance(current_config, dict):
        result = dict(current_config)
        for key in diff.changed_keys:
            result[key] = diff.new_values[key]
        return result

    # dataclass — create new instance with changed fields
    kwargs = {}
    for f in fields(current_config):
        if f.name in diff.changed_keys:
            kwargs[f.name] = diff.new_values[f.name]
        else:
            kwargs[f.name] = getattr(current_config, f.name)
    return current_config.__class__(**kwargs)
