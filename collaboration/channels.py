"""Channel adapters for the AsyncMessageBus.

Provides pluggable transport layer adapters:
- WebSocketChannelAdapter: wraps existing WebSocket broadcast logic
- SSEChannelAdapter: wraps existing SSE endpoint delivery
- HTTPWebhookAdapter: nanobot-style HTTP webhook push to external endpoints
"""

import asyncio
import json
import logging
from abc import ABC
from typing import Any, Callable, Coroutine

from collaboration.events import Event

_log = logging.getLogger(__name__)


# ─── WebSocket Channel Adapter ───────────────────────────────────────────────


class WebSocketChannelAdapter:
    """Channel adapter that broadcasts events via the WebSocket room system.

    Wraps the existing _WS_ROOMS / _broadcast machinery from websocket_server.py.
    """

    def __init__(self):
        # Defer import to avoid circular dependency at module load
        from collaboration.websocket_server import (
            _WS_ROOMS,
            _WS_LOCK,
            _broadcast,
        )
        self._rooms = _WS_ROOMS
        self._lock = _WS_LOCK
        self._broadcast_raw = _broadcast

    async def publish(self, event: Event) -> bool:
        """Broadcast an event to all WebSocket clients in the workspace room."""
        if not event.workspace_id:
            return True
        msg = json.dumps(event.to_dict(), default=str)
        await self._broadcast_raw(event.workspace_id, msg)
        return True

    async def subscribe(self, handler: Callable[[Event], Coroutine[Any, Any, None]]) -> None:
        """Register a handler (not directly used for WebSocket — clients subscribe via WS protocol)."""
        # WebSocket clients subscribe through the WS protocol, not via this API
        pass

    async def start(self) -> None:
        """No-op: WebSocket rooms are established on client connections."""
        pass

    async def stop(self) -> None:
        """No-op: graceful shutdown handled by the server."""
        pass


# ─── SSE Channel Adapter ─────────────────────────────────────────────────────


class SSEChannelAdapter:
    """Channel adapter that delivers events to SSE clients via SSEManager.

    Wraps the existing _sse_manager from collab_api.py.
    """

    def __init__(self):
        from collaboration.collab_api import _sse_manager
        self._sse_manager = _sse_manager

    async def publish(self, event: Event) -> bool:
        """Push an event to all connected SSE clients."""
        event_dict = {
            "event": event.event_type.value,
            "workspace_id": event.workspace_id,
            "payload": event.payload,
            "timestamp": event.timestamp,
        }
        await self._sse_manager.broadcast(event_dict)
        return True

    async def subscribe(self, handler: Callable[[Event], Coroutine[Any, Any, None]]) -> None:
        """Register an event handler for incoming events (not used for SSE push)."""
        pass

    async def start(self) -> None:
        """No-op: SSE manager is started with the FastAPI server."""
        pass

    async def stop(self) -> None:
        """No-op: SSE connections are closed on client disconnect."""
        pass


# ─── HTTP Webhook Adapter ─────────────────────────────────────────────────────


class HTTPWebhookChannelAdapter:
    """Channel adapter that POSTs events to external HTTP webhook endpoints.

    nanobot-style: configurable list of webhook URLs, supports workspace-specific routing.
    Retries are handled by the AsyncMessageBus retry logic; this adapter just publishes once.
    """

    def __init__(self, webhook_urls: list[str] | None = None, timeout: float = 5.0):
        """
        Args:
            webhook_urls: List of HTTP(S) endpoint URLs to POST events to.
            timeout: Request timeout in seconds (default 5s).
        """
        import httpx
        self._httpx = httpx
        self._webhook_urls = webhook_urls or []
        self._timeout = timeout

    def add_webhook(self, url: str) -> None:
        """Add a webhook URL dynamically."""
        if url not in self._webhook_urls:
            self._webhook_urls.append(url)

    def remove_webhook(self, url: str) -> None:
        """Remove a webhook URL."""
        if url in self._webhook_urls:
            self._webhook_urls.remove(url)

    async def publish(self, event: Event) -> bool:
        """POST the event to all configured webhook URLs."""
        if not self._webhook_urls:
            return True

        payload = event.to_dict()
        async with self._httpx.AsyncClient(timeout=self._timeout) as client:
            tasks = [
                client.post(url, json=payload)
                for url in self._webhook_urls
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for url, result in zip(self._webhook_urls, results):
                if isinstance(result, Exception):
                    _log.warning("Webhook POST to %s failed: %s", url, result)
                    raise result
        return True

    async def subscribe(self, handler: Callable[[Event], Coroutine[Any, Any, None]]) -> None:
        """Register a handler for incoming webhook events (for hybrid inbound scenarios)."""
        pass

    async def start(self) -> None:
        """Validate webhook URLs on startup (optional)."""
        pass

    async def stop(self) -> None:
        """No-op."""
        pass


# ─── Exports ──────────────────────────────────────────────────────────────────


__all__ = [
    "WebSocketChannelAdapter",
    "SSEChannelAdapter",
    "HTTPWebhookChannelAdapter",
]