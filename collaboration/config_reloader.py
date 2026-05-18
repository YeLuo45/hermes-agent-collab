"""SIGUSR1 signal-based configuration reloader.

Requires collaboration/config.py to export `collab_config` and `message_bus`.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collaboration.config import CollabConfig

logger = logging.getLogger(__name__)


class ConfigReloader:
    """
    Listens for SIGUSR1 and triggers a hot-reload of the application config.

    On reload, publishes a ConfigReloadRequest to the message bus so all
    registered components (RateLimiter, Tracing, ChannelAdapter, etc.)
    can react to the change.

    Usage::

        reloader = ConfigReloader(collab_config, message_bus)
        await reloader.start()
        # Now: kill -USR1 <pid>
    """

    def __init__(
        self,
        config: CollabConfig,
        message_bus,
        enabled: bool = True,
    ):
        self._config = config
        self._bus = message_bus
        self._enabled = enabled
        self._sigint_received = asyncio.Event()
        self._reload_id: str | None = None

    @property
    def last_reload_id(self) -> str | None:
        return self._reload_id

    async def start(self) -> None:
        """Register SIGUSR1 handler on the running event loop."""
        if not self._enabled:
            logger.info("ConfigReloader disabled — SIGUSR1 handler not registered")
            return

        loop = asyncio.get_running_loop()

        def _sigusr1_handler() -> None:
            asyncio.create_task(self._do_reload())

        try:
            loop.add_signal_handler(signal.SIGUSR1, _sigusr1_handler)
            logger.info("ConfigReloader: SIGUSR1 handler registered (pid=%d)", __import__("os").getpid())
        except (ValueError, OSError) as exc:
            logger.warning("Could not register SIGUSR1 handler: %s", exc)

    async def stop(self) -> None:
        """Remove the SIGUSR1 handler."""
        try:
            loop = asyncio.get_running_loop()
            loop.remove_signal_handler(signal.SIGUSR1)
        except (ValueError, OSError):
            pass
        logger.info("ConfigReloader stopped")

    async def _do_reload(self) -> None:
        """Execute the reload: compute diff, publish event, update components."""
        reload_id = str(uuid.uuid4())
        self._reload_id = reload_id
        timestamp = datetime.now(timezone.utc).isoformat()

        logger.info("Config reload triggered via SIGUSR1 (reload_id=%s)", reload_id)

        if self._bus is not None:
            from collaboration.models import HookEvent

            class ConfigReloadRequest(HookEvent):
                requester: str
                reload_id: str
                timestamp: str

                def to_dict(self) -> dict:
                    return {
                        "event_type": self.event_type,
                        "requester": self.requester,
                        "reload_id": self.reload_id,
                        "timestamp": self.timestamp,
                    }

            event = ConfigReloadRequest(
                event_type="config.reload_request",
                requester="SIGUSR1",
                reload_id=reload_id,
                timestamp=timestamp,
            )
            await self._bus.publish(event)

    async def reload_now(self, requester: str = "API") -> str:
        """
        Programmatically trigger a reload.
        Returns the reload_id.
        """
        reload_id = str(uuid.uuid4())
        self._reload_id = reload_id
        timestamp = datetime.now(timezone.utc).isoformat()

        if self._bus is not None:
            from collaboration.models import HookEvent

            class ConfigReloadRequest(HookEvent):
                requester: str
                reload_id: str
                timestamp: str

                def to_dict(self) -> dict:
                    return {
                        "event_type": self.event_type,
                        "requester": self.requester,
                        "reload_id": self.reload_id,
                        "timestamp": self.timestamp,
                    }

            event = ConfigReloadRequest(
                event_type="config.reload_request",
                requester=requester,
                reload_id=reload_id,
                timestamp=timestamp,
            )
            await self._bus.publish(event)

        return reload_id
