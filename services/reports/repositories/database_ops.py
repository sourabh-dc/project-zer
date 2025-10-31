import uuid
from datetime import datetime, timezone, timedelta

from fastapi import HTTPException

from services.reports.models import ReportJob, Dashboard, DashboardAccess, DashboardDataRefresh
from services.reports.schemas import DashboardResponse, DashboardCreateRequest
from services.reports.utils.report_enums import ReportStatus
from services.reports.utils.reports_logger import logger


def update_report_job_status(db, job_id: str, file_path: str = None, status: ReportStatus = ReportStatus.COMPLETED,
                                   error_message: str = None):
    """Update the status of a report job in the database."""
    job = db.query(ReportJob).filter(ReportJob.id == job_id).first()
    if job:
        job.status = status
        job.file_path = file_path
        job.error_message = error_message
        job.completed_at = datetime.now(timezone.utc)
        db.commit()

def create_report_job(db, job_id, request):
    """Create a new report job in the database."""
    job = ReportJob(
        id=job_id,
        tenant_id=request.tenant_id,
        user_id=request.user_id,
        report_type=request.report_type,
        report_name=request.report_name,
        parameters=request.parameters,
        status=ReportStatus.GENERATING,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24)
    )
    db.add(job)
    db.commit()
    return job

def get_report_job(db, job_id: str):
    """Retrieve a report job from the database."""
    return db.query(ReportJob).filter(ReportJob.id == job_id).first()

def create_dashboard_db(db, tenant_id: str, user_id: str, request: DashboardCreateRequest) -> DashboardResponse:
    start_time = datetime.now()
    # Check if dashboard name already exists for tenant
    existing = db.query(Dashboard).filter(
        Dashboard.tenant_id == tenant_id,
        Dashboard.name == request.name
    ).first()

    if existing:
        raise HTTPException(status_code=409, detail="Dashboard name already exists")

    # Create dashboard
    dashboard_id = str(uuid.uuid4())
    dashboard = Dashboard(
        dashboard_id=dashboard_id,
        tenant_id=tenant_id,
        name=request.name,
        description=request.description,
        dashboard_type=request.dashboard_type.value,
        powerbi_workspace_id=request.powerbi_workspace_id,
        powerbi_report_id=request.powerbi_report_id,
        powerbi_dataset_id=request.powerbi_dataset_id,
        embed_config=request.embed_config,
        data_sources=request.data_sources,
        refresh_schedule=request.refresh_schedule,
        filters=request.filters,
        is_public=request.is_public
    )

    db.add(dashboard)

    # Create default access for creator
    access_id = str(uuid.uuid4())
    access = DashboardAccess(
        id=access_id,
        dashboard_id=dashboard_id,
        user_id=user_id,
        permissions=["read", "write", "admin"]  # Full access for creator
    )
    db.add(access)

    # Create initial data refresh record
    refresh_id = str(uuid.uuid4())
    refresh = DashboardDataRefresh(
        id=refresh_id,
        dashboard_id=dashboard_id,
        status="pending"
    )
    db.add(refresh)

    db.commit()

    duration = (datetime.now() - start_time).total_seconds()
    logger.info(f"Dashboard created: {dashboard_id} for tenant {tenant_id}")

    return DashboardResponse(
        dashboard_id=dashboard_id,
        name=request.name,
        description=request.description,
        dashboard_type=request.dashboard_type,
        powerbi_workspace_id=request.powerbi_workspace_id,
        powerbi_report_id=request.powerbi_report_id,
        powerbi_dataset_id=request.powerbi_dataset_id,
        embed_config=request.embed_config,
        data_sources=request.data_sources,
        refresh_schedule=request.refresh_schedule,
        filters=request.filters,
        is_public=request.is_public,
        created_at=dashboard.created_at,
        updated_at=dashboard.updated_at
    )

def list_dashboards_db(db, tenant_id: str, dashboard_type):
    query = db.query(Dashboard).filter(
        Dashboard.tenant_id == tenant_id
    )

    if dashboard_type:
        query = query.filter(Dashboard.dashboard_type == dashboard_type)

    dashboards = query.all()
    return dashboards

def get_dashboard_db(db, dashboard_id: str, tenant_id: str):
    dashboard = db.query(Dashboard).filter(
        Dashboard.dashboard_id == dashboard_id,
        Dashboard.tenant_id == tenant_id
    ).first()

    return dashboard

def get_dashboard_refresh(db, dashboard_id):
    refresh = db.query(DashboardDataRefresh).filter(
        DashboardDataRefresh.dashboard_id == dashboard_id
    ).first()
    return refresh

def update_dashboard_refresh(db, refresh, status, last_refresh=None, error_message=None):
    refresh.status = status
    refresh.last_refresh = last_refresh
    refresh.error_message = error_message
    refresh.updated_at = datetime.now(timezone.utc)
    db.commit()