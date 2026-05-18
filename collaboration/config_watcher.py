"""File-based configuration watcher — polls config file for changes and publishes ConfigChangedEvent."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class ConfigWatcher:
    """
    Polls a configuration file for mtime changes and fires a ConfigChangedEvent
    when the file is modified.

    Uses a low-priority background task so it never blocks the main scheduler.
    """

    def __init__(
        self,
        config_path: str,
        poll_interval: float = 5.0,
        enabled: bool = True,
    ):
        self._config_path = Path(config_path)
        self._poll_interval = poll_interval
        self._enabled = enabled
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_mtime: float | None = None
        self._last_reload_id: str | None = None

        # Lazily resolved at start() — set by set_message_bus()
        self._message_bus = None
        self._priority_scheduler = None

    def set_message_bus(self, bus):
        self._message_bus = bus

    def set_scheduler(self, scheduler):
        self._priority_scheduler = scheduler

    @property
    def last_reload_id(self) -> str | None:
        return self._last_reload_id

    async def start(self) -> None:
        """Start the background polling loop."""
        if not self._enabled:
            logger.info("ConfigWatcher disabled — skipping start")
            return
        if self._running:
            logger.warning("ConfigWatcher already running")
            return

        if not self._config_path.exists():
            logger.warning("Config file does not exist: %s — watcher will poll until it appears", self._config_path)
            self._last_mtime = None
        else:
            self._last_mtime = self._config_path.stat().st_mtime

        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("ConfigWatcher started (path=%s, interval=%.1fs)", self._config_path, self._poll_interval)

    async def stop(self) -> None:
        """Stop the polling loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("ConfigWatcher stopped")

    async def _poll_loop(self) -> None:
        """Background polling loop — runs at HIGH priority every poll_interval seconds."""
        while self._running:
            try:
                await asyncio.sleep(self._poll_interval)
                await self._check()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("ConfigWatcher poll error: %s", exc)

    async def _check(self) -> None:
        """Check if config file mtime changed since last poll."""
        if not self._config_path.exists():
            return

        try:
            current_mtime = self._config_path.stat().st_mtime
        except OSError as exc:
            logger.warning("Failed to stat config file: %s", exc)
            return

        if self._last_mtime is None:
            self._last_mtime = current_mtime
            return

        if current_mtime == self._last_mtime:
            return  # No change

        self._last_mtime = current_mtime
        reload_id = str(uuid.uuid4())
        self._last_reload_id = reload_id

        changed_keys = self._read_changed_keys()
        timestamp = datetime.now(timezone.utc).isoformat()

        logger.info("Config file changed: %s (reload_id=%s)", self._config_path, reload_id)

        if self._message_bus is not None:
            # Import here to avoid circular deps — HookEvent is in models
            from collaboration.models import HookEvent

            class ConfigChangedEvent(HookEvent):
                path: str
                reload_id: str
                changed_keys: list[str]
                timestamp: str

                def to_dict(self) -> dict:
                    return {
                        "event_type": self.event_type,
                        "path": self.path,
                        "reload_id": self.reload_id,
                        "changed_keys": self.changed_keys,
                        "timestamp": self.timestamp,
                    }

            event = ConfigChangedEvent(
                event_type="config.changed",
                path=str(self._config_path),
                reload_id=reload_id,
                changed_keys=changed_keys,
                timestamp=timestamp,
            )
            await self._message_bus.publish(event)

    def _read_changed_keys(self) -> list[str]:
        """
        Attempt to parse the config file and return top-level keys.
        Returns ['<unknown>'] if the file cannot be parsed.
        Subclasses / callers can override for richer diff.
        """
        try:
            import yaml

            with open(self._config_path, "r") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                return list(data.keys())
        except Exception:
            pass

        try:
            import json

            with open(self._config_path, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return list(data.keys())
        except Exception:
            pass

        return ["<unknown>"]

    async def trigger_reload(self) -> str:
        """
        Manually trigger a reload as if the file changed.
        Returns the reload_id.
        """
        reload_id = str(uuid.uuid4())
        self._last_reload_id = reload_id

        if self._message_bus is not None:
            from collaboration.models import HookEvent

            class ConfigChangedEvent(HookEvent):
                path: str
                reload_id: str
                changed_keys: list[str]
                timestamp: str

                def to_dict(self) -> dict:
                    return {
                        "event_type": self.event_type,
                        "path": self.path,
                        "reload_id": self.reload_id,
                        "changed_keys": self.changed_keys,
                        "timestamp": self.timestamp,
                    }

            event = ConfigChangedEvent(
                event_type="config.changed",
                path=str(self._config_path),
                reload_id=reload_id,
                changed_keys=self._read_changed_keys(),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            await self._message_bus.publish(event)

        return reload_id
