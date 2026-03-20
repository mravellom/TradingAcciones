from datetime import datetime
from typing import Any

from pydantic import BaseModel


class WSMessage(BaseModel):
    """WebSocket message envelope."""

    channel: str
    event: str
    data: Any
    timestamp: datetime
