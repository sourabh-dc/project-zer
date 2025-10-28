from sqlalchemy import String, Column, JSON, DateTime, Text, Integer, Boolean, func
from sqlalchemy.orm import declarative_base

from services.reports.utils.report_enums import ReportStatus

Base = declarative_base()

# ---- Database Models ----
class ReportJob(Base):
    __tablename__ = "report_jobs_new"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False)
    user_id = Column(String, nullable=True)
    report_type = Column(String, nullable=False)
    report_name = Column(String, nullable=False)
    parameters = Column(JSON, nullable=False)
    status = Column(String, nullable=False, default=ReportStatus.PENDING)
    file_path = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)


class ReportCache(Base):
    __tablename__ = "report_cache_new"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False)
    cache_key = Column(String, nullable=False, unique=True)
    report_type = Column(String, nullable=False)
    parameters_hash = Column(String, nullable=False)
    data = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)


# Phase 6: Dashboard Models for Power BI Integration
class Dashboard(Base):
    """Dashboard configuration for Power BI - Phase 6"""
    __tablename__ = "dashboards"

    dashboard_id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    dashboard_type = Column(String(50), nullable=False)
    powerbi_workspace_id = Column(String(100), nullable=True)
    powerbi_report_id = Column(String(100), nullable=True)
    powerbi_dataset_id = Column(String(100), nullable=True)
    embed_config = Column(JSON, nullable=False, default=dict)
    data_sources = Column(JSON, nullable=False, default=list)  # List of service names
    refresh_schedule = Column(String(100), nullable=True)  # Cron format
    filters = Column(JSON, nullable=False, default=dict)
    is_public = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=True)


class DashboardAccess(Base):
    """Dashboard access control - Phase 6"""
    __tablename__ = "dashboard_access"

    id = Column(String, primary_key=True)
    dashboard_id = Column(String, nullable=False)
    user_id = Column(String, nullable=True)  # null for public access
    role_id = Column(String, nullable=True)  # null for user-specific access
    permissions = Column(JSON, nullable=False, default=list)  # read, write, admin
    granted_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)


class DashboardDataRefresh(Base):
    """Dashboard data refresh tracking - Phase 6"""
    __tablename__ = "dashboard_data_refresh"

    id = Column(String, primary_key=True)
    dashboard_id = Column(String, nullable=False)
    status = Column(String(20), nullable=False, default="pending")  # pending, running, completed, failed
    last_refresh = Column(DateTime(timezone=True), nullable=True)
    next_refresh = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    refresh_duration_seconds = Column(Integer, nullable=True)
    records_processed = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=True)