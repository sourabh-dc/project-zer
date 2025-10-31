from datetime import datetime, timezone, timedelta

from services.reports.models import ReportJob
from services.reports.utils.report_enums import ReportStatus


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