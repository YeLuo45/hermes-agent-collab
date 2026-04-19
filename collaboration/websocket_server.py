"""WebSocket server for real-time collaboration events.

Runs as a FastAPI WebSocket endpoint integrated with the Hermes web server.
Broadcasts events from the collaboration EventBus to all connected clients
in the same workspace room.

Event format:
{
    "event": "task.updated | agent.status_changed | ...",
    "workspace_id": "uuid",
    "payload": {...},
    "timestamp": "ISO8601"
}
"""

import asyncio
import json
import logging
from collections import defaultdict
from typing import TYPE_CHECKING

try:
    import websockets
except ImportError:
    websockets = None

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from collaboration.events import Event, EventType, get_event_bus

_log = logging.getLogger(__name__)

# ─── Connection manager ───────────────────────────────────────────────────────

# Global registry: workspace_id -> set of websocket connections
_WS_ROOMS: dict[str, set[WebSocket]] = defaultdict(set)
_WS_LOCK = asyncio.Lock()


async def _join_room(ws: WebSocket, workspace_id: str):
    async with _WS_LOCK:
        _WS_ROOMS[workspace_id].add(ws)


async def _leave_room(ws: WebSocket, workspace_id: str):
    async with _WS_LOCK:
        _WS_ROOMS[workspace_id].discard(ws)
        if not _WS_ROOMS[workspace_id]:
            del _WS_ROOMS[workspace_id]


async def _broadcast(workspace_id: str, message: str):
    """Send a message to all clients in a workspace room."""
    if workspace_id not in _WS_ROOMS:
        return
    dead = set()
    for ws in _WS_ROOMS[workspace_id]:
        try:
            await ws.send_text(message)
        except Exception:
            dead.add(ws)
    if dead:
        async with _WS_LOCK:
            _WS_ROOMS[workspace_id] -= dead


# ─── EventBus subscriber ──────────────────────────────────────────────────────

async def _on_event(event: Event):
    """Forward an EventBus event to the appropriate WebSocket room."""
    if event.workspace_id:
        msg = json.dumps(event.to_dict(), default=str)
        await _broadcast(event.workspace_id, msg)


# ─── FastAPI router ───────────────────────────────────────────────────────────

ws_router = APIRouter(tags=["collaboration"])


@ws_router.websocket("/ws/collaboration/{workspace_id}")
async def collaboration_ws_endpoint(websocket: WebSocket, workspace_id: str):
    """WebSocket endpoint for real-time collaboration events.

    Clients connect to /ws/collaboration/{workspace_id} and receive
    all task/agent/workspace events for that workspace.
    """
    await websocket.accept()
    await _join_room(websocket, workspace_id)
    _log.info("WebSocket client joined workspace=%s", workspace_id)

    try:
        # Subscribe to the event bus for this workspace
        bus = get_event_bus()
        await bus.subscribe(
            _on_event,
            event_types={e.value for e in EventType},
            workspace_id=workspace_id,
        )

        # Keep connection alive, handle incoming messages
        while True:
            try:
                # No expect client messages in v1; just wait for disconnect
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                _log.debug("Received from client in %s: %s", workspace_id, data)
            except asyncio.TimeoutError:
                # Send a ping to keep the connection alive
                try:
                    await websocket.send_json({"event": "ping", "timestamp": ""})
                except Exception:
                    break

    except WebSocketDisconnect:
        _log.info("WebSocket client left workspace=%s", workspace_id)
    except Exception:
        _log.exception("WebSocket error in workspace=%s", workspace_id)
    finally:
        await _leave_room(websocket, workspace_id)


# ─── REST helpers (optional, for polling fallback) ───────────────────────────

def ws_rooms_summary() -> dict[str, int]:
    """Return a summary of connected clients per workspace (for debugging)."""
    return {wid: len(clients) for wid, clients in _WS_ROOMS.items()}


# ─── Standalone WebSocket server (alternative mode) ──────────────────────────

async def standalone_server(host: str = "127.0.0.1", port: int = 3101):
    """Run a standalone WebSocket server (for when not using FastAPI).

    Use this only if the FastAPI integration is not available.
    """
    if websockets is None:
        raise RuntimeError("websockets library not installed")

    async def handler(ws: websockets.WebSocketServerProtocol, path: str):
        # path format: /{workspace_id}
        workspace_id = path.lstrip("/") or "default"
        await ws.accept()
        await _join_room(ws, workspace_id)
        _log.info("Standalone WS client joined workspace=%s", workspace_id)

        # Subscribe to event bus
        bus = get_event_bus()
        await bus.subscribe(
            _on_event,
            event_types={e.value for e in EventType},
            workspace_id=workspace_id,
        )

        try:
            async for msg in ws:
                _log.debug("Standalone WS received: %s", msg)
        except websockets.ConnectionClosed:
            pass
        finally:
            await _leave_room(ws, workspace_id)

    _log.info("Starting standalone WebSocket server on %s:%d", host, port)
    async with websockets.serve(handler, host, port):
        await asyncio.Future()  # run forever
