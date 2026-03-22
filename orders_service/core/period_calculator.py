from datetime import date
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from orders_service.Models import FinancialCalendar, FinancialPeriod, FinancialYear


def get_current_period(db: Session, tenant_id: UUID, as_of: Optional[date] = None):
    today = as_of or date.today()
    return (
        db.query(FinancialPeriod)
        .join(FinancialYear, FinancialPeriod.year_id == FinancialYear.year_id)
        .join(FinancialCalendar, FinancialPeriod.calendar_id == FinancialCalendar.calendar_id)
        .filter(
            FinancialCalendar.tenant_id == tenant_id,
            FinancialCalendar.is_active.is_(True),
            FinancialYear.status == "active",
            FinancialPeriod.start_date <= today,
            FinancialPeriod.end_date >= today,
        )
        .order_by(FinancialCalendar.is_default.desc())
        .first()
    )

