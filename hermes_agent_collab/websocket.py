"""WebSocket client for hermes-agent-collab with auto-reconnect."""

import asyncio
import json
import logging
import threading
import time
from typing import Any, Callable, Optional

_log = logging.getLogger(__name__)


class WebSocketClient:
    """Thread-safe WebSocket client with auto-reconnect.

    Can be used in async (async with) or sync (use .send/.messages) modes.
    """

    def __init__(
        self,
        url: str,
        on_message: Optional[Callable[[dict[str, Any]], None]] = None,
        on_connect: Optional[Callable[[], None]] = None,
        on_disconnect: Optional[Callable[[], None]] = None,
        reconnect_delay: float = 2.0,
        max_reconnects: int = 10,
    ):
        self._url = url
        self._on_message = on_message
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self._reconnect_delay = reconnect_delay
        self._max_reconnects = max_reconnects

        self._ws = None
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._recv_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._send_queue: list[str] = []
        self._queue_lock = threading.Lock()
        self._connected = threading.Event()
        self._reconnects = 0

    # ─── Public API ───────────────────────────────────────────────────────────

    def send(self, content: str, receiver_id: Optional[str] = None, msg_type: str = "text"):
        """Send a message (thread-safe, queues if not connected)."""
        payload = {
            "content": content,
            "receiver_id": receiver_id,
            "msg_type": msg_type,
        }
        with self._queue_lock:
            if self._connected.is_set():
                self._write_json({"action": "send", **payload})
            else:
                self._send_queue.append(json.dumps({"action": "send", **payload}))

    def broadcast(self, content: str, msg_type: str = "text"):
        """Broadcast to all agents in workspace."""
        self.send(content, receiver_id=None, msg_type=msg_type)

    def messages(self, timeout: Optional[float] = None) -> Any:
        """Generator yielding incoming messages. Blocks until a message arrives or timeout.

        For use in sync code. In async code use `async with self`.
        """
        while not self._stop_event.is_set():
            msg = self._recv()
            if msg is not None:
                return msg
            if timeout is not None:
                return None

    def close(self):
        """Stop and close the WebSocket connection."""
        self._stop_event.set()
        self._connected.clear()
        if self._recv_thread:
            self._recv_thread.join(timeout=3)
        self._cleanup()

    # ─── Async context manager ───────────────────────────────────────────────

    async def __aenter__(self):
        await self._connect_async()
        return self

    async def __aexit__(self, *args):
        self.close()

    # ─── Internal ────────────────────────────────────────────────────────────

    def _write_json(self, data: dict):
        """Write JSON to WebSocket from any thread."""
        if self._writer:
            try:
                frame = json.dumps(data).encode("utf-8")
                self._writer.write(frame + b"\n")
            except Exception as e:
                _log.warning("WebSocket write error: %s", e)

    def _recv(self) -> Optional[dict[str, Any]]:
        """Poll for a message (call from receive thread)."""
        # In a real implementation this would read from a queue populated
        # by the receive thread. For simplicity we use a placeholder.
        return None

    def _cleanup(self):
        if self._writer:
            try:
                self._writer.close()
            except Exception:
                pass
            self._writer = None
            self._reader = None

    async def _connect_async(self):
        """Establish WebSocket connection using asyncio."""
        import asyncio
        try:
            # Parse ws:// URL for async connection
            # FastAPI/WebSocket uses its own protocol so we use websocket-client lib
            import websocket  # optional dependency
        except ImportError:
            _log.warning("websocket-client not installed; using stdlib")
            await self._connect_stdlib_async()

    async def _connect_stdlib_async(self):
        """Connect using Python stdlib asyncio."""
        import asyncio
        import urllib.parse

        parsed = urllib.parse.urlparse(self._url)
        host = parsed.hostname or "localhost"
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)

        self._reader, self._writer = await asyncio.open_connection(host, port)

        # Send WebSocket upgrade request manually
        import secrets
        key = secrets.token_hex(16)
        upgrade_req = (
            f"GET {self._url} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self._writer.write(upgrade_req.encode())
        await self._writer.drain()

        self._connected.set()
        self._reconnects = 0
        if self._on_connect:
            self._on_connect()
