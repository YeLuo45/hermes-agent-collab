"""Configuration hot-reload service — coordinates config changes across all components."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Callable

from collaboration.config_diff import ConfigDiff, compute_diff

logger = logging.getLogger(__name__)

# Global registry of components that want to be notified on config change
_hot_reload_callbacks: list[Callable[[ConfigDiff], None | AwaitableNone]] = []


def register_reload_callback(cb: Callable[[ConfigDiff], None | AwaitableNone]) -> None:
    """Register a callback to be invoked whenever the config is reloaded."""
    _hot_reload_callbacks.append(cb)


async def notify_components(diff: ConfigDiff) -> None:
    """Call all registered callbacks with the config diff."""
    for cb in _hot_reload_callbacks:
        result = cb(diff)
        if asyncio.iscoroutine(result):
            await result


class ConfigHotReloadService:
    """
    Coordinates configuration hot-reload across all components.

    This service:
    1. Holds the current CollabConfig snapshot (for diffing)
    2. Provides a `reload(new_config)` method that computes diff and notifies all components
    3. Integrates ConfigWatcher and ConfigReloader to auto-trigger reloads
    """

    def __init__(self, config: Any, message_bus=None):
        from collaboration.config_watcher import ConfigWatcher
        from collaboration.config_reloader import ConfigReloader

        self._current_config = config
        self._bus = message_bus
        self._watcher: ConfigWatcher | None = None
        self._reloader: ConfigReloader | None = None
        self._reload_history: list[ConfigDiff] = []
        self._lock = asyncio.Lock()

    @property
    def current_config(self) -> Any:
        return self._current_config

    @property
    def last_diff(self) -> ConfigDiff | None:
        return self._reload_history[-1] if self._reload_history else None

    @property
    def reload_history(self) -> list[ConfigDiff]:
        return list(self._reload_history)

    def setup_watcher(
        self,
        path: str,
        poll_interval: float = 5.0,
        enabled: bool = True,
    ) -> Any:
        """Create and configure the file watcher."""
        from collaboration.config_watcher import ConfigWatcher

        self._watcher = ConfigWatcher(
            config_path=path,
            poll_interval=poll_interval,
            enabled=enabled,
        )
        self._watcher.set_message_bus(self._bus)
        return self._watcher

    def setup_reloader(self, enabled: bool = True) -> Any:
        """Create and configure the SIGUSR1 reloader."""
        from collaboration.config_reloader import ConfigReloader

        self._reloader = ConfigReloader(
            config=self._current_config,
            message_bus=self._bus,
            enabled=enabled,
        )
        return self._reloader

    async def start(self) -> None:
        """Start the watcher and reloader."""
        if self._watcher:
            await self._watcher.start()
        if self._reloader:
            await self._reloader.start()

    async def stop(self) -> None:
        """Stop the watcher and reloader."""
        if self._watcher:
            await self._watcher.stop()
        if self._reloader:
            await self._reloader.stop()

    async def reload(self, new_config: Any, requester: str = "API") -> ConfigDiff:
        """
        Reload configuration: compute diff from current → new, notify components.

        Returns the ConfigDiff.
        """
        import uuid

        async with self._lock:
            reload_id = str(uuid.uuid4())
            diff = compute_diff(self._current_config, new_config, reload_id, requester)

            if not diff.changed_keys:
                logger.info("Config reload: no changes detected")
                return diff

            logger.info(
                "Config reload: %d keys changed (requester=%s): %s",
                len(diff.changed_keys),
                requester,
                diff.changed_keys,
            )

            # Notify all registered components
            await notify_components(diff)

            # Update snapshot
            self._current_config = new_config
            self._reload_history.append(diff)

            return diff


# Singleton
_service: ConfigHotReloadService | None = None


def get_hot_reload_service() -> ConfigHotReloadService | None:
    return _service


def init_hot_reload_service(config: Any, message_bus=None) -> ConfigHotReloadService:
    global _service
    _service = ConfigHotReloadService(config, message_bus)
    return _service
