from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, String, Integer, DateTime, Boolean, Numeric, JSON, func
import uuid

Base = declarative_base()
# =============================================================================
# DATABASE MODELS
# =============================================================================

class Metric(Base):
    __tablename__ = "metrics_new"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    metric_name = Column(String, nullable=False)
    metric_type = Column(String, nullable=False)  # counter, gauge, histogram, summary
    value = Column(Numeric, nullable=False)
    labels = Column(JSON, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    tenant_id = Column(String, nullable=True)
    service_name = Column(String, nullable=True)


class Monitor(Base):
    __tablename__ = "monitors_new"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    monitor_name = Column(String, nullable=False)
    monitor_type = Column(String, nullable=False)  # health, performance, error_rate
    target_service = Column(String, nullable=False)
    target_endpoint = Column(String, nullable=False)
    check_interval_seconds = Column(Integer, nullable=False, default=60)
    timeout_seconds = Column(Integer, nullable=False, default=30)
    threshold_value = Column(Numeric, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    last_check = Column(DateTime(timezone=True), nullable=True)
    last_status = Column(String, nullable=True)
    # metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())