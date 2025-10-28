# ---- Pydantic Models ----
from datetime import datetime
from typing import Optional, Dict, Any, List

from pydantic import BaseModel, Field

from services.reports.utils.report_enums import ReportType, ReportFormat, ReportStatus, DashboardType


class ReportRequest(BaseModel):
    tenant_id: str
    user_id: Optional[str] = None
    report_type: ReportType
    report_name: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    format: ReportFormat = ReportFormat.JSON
    cache_ttl_minutes: Optional[int] = 60

class ReportResponse(BaseModel):
    job_id: str
    status: ReportStatus
    message: str
    estimated_completion: Optional[datetime] = None

class ReportData(BaseModel):
    report_id: str
    report_type: ReportType
    data: Dict[str, Any]
    metadata: Dict[str, Any]
    generated_at: datetime
    cache_hit: bool = False

class AnalyticsQuery(BaseModel):
    tenant_id: str
    start_date: datetime
    end_date: datetime
    filters: Dict[str, Any] = Field(default_factory=dict)
    group_by: Optional[List[str]] = None
    metrics: List[str] = Field(default_factory=list)

# Phase 6: Dashboard Models for Power BI Integration
class DashboardConfig(BaseModel):
    """Dashboard configuration for Power BI"""
    name: str = Field(..., description="Dashboard name")
    description: Optional[str] = Field(None, description="Dashboard description")
    dashboard_type: DashboardType = Field(..., description="Type of dashboard")
    powerbi_workspace_id: Optional[str] = Field(None, description="Power BI workspace ID")
    powerbi_report_id: Optional[str] = Field(None, description="Power BI report ID")
    powerbi_dataset_id: Optional[str] = Field(None, description="Power BI dataset ID")
    embed_config: Dict[str, Any] = Field(default_factory=dict, description="Power BI embed configuration")
    data_sources: List[str] = Field(default_factory=list, description="Data source service names")
    refresh_schedule: Optional[str] = Field(None, description="Data refresh schedule (cron format)")
    filters: Dict[str, Any] = Field(default_factory=dict, description="Default dashboard filters")
    is_public: bool = Field(default=False, description="Whether dashboard is publicly accessible")

class DashboardResponse(BaseModel):
    """Dashboard response model"""
    dashboard_id: str
    name: str
    description: Optional[str]
    dashboard_type: DashboardType
    powerbi_workspace_id: Optional[str]
    powerbi_report_id: Optional[str]
    powerbi_dataset_id: Optional[str]
    embed_config: Dict[str, Any]
    data_sources: List[str]
    refresh_schedule: Optional[str]
    filters: Dict[str, Any]
    is_public: bool
    created_at: datetime
    updated_at: Optional[datetime]

class DashboardCreateRequest(BaseModel):
    """Dashboard creation request"""
    name: str = Field(..., description="Dashboard name")
    description: Optional[str] = Field(None, description="Dashboard description")
    dashboard_type: DashboardType = Field(..., description="Type of dashboard")
    powerbi_workspace_id: Optional[str] = Field(None, description="Power BI workspace ID")
    powerbi_report_id: Optional[str] = Field(None, description="Power BI report ID")
    powerbi_dataset_id: Optional[str] = Field(None, description="Power BI dataset ID")
    data_sources: List[str] = Field(default_factory=list, description="Data source service names")
    refresh_schedule: Optional[str] = Field(None, description="Data refresh schedule")
    filters: Dict[str, Any] = Field(default_factory=dict, description="Default dashboard filters")
    is_public: bool = Field(default=False, description="Whether dashboard is publicly accessible")

class PowerBIEmbedRequest(BaseModel):
    """Power BI embed token request"""
    dashboard_id: str
    user_id: Optional[str] = None
    permissions: List[str] = Field(default_factory=list, description="User permissions for dashboard")

class PowerBIEmbedResponse(BaseModel):
    """Power BI embed response"""
    embed_token: str
    embed_url: str
    expiry: datetime
    permissions: List[str]

class DashboardDataRefresh(BaseModel):
    """Dashboard data refresh status"""
    dashboard_id: str
    status: str  # 'running', 'completed', 'failed'
    last_refresh: Optional[datetime]
    next_refresh: Optional[datetime]
    error_message: Optional[str]