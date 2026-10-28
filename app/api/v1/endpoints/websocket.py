"""WebSocket live events endpoint for timeline collaboration (Milestone P7).

Pushes op-applied events, plan generation progress, and render status to connected clients.
"""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Live Events"])


class TimelineConnectionManager:
    """Manages active WebSocket connections subscribed to timeline updates."""

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def _ensure_loop(self) -> None:
        if self._loop is None or self._loop.is_closed():
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                pass

    async def connect(self, websocket: WebSocket, timeline_id: str) -> None:
        """Accept connection and register websocket to timeline topic."""
        await websocket.accept()
        self._ensure_loop()
        if timeline_id not in self._connections:
            self._connections[timeline_id] = set()
        self._connections[timeline_id].add(websocket)
        logger.info("WebSocket client connected to timeline '%s'", timeline_id)

    def disconnect(self, websocket: WebSocket, timeline_id: str) -> None:
        """Remove disconnected websocket from registry."""
        if timeline_id in self._connections:
            self._connections[timeline_id].discard(websocket)
            if not self._connections[timeline_id]:
                del self._connections[timeline_id]
        logger.info("WebSocket client disconnected from timeline '%s'", timeline_id)

    async def broadcast(self, timeline_id: str, message: dict[str, Any]) -> None:
        """Broadcast JSON message to all clients listening to a specific timeline."""
        clients = list(self._connections.get(timeline_id, set()))
        if not clients:
            return

        dead_clients: list[WebSocket] = []
        for ws in clients:
            try:
                await ws.send_json(message)
            except Exception as exc:
                logger.warning("Failed to push event to websocket on %s: %s", timeline_id, exc)
                dead_clients.append(ws)

        for ws in dead_clients:
            self.disconnect(ws, timeline_id)

    def broadcast_sync(self, timeline_id: str, message: dict[str, Any]) -> None:
        """Thread-safe synchronous helper to schedule broadcast on event loop."""
        try:
            asyncio.get_running_loop()
            asyncio.create_task(self.broadcast(timeline_id, message))
        except RuntimeError:
            if self._loop and self._loop.is_running():
                asyncio.run_coroutine_threadsafe(self.broadcast(timeline_id, message), self._loop)


timeline_manager = TimelineConnectionManager()


@router.websocket("/ws/timelines/{id}")
async def timeline_live_events(websocket: WebSocket, id: str) -> None:
    """WebSocket endpoint pushing real-time operation and progress events for a timeline."""
    await timeline_manager.connect(websocket, id)
    # Send connection acknowledgment
    await websocket.send_json(
        {
            "event": "CONNECTED",
            "timeline_id": id,
            "message": f"Subscribed to live events for timeline '{id}'",
        }
    )
    try:
        while True:
            # Keep connection open; receive optional heartbeats or ping messages
            data = await websocket.receive_text()
            if data.lower() == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        timeline_manager.disconnect(websocket, id)
    except Exception as exc:
        logger.warning("WebSocket exception for timeline %s: %s", id, exc)
        timeline_manager.disconnect(websocket, id)
