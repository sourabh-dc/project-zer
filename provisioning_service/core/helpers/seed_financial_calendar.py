"""
seed_financial_calendar.py
--------------------------
Auto-seed a default FinancialCalendar + active FinancialYear + monthly
FinancialPeriods when a new tenant is created, so cost-centre budgets
work out of the box.
"""
import uuid
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from provisioning_service.Models import FinancialCalendar, FinancialYear, FinancialPeriod
from provisioning_service.core.period_calculator import build_financial_period_rows
from provisioning_service.utils.logger import logger


def seed_default_financial_calendar(
    db: Session,
    tenant_id,
    currency: str = "GBP",
    created_by=None,
    start_month: int = 1,
) -> Optional[FinancialYear]:
    """Create the default calendar + current active FY + monthly periods.

    Idempotent: skips if the tenant already has a default calendar.
    Returns the active FinancialYear, or None if already seeded.
    """
    if isinstance(tenant_id, str):
        tenant_id = uuid.UUID(tenant_id)

    existing = db.query(FinancialCalendar).filter(
        FinancialCalendar.tenant_id == tenant_id,
        FinancialCalendar.is_default == True,
    ).first()
    if existing:
        return None

    today = date.today()
    fy_start = date(today.year, start_month, 1)
    if today < fy_start:
        fy_start = date(today.year - 1, start_month, 1)
    fy_end = date(fy_start.year + 1, start_month, 1) - timedelta(days=1)
    label = f"FY{fy_start.year}" if start_month == 1 else f"FY{fy_start.year}/{(fy_start.year + 1) % 100:02d}"

    cal = FinancialCalendar(
        calendar_id=uuid.uuid4(),
        tenant_id=tenant_id,
        name="Default Calendar",
        description="Auto-created on tenant creation",
        calendar_type="gregorian",
        start_month=start_month,
        currency=currency or "GBP",
        is_active=True,
        is_default=True,
        created_by=created_by,
    )
    db.add(cal)

    year = FinancialYear(
        year_id=uuid.uuid4(),
        calendar_id=cal.calendar_id,
        tenant_id=tenant_id,
        label=label,
        start_date=fy_start,
        end_date=fy_end,
        year_type="full",
        status="active",
        created_by=created_by,
    )
    db.add(year)
    db.flush()

    rows = build_financial_period_rows(
        tenant_id=tenant_id,
        year_id=year.year_id,
        calendar_id=cal.calendar_id,
        calendar_type="gregorian",
        start_date=fy_start,
        end_date=fy_end,
        period_type="month",
    )
    for row in rows:
        db.add(FinancialPeriod(**row))

    db.commit()
    logger.info(
        f"Seeded default financial calendar for tenant {tenant_id}: "
        f"{label} ({fy_start} → {fy_end}), {len(rows)} monthly periods"
    )
    return year
