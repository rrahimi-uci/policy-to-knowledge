"""
WebSocket handler for real-time impact analysis progress streaming.
"""

import asyncio
import json
from collections import defaultdict
from typing import Dict, Set

from fastapi import WebSocket, WebSocketDisconnect

# analysis_id → set of connected websockets
_subscribers: Dict[str, Set[WebSocket]] = defaultdict(set)


async def broadcast_impact(analysis_id: str, payload: dict):
    """Called by the agentic service to push step progress to clients."""
    dead = set()
    for ws in _subscribers.get(analysis_id, set()):
        try:
            await ws.send_text(json.dumps(payload))
        except Exception:
            dead.add(ws)
    if dead and analysis_id in _subscribers:
        _subscribers[analysis_id] -= dead


async def ws_impact(websocket: WebSocket, analysis_id: str):
    """WebSocket endpoint: /ws/impact/{analysis_id}"""
    await websocket.accept()
    _subscribers[analysis_id].add(websocket)
    try:
        while True:
            await websocket.receive_text()  # keep alive
    except WebSocketDisconnect:
        pass
    finally:
        _subscribers[analysis_id].discard(websocket)
        if not _subscribers[analysis_id]:
            del _subscribers[analysis_id]
