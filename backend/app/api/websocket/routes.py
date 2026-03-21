import secrets

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.api.websocket.ws_manager import manager
from app.config import settings
from app.core.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    channels: str = Query(default="portfolio,positions,signals,risk,system"),
    token: str = Query(default=""),
):
    """WebSocket endpoint for real-time updates.

    Connect with: ws://localhost:8000/ws?channels=portfolio,positions&token=YOUR_API_KEY
    """
    # Must accept before we can close with a code
    await websocket.accept()

    # Authenticate WebSocket connection
    if settings.api_key:
        if not token or not secrets.compare_digest(token, settings.api_key):
            await websocket.close(code=1008, reason="Unauthorized")
            logger.warning("ws_auth_failed", reason="invalid_token")
            return
    elif not settings.debug:
        # No API key configured + not in debug mode = reject
        await websocket.close(code=1008, reason="API key not configured")
        return

    channel_list = [c.strip() for c in channels.split(",") if c.strip()]
    # Re-register with manager (already accepted)
    await manager.connect(websocket, channel_list, already_accepted=True)

    try:
        while True:
            data = await websocket.receive_text()
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
