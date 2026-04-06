"""
Outbox event model — the single source of truth for the event pipeline.

Lifecycle:
    pending  →  published  →  (consumed by downstream via Service Bus)
    pending  →  failed     →  pending (retry)
    pending  →  dead_letter (max retries exhausted)

The outbox_events table is the transactional outbox. The API layer writes
business data + an outbox row in the SAME Postgres transaction, guaranteeing
at-least-once delivery.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, DateTime, Index, Integer, String, Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    # What happened
    event_type = Column(String(200), nullable=False, index=True)
    aggregate_type = Column(String(100), nullable=True, index=True)
    aggregate_id = Column(UUID(as_uuid=True), nullable=True)
    payload = Column(JSONB, nullable=False, default=dict)

    # Pipeline state
    status = Column(String(20), nullable=False, default="pending", index=True)
    topic = Column(String(100), nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=5)
    error_message = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    published_at = Column(DateTime(timezone=True), nullable=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_outbox_status_created", "status", "created_at"),
        Index("idx_outbox_tenant_type", "tenant_id", "event_type"),
    )

    def __repr__(self):
        return f"<OutboxEvent {self.event_type} id={self.id} status={self.status}>"
