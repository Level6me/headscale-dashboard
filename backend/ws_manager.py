import json
import logging
import asyncio
from typing import List, Any, Dict
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("HeadscaleDashboard.WS")

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket client connected. Total clients: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket client disconnected. Remaining: {len(self.active_connections)}")

    async def broadcast(self, event_type: str, data: Any):
        if not self.active_connections:
            return
        payload = json.dumps({
            "type": event_type,
            "data": data
        }, ensure_ascii=False)

        to_remove = []
        for connection in self.active_connections:
            try:
                await connection.send_text(payload)
            except Exception as e:
                logger.warning(f"Failed to send to WS client: {e}")
                to_remove.append(connection)

        for dead_conn in to_remove:
            self.disconnect(dead_conn)

    def broadcast_sync(self, event_type: str, data: Any):
        """同步调用广播，调度到事件循环中执行"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(self.broadcast(event_type, data), loop)
        except Exception:
            pass

ws_manager = ConnectionManager()
