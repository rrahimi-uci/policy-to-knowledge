"""
WebSocket handler for real-time pipeline log streaming.
"""

import asyncio
import json
from collections import defaultdict
from typing import Dict, Set

from fastapi import WebSocket, WebSocketDisconnect

# run_id → set of connected websockets
_subscribers: Dict[str, Set[WebSocket]] = defaultdict(set)


async def broadcast(run_id: str, payload: dict):
    """Called by pipeline_runner to fan out to subscribers."""
    dead = set()
    for ws in _subscribers.get(run_id, set()):
        try:
            await ws.send_text(json.dumps(payload))
        except Exception:
            dead.add(ws)
    if dead and run_id in _subscribers:
        _subscribers[run_id] -= dead


async def ws_pipeline(websocket: WebSocket, run_id: str):
    """WebSocket endpoint: /ws/pipeline/{run_id}"""
    await websocket.accept()
    _subscribers[run_id].add(websocket)
    try:
        while True:
            # Keep alive; client can send pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _subscribers[run_id].discard(websocket)
        if not _subscribers[run_id]:
            del _subscribers[run_id]
