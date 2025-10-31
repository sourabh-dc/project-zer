# ---- Background Tasks ----
import io
from datetime import datetime, timezone, timedelta
from typing import Dict, Any
import json
import os
import pandas as pd
from fastapi import BackgroundTasks, HTTPException

from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from services.reports.repositories.report_generator_saga import ReportGenerator
from services.reports.utils.report_enums import ReportType, ReportFormat, ReportStatus
from ..repositories.database_ops import update_report_job_status, create_report_job, get_report_job
from ..schemas import ReportRequest, ReportResponse
from ..utils.metrics import report_requests_total
from ..utils.reports_logger import logger


async def generate_report_background(job_id: str, report_type: str, parameters: Dict[str, Any], format: ReportFormat,
                                     cache_ttl_minutes: int, db: Session):
    """Background task to generate reports"""
    try:
        generator = ReportGenerator(db)

        # Generate report data based on type
        if report_type == ReportType.SALES_ANALYTICS:
            data = await generator.generate_sales_analytics(parameters)
        elif report_type == ReportType.INVENTORY_ANALYTICS:
            data = await generator.generate_inventory_analytics(parameters)
        elif report_type == ReportType.CUSTOMER_ANALYTICS:
            data = await generator.generate_customer_analytics(parameters)
        elif report_type == ReportType.OPERATIONAL_ANALYTICS:
            data = await generator.generate_operational_analytics(parameters)
        else:
            raise ValueError(f"Unsupported report type: {report_type}")

        # Save report data to file
        file_path = f"/tmp/reports/{job_id}.{format}"
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        if format == ReportFormat.JSON:
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=2, default=str)
        elif format == ReportFormat.CSV:
            # Convert to CSV format (simplified)
            df = pd.json_normalize(data)
            df.to_csv(file_path, index=False)

        # Update job status
        update_report_job_status(db=db, job_id=job_id, file_path=file_path)

        logger.info("Report generation completed", job_id=job_id, report_type=report_type)

    except Exception as e:
        logger.error("Report generation failed", job_id=job_id, error=str(e))

        # Update job status to failed
        try:
            update_report_job_status(db=db, job_id=job_id, status=ReportStatus.FAILED, error_message=str(e))
        except Exception:
            pass


async def generate_report(request: ReportRequest, background_tasks: BackgroundTasks, db: Session):
    """Generate a new report"""
    try:
        job_id = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{request.report_type}"

        # Check cache first
        cache_key = f"{request.tenant_id}:{request.report_type}:{hash(str(request.parameters))}"

        # Create report job
        create_report_job(job_id=job_id, request=request, db=db)

        # Start background report generation
        background_tasks.add_task(
            generate_report_background,
            job_id,
            request.report_type,
            request.parameters,
            request.format,
            request.cache_ttl_minutes,
            db
        )

        report_requests_total.labels(report_type=request.report_type, status="initiated").inc()

        return ReportResponse(
            job_id=job_id,
            status=ReportStatus.GENERATING,
            message="Report generation initiated",
            estimated_completion=datetime.now(timezone.utc) + timedelta(minutes=5)
        )

    except Exception as e:
        logger.error("Failed to initiate report generation", error=str(e))
        report_requests_total.labels(report_type=request.report_type, status="failed").inc()
        raise HTTPException(status_code=500, detail=f"Failed to generate report: {str(e)}")

async def fetch_report_status(job_id: str, db: Session):
    """Get report generation status"""
    try:
        job = get_report_job(db=db, job_id=job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Report job not found")

        return {
            "job_id": job.id,
            "status": job.status,
            "created_at": job.created_at,
            "completed_at": job.completed_at,
            "error_message": job.error_message,
            "file_path": job.file_path
        }
    except Exception as e:
        logger.error("Failed to get report status", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


async def download_report(job_id: str, db: Session):
    """Download completed report"""
    try:
        job = get_report_job(db=db, job_id=job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Report job not found")

        if job.status != ReportStatus.COMPLETED:
            raise HTTPException(status_code=400, detail="Report not ready for download")

        if not job.file_path or not os.path.exists(job.file_path):
            raise HTTPException(status_code=404, detail="Report file not found")

        # Return file based on format
        with open(job.file_path, 'rb') as f:
            content = f.read()

        return StreamingResponse(
            io.BytesIO(content),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename={job.report_name}.{job.parameters.get('format', 'json')}"}
        )

    except Exception as e:
        logger.error("Failed to download report", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))