from sqlalchemy import Column, String, Integer, DateTime, JSON, Text, func
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class UsageEvent(Base):
    __tablename__ = "usage_events_new"

    event_id = Column(String(255), primary_key=True)
    tenant_id = Column(String(255), nullable=False)
    user_id = Column(String(255), nullable=True)
    meter_code = Column(String(100), nullable=False)
    quantity = Column(Integer, default=1)
    metadata_json = Column(JSON, nullable=True)
    recorded_at = Column(DateTime(timezone=True), server_default=func.now())


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    event_id = Column(String(255), primary_key=True)
    event_type = Column(String(100), nullable=False, index=True)
    aggregate_id = Column(String(255), nullable=False)
    event_data = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    retry_count = Column(Integer, nullable=False, default=0)
    published_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"
    log_id = Column(String(255), primary_key=True)
    aggregate_id = Column(String(255), nullable=False, index=True)
    user_id = Column(String(255))
    action = Column(String(100), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String(255), nullable=False)
    changes = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())