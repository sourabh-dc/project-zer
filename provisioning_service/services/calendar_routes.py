"""
calendar_routes.py
------------------
CRUD for FinancialCalendar, FinancialYear, and FinancialPeriod.
Includes auto-generation of periods from a financial year.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from provisioning_service.Models import FinancialCalendar, FinancialYear, FinancialPeriod
from provisioning_service.Schemas import (
    FinancialCalendarCreate, FinancialCalendarUpdate,
    FinancialYearCreate, PeriodGenerationRequest, FinancialPeriodCreate,
)
from provisioning_service.core.db_config import get_db
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.core.period_calculator import build_financial_period_rows
from provisioning_service.core.helpers.outbox_helpers import create_outbox_event
from provisioning_service.utils.logger import logger

router = APIRouter(prefix="/financial-calendars", tags=["Financial Calendars"])


# =============================================================================
# CALENDAR CRUD
# =============================================================================

@router.post("", status_code=201)
async def create_calendar(
    req: FinancialCalendarCreate,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
):
    tenant_id = uuid.UUID(ctx["tenant_id"] if isinstance(ctx, dict) else str(ctx.tenant_id))
    user_id   = uuid.UUID(ctx["user_id"] if isinstance(ctx, dict) else str(ctx.user_id))

    existing = db.query(FinancialCalendar).filter(
        FinancialCalendar.tenant_id == tenant_id,
        FinancialCalendar.name == req.name,
        FinancialCalendar.is_active == True,
    ).first()
    if existing:
        raise HTTPException(409, "A calendar with this name already exists")

    # If this is set as default, unset others
    if req.is_default:
        db.query(FinancialCalendar).filter(
            FinancialCalendar.tenant_id == tenant_id,
            FinancialCalendar.is_default == True,
        ).update({"is_default": False})

    cal = FinancialCalendar(
        calendar_id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=req.name,
        description=req.description,
        calendar_type=req.calendar_type,
        start_month=req.start_month,
        currency=req.currency or "GBP",
        is_active=True,
        is_default=req.is_default,
        created_by=user_id,
    )
    db.add(cal)
    db.commit()
    db.refresh(cal)

    try:
        create_outbox_event(db, tenant_id, "financial_calendar.created",
                            {"calendar_id": str(cal.calendar_id), "name": cal.name})
        db.commit()
    except Exception as e:
        logger.warning(f"Outbox failed for financial_calendar.created: {e}")

    return _calendar_dict(cal)


@router.get("")
async def list_calendars(
    active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
):
    tenant_id = uuid.UUID(ctx["tenant_id"] if isinstance(ctx, dict) else str(ctx.tenant_id))
    q = db.query(FinancialCalendar).filter(FinancialCalendar.tenant_id == tenant_id)
    if active is not None:
        q = q.filter(FinancialCalendar.is_active == active)
    return {"calendars": [_calendar_dict(c) for c in q.order_by(FinancialCalendar.name).all()]}


@router.get("/{calendar_id}")
async def get_calendar(
    calendar_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
):
    tenant_id = uuid.UUID(ctx["tenant_id"] if isinstance(ctx, dict) else str(ctx.tenant_id))
    cal = _get_calendar_or_404(db, calendar_id, tenant_id)
    return _calendar_dict(cal)


@router.put("/{calendar_id}")
async def update_calendar(
    calendar_id: str,
    req: FinancialCalendarUpdate,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
):
    tenant_id = uuid.UUID(ctx["tenant_id"] if isinstance(ctx, dict) else str(ctx.tenant_id))
    cal = _get_calendar_or_404(db, calendar_id, tenant_id)

    if req.name is not None:
        cal.name = req.name
    if req.description is not None:
        cal.description = req.description
    if req.is_active is not None:
        cal.is_active = req.is_active
    if req.is_default is not None:
        if req.is_default:
            db.query(FinancialCalendar).filter(
                FinancialCalendar.tenant_id == tenant_id,
                FinancialCalendar.is_default == True,
            ).update({"is_default": False})
        cal.is_default = req.is_default

    cal.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(cal)

    try:
        create_outbox_event(db, tenant_id, "financial_calendar.updated",
                            {"calendar_id": calendar_id})
        db.commit()
    except Exception as e:
        logger.warning(f"Outbox failed for financial_calendar.updated: {e}")

    return _calendar_dict(cal)


@router.delete("/{calendar_id}", status_code=204)
async def delete_calendar(
    calendar_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
):
    tenant_id = uuid.UUID(ctx["tenant_id"] if isinstance(ctx, dict) else str(ctx.tenant_id))
    cal = _get_calendar_or_404(db, calendar_id, tenant_id)

    has_active_years = db.query(FinancialYear).filter(
        FinancialYear.calendar_id == cal.calendar_id,
        FinancialYear.status == "active",
    ).count()
    if has_active_years:
        raise HTTPException(400, "Cannot delete a calendar with active financial years")

    cal.is_active = False
    cal.updated_at = datetime.now(timezone.utc)
    db.commit()

    try:
        create_outbox_event(db, tenant_id, "financial_calendar.deleted", {"calendar_id": calendar_id})
        db.commit()
    except Exception as e:
        logger.warning(f"Outbox failed for financial_calendar.deleted: {e}")


# =============================================================================
# FINANCIAL YEAR CRUD
# =============================================================================

@router.post("/{calendar_id}/years", status_code=201)
async def create_year(
    calendar_id: str,
    req: FinancialYearCreate,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
):
    tenant_id = uuid.UUID(ctx["tenant_id"] if isinstance(ctx, dict) else str(ctx.tenant_id))
    user_id   = uuid.UUID(ctx["user_id"] if isinstance(ctx, dict) else str(ctx.user_id))
    cal = _get_calendar_or_404(db, calendar_id, tenant_id)

    if req.start_date >= req.end_date:
        raise HTTPException(400, "end_date must be after start_date")

    existing = db.query(FinancialYear).filter(
        FinancialYear.calendar_id == cal.calendar_id,
        FinancialYear.label == req.label,
    ).first()
    if existing:
        raise HTTPException(409, f"Year '{req.label}' already exists for this calendar")

    year = FinancialYear(
        year_id=uuid.uuid4(),
        calendar_id=cal.calendar_id,
        tenant_id=tenant_id,
        label=req.label,
        start_date=req.start_date,
        end_date=req.end_date,
        year_type=req.year_type,
        status="draft",
        total_budget_minor=req.total_budget_minor,
        notes=req.notes,
        created_by=user_id,
    )
    db.add(year)
    db.commit()
    db.refresh(year)

    try:
        create_outbox_event(db, tenant_id, "financial_year.created",
                            {"year_id": str(year.year_id), "label": year.label})
        db.commit()
    except Exception as e:
        logger.warning(f"Outbox failed for financial_year.created: {e}")

    return _year_dict(year)


@router.get("/{calendar_id}/years")
async def list_years(
    calendar_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
):
    tenant_id = uuid.UUID(ctx["tenant_id"] if isinstance(ctx, dict) else str(ctx.tenant_id))
    cal = _get_calendar_or_404(db, calendar_id, tenant_id)
    years = db.query(FinancialYear).filter(
        FinancialYear.calendar_id == cal.calendar_id,
    ).order_by(FinancialYear.start_date).all()
    return {"years": [_year_dict(y) for y in years]}


@router.put("/{calendar_id}/years/{year_id}/activate", status_code=200)
async def activate_year(
    calendar_id: str,
    year_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
):
    tenant_id = uuid.UUID(ctx["tenant_id"] if isinstance(ctx, dict) else str(ctx.tenant_id))
    cal = _get_calendar_or_404(db, calendar_id, tenant_id)
    year = _get_year_or_404(db, year_id, cal.calendar_id)
    if year.status == "active":
        raise HTTPException(400, "Year is already active")
    year.status = "active"
    db.commit()

    try:
        create_outbox_event(db, tenant_id, "financial_year.activated", {"year_id": year_id})
        db.commit()
    except Exception as e:
        logger.warning(f"Outbox failed for financial_year.activated: {e}")

    return {"year_id": year_id, "status": "active"}


@router.put("/{calendar_id}/years/{year_id}/close", status_code=200)
async def close_year(
    calendar_id: str,
    year_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
):
    tenant_id = uuid.UUID(ctx["tenant_id"] if isinstance(ctx, dict) else str(ctx.tenant_id))
    cal = _get_calendar_or_404(db, calendar_id, tenant_id)
    year = _get_year_or_404(db, year_id, cal.calendar_id)
    year.status = "closed"
    db.commit()

    try:
        create_outbox_event(db, tenant_id, "financial_year.closed", {"year_id": year_id})
        db.commit()
    except Exception as e:
        logger.warning(f"Outbox failed for financial_year.closed: {e}")

    return {"year_id": year_id, "status": "closed"}


# =============================================================================
# PERIOD GENERATION & CRUD
# =============================================================================

@router.post("/{calendar_id}/years/{year_id}/generate-periods", status_code=201)
async def generate_periods(
    calendar_id: str,
    year_id: str,
    req: PeriodGenerationRequest,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
):
    """Auto-generate FinancialPeriod rows for a year using the calendar's type."""
    tenant_id = uuid.UUID(ctx["tenant_id"] if isinstance(ctx, dict) else str(ctx.tenant_id))
    cal  = _get_calendar_or_404(db, calendar_id, tenant_id)
    year = _get_year_or_404(db, year_id, cal.calendar_id)

    # Delete any existing periods for this year first
    db.query(FinancialPeriod).filter(FinancialPeriod.year_id == year.year_id).delete()

    if cal.calendar_type == "custom":
        raise HTTPException(400, "Use POST /periods to manually define periods for custom calendars")

    rows = build_financial_period_rows(
        tenant_id=tenant_id,
        year_id=year.year_id,
        calendar_id=cal.calendar_id,
        calendar_type=cal.calendar_type,
        start_date=year.start_date,
        end_date=year.end_date,
        period_type=req.period_type,
    )

    for row in rows:
        db.add(FinancialPeriod(**row))
    db.commit()

    try:
        create_outbox_event(db, tenant_id, "financial_periods.generated", {
            "year_id": year_id,
            "period_count": len(rows),
        })
        db.commit()
    except Exception as e:
        logger.warning(f"Outbox failed for financial_periods.generated: {e}")

    periods = db.query(FinancialPeriod).filter(
        FinancialPeriod.year_id == year.year_id
    ).order_by(FinancialPeriod.period_number).all()

    return {
        "year_id": year_id,
        "generated": len(rows),
        "periods": [_period_dict(p) for p in periods],
    }


@router.post("/{calendar_id}/years/{year_id}/periods", status_code=201)
async def create_period(
    calendar_id: str,
    year_id: str,
    req: FinancialPeriodCreate,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
):
    """Manually create a period (for custom calendars)."""
    tenant_id = uuid.UUID(ctx["tenant_id"] if isinstance(ctx, dict) else str(ctx.tenant_id))
    cal  = _get_calendar_or_404(db, calendar_id, tenant_id)
    year = _get_year_or_404(db, year_id, cal.calendar_id)

    existing = db.query(FinancialPeriod).filter(
        FinancialPeriod.year_id == year.year_id,
        FinancialPeriod.period_number == req.period_number,
    ).first()
    if existing:
        raise HTTPException(409, f"Period {req.period_number} already exists for this year")

    period = FinancialPeriod(
        period_id=uuid.uuid4(),
        year_id=year.year_id,
        calendar_id=cal.calendar_id,
        tenant_id=tenant_id,
        period_number=req.period_number,
        label=req.label,
        period_type=req.period_type,
        start_date=req.start_date,
        end_date=req.end_date,
    )
    db.add(period)
    db.commit()
    db.refresh(period)

    try:
        create_outbox_event(db, tenant_id, "financial_period.created", {
            "period_id": str(period.period_id),
            "year_id": year_id,
            "period_number": period.period_number,
        })
        db.commit()
    except Exception as e:
        logger.warning(f"Outbox failed for financial_period.created: {e}")

    return _period_dict(period)


@router.get("/{calendar_id}/years/{year_id}/periods")
async def list_periods(
    calendar_id: str,
    year_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
):
    tenant_id = uuid.UUID(ctx["tenant_id"] if isinstance(ctx, dict) else str(ctx.tenant_id))
    cal  = _get_calendar_or_404(db, calendar_id, tenant_id)
    year = _get_year_or_404(db, year_id, cal.calendar_id)
    periods = db.query(FinancialPeriod).filter(
        FinancialPeriod.year_id == year.year_id,
    ).order_by(FinancialPeriod.period_number).all()
    return {"periods": [_period_dict(p) for p in periods]}


# =============================================================================
# Internal helpers
# =============================================================================

def _get_calendar_or_404(db, calendar_id, tenant_id):
    try:
        cid = uuid.UUID(calendar_id)
    except ValueError:
        raise HTTPException(400, "Invalid calendar_id")
    cal = db.query(FinancialCalendar).filter(
        FinancialCalendar.calendar_id == cid,
        FinancialCalendar.tenant_id == tenant_id,
    ).first()
    if not cal:
        raise HTTPException(404, "Financial calendar not found")
    return cal


def _get_year_or_404(db, year_id, calendar_id):
    try:
        yid = uuid.UUID(year_id)
    except ValueError:
        raise HTTPException(400, "Invalid year_id")
    year = db.query(FinancialYear).filter(
        FinancialYear.year_id == yid,
        FinancialYear.calendar_id == calendar_id,
    ).first()
    if not year:
        raise HTTPException(404, "Financial year not found")
    return year


def _calendar_dict(cal):
    return {
        "calendar_id": str(cal.calendar_id),
        "name": cal.name,
        "description": cal.description,
        "calendar_type": cal.calendar_type,
        "start_month": cal.start_month,
        "currency": cal.currency,
        "is_active": cal.is_active,
        "is_default": cal.is_default,
        "created_at": cal.created_at.isoformat() if cal.created_at else None,
    }


def _year_dict(year):
    return {
        "year_id": str(year.year_id),
        "calendar_id": str(year.calendar_id),
        "label": year.label,
        "start_date": str(year.start_date),
        "end_date": str(year.end_date),
        "year_type": year.year_type,
        "status": year.status,
        "total_budget_minor": year.total_budget_minor,
    }


def _period_dict(period):
    return {
        "period_id": str(period.period_id),
        "year_id": str(period.year_id),
        "period_number": period.period_number,
        "label": period.label,
        "period_type": period.period_type,
        "start_date": str(period.start_date),
        "end_date": str(period.end_date),
    }

