# =============================================================================
# DATABASE MODELS
# =============================================================================
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, String, Integer, DateTime, Text, JSON, func
import uuid


Base = declarative_base()

class ServiceHealth(Base):
    __tablename__ = "service_health_new"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    service_name = Column(String, nullable=False)
    status = Column(String, nullable=False)  # healthy, unhealthy, degraded
    response_time_ms = Column(Integer, nullable=True)
    last_check = Column(DateTime(timezone=True), server_default=func.now())
    error_message = Column(Text, nullable=True)
    meta = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Alert(Base):
    __tablename__ = "alerts_new"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    service_name = Column(String, nullable=False)
    alert_type = Column(String, nullable=False)  # health_check, performance, error_rate
    severity = Column(String, nullable=False)  # critical, warning, info
    message = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="active")  # active, resolved, acknowledged
    metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)