# ---- Background Tasks ----
from typing import Dict, Any
import json
import os
import pandas as pd
from datetime import datetime, timezone

from services.reports.models import ReportJob
from services.reports.repositories.db_config import SessionLocal
from services.reports.repositories.report_generator_saga import ReportGenerator
from services.reports.utils.report_enums import ReportType, ReportFormat, ReportStatus
from ..utils.reports_logger import logger


async def generate_report_background(job_id: str, report_type: str, parameters: Dict[str, Any], format: ReportFormat,
                                     cache_ttl_minutes: int):
    """Background task to generate reports"""
    try:
        with SessionLocal() as db:
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
            job = db.query(ReportJob).filter(ReportJob.id == job_id).first()
            if job:
                job.status = ReportStatus.COMPLETED
                job.file_path = file_path
                job.completed_at = datetime.now(timezone.utc)
                db.commit()

            logger.info("Report generation completed", job_id=job_id, report_type=report_type)

    except Exception as e:
        logger.error("Report generation failed", job_id=job_id, error=str(e))

        # Update job status to failed
        try:
            with SessionLocal() as db:
                job = db.query(ReportJob).filter(ReportJob.id == job_id).first()
                if job:
                    job.status = ReportStatus.FAILED
                    job.error_message = str(e)
                    job.completed_at = datetime.now(timezone.utc)
                    db.commit()
        except Exception:
            pass