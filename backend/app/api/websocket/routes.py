from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.api.websocket.ws_manager import manager

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    channels: str = Query(default="portfolio,positions,signals,risk,system"),
):
    """WebSocket endpoint for real-time updates.

    Connect with: ws://localhost:8000/ws?channels=portfolio,positions,signals
    """
    channel_list = [c.strip() for c in channels.split(",") if c.strip()]
    await manager.connect(websocket, channel_list)

    try:
        while True:
            # Keep connection alive, handle client messages if needed
            data = await websocket.receive_text()
            # Client can send subscription changes
            if data.startswith("subscribe:"):
                new_channels = data[10:].split(",")
                for ch in new_channels:
                    ch = ch.strip()
                    if ch:
                        manager._subscriptions[ch].add(websocket)
            elif data.startswith("unsubscribe:"):
                old_channels = data[12:].split(",")
                for ch in old_channels:
                    ch = ch.strip()
                    if ch in manager._subscriptions:
                        manager._subscriptions[ch].discard(websocket)
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
