import uuid
from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import AggregateType, EventType
from app.models.event_store import Event


class EventRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def append(
        self,
        aggregate_type: AggregateType,
        aggregate_id: uuid.UUID,
        event_type: EventType,
        event_data: dict,
        metadata: dict | None = None,
    ) -> Event:
        """Append a new event to the event store."""
        # Get next sequence number for this aggregate
        stmt = select(func.coalesce(func.max(Event.sequence_number), 0)).where(
            Event.aggregate_id == aggregate_id
        )
        result = await self.session.execute(stmt)
        next_seq = result.scalar_one() + 1

        event = Event(
            aggregate_type=aggregate_type.value,
            aggregate_id=aggregate_id,
            event_type=event_type.value,
            event_data=event_data,
            metadata_=metadata or {},
            sequence_number=next_seq,
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def get_by_aggregate(
        self, aggregate_id: uuid.UUID, since_sequence: int = 0
    ) -> list[Event]:
        """Get all events for an aggregate, optionally since a sequence number."""
        stmt = (
            select(Event)
            .where(
                Event.aggregate_id == aggregate_id,
                Event.sequence_number > since_sequence,
            )
            .order_by(Event.sequence_number)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_correlation_id(self, correlation_id: str) -> list[Event]:
        """Get all events linked by a correlation_id in metadata."""
        stmt = (
            select(Event)
            .where(Event.metadata_["correlation_id"].astext == correlation_id)
            .order_by(Event.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_type(
        self,
        event_type: EventType,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[Event]:
        """Get events by type, optionally filtered by time."""
        stmt = select(Event).where(Event.event_type == event_type.value)
        if since:
            stmt = stmt.where(Event.created_at >= since)
        stmt = stmt.order_by(Event.created_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
