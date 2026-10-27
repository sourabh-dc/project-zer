"""
Department reports API — KPI tiles and charts for the departments dashboard.

Data sources (shared tenant DB):
  departments  → org_units (type='department')
  headcount    → user_org_assignments (count of assigned users)
  spend        → purchase_requests (approved/po_issued) attributed to a
                 department via cost_centres.department_id
  fiscal year  → financial_years (label, e.g. "2026-27"); default = active year
  periods      → financial_periods (month periods within the year)
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from provisioning_service import Models
from provisioning_service.core.db_config import get_db
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.utils.logger import logger

router = APIRouter(prefix="/v1/reports", tags=["Reports"])

REPORT_PERMISSION = "org_units.manage"
SPEND_STATUSES = ("approved", "po_issued")   # realised spend only


# ── Helpers ─────────────────────────────────────────────────────────

def _tenant_uuid(ctx) -> uuid.UUID:
    tid = ctx.get("tenant_id")
    if not tid:
        raise HTTPException(status_code=403, detail="No tenant in token")
    return uuid.UUID(str(tid))


def _fmt_money(minor: int, currency: str = "GBP") -> str:
    symbol = {"GBP": "£", "USD": "$", "EUR": "€"}.get(currency, f"{currency} ")
    return f"{symbol}{int(round(minor / 100)):,}"


def _currency(db: Session, tenant_id: uuid.UUID) -> str:
    tenant = db.query(Models.Tenant).filter(Models.Tenant.tenant_id == tenant_id).first()
    return (tenant.default_currency or "GBP") if tenant else "GBP"


def _resolve_year(db: Session, tenant_id: uuid.UUID, fiscal_year: Optional[str]) -> Models.FinancialYear:
    """Label match → else active year → else latest. 404 when nothing found."""
    query = db.query(Models.FinancialYear).filter(Models.FinancialYear.tenant_id == tenant_id)
    if fiscal_year:
        year = query.filter(Models.FinancialYear.label == fiscal_year).first()
        if not year:
            raise HTTPException(status_code=404, detail=f"Fiscal year '{fiscal_year}' not found")
        return year
    year = query.filter(Models.FinancialYear.status == "active").order_by(
        Models.FinancialYear.start_date.desc()).first()
    if not year:
        year = query.order_by(Models.FinancialYear.start_date.desc()).first()
    if not year:
        raise HTTPException(status_code=404, detail="No financial year configured for this tenant")
    return year


def _departments(db: Session, tenant_id: uuid.UUID) -> List[Models.OrgUnit]:
    return db.query(Models.OrgUnit).filter(
        Models.OrgUnit.tenant_id == tenant_id,
        Models.OrgUnit.type == "department",
        Models.OrgUnit.status == "active",
    ).order_by(Models.OrgUnit.name).all()


def _headcount_map(db: Session, tenant_id: uuid.UUID) -> Dict[uuid.UUID, int]:
    """org_unit_id → assigned user count (departments only)."""
    rows = (
        db.query(
            Models.UserOrgAssignment.org_unit_id,
            func.count(func.distinct(Models.UserOrgAssignment.user_id)),
        )
        .join(Models.OrgUnit, Models.UserOrgAssignment.org_unit_id == Models.OrgUnit.org_unit_id)
        .filter(Models.OrgUnit.tenant_id == tenant_id, Models.OrgUnit.type == "department")
        .group_by(Models.UserOrgAssignment.org_unit_id)
        .all()
    )
    return {r[0]: int(r[1]) for r in rows}


def _spend_map(
    db: Session,
    tenant_id: uuid.UUID,
    year: Models.FinancialYear,
    period: Optional[Models.FinancialPeriod] = None,
) -> Dict[uuid.UUID, int]:
    """department org_unit_id → SUM(amount_minor) for realised spend.

    PRs link to a year/period explicitly (year_id/period_id); older rows
    may have NULL — fall back to created_at within the date range.
    """
    if period is not None:
        date_filter = or_(
            Models.PurchaseRequest.period_id == period.period_id,
            func.date(Models.PurchaseRequest.created_at).between(period.start_date, period.end_date),
        )
    else:
        date_filter = or_(
            Models.PurchaseRequest.year_id == year.year_id,
            func.date(Models.PurchaseRequest.created_at).between(year.start_date, year.end_date),
        )

    rows = (
        db.query(
            Models.CostCentre.department_id,
            func.coalesce(func.sum(Models.PurchaseRequest.amount_minor), 0),
        )
        .join(Models.PurchaseRequest,
              Models.PurchaseRequest.cost_centre_id == Models.CostCentre.cost_centre_id)
        .filter(
            Models.PurchaseRequest.tenant_id == tenant_id,
            Models.PurchaseRequest.status.in_(SPEND_STATUSES),
            Models.CostCentre.department_id.isnot(None),
            date_filter,
        )
        .group_by(Models.CostCentre.department_id)
        .all()
    )
    return {r[0]: int(r[1]) for r in rows}


def _month_periods(db: Session, tenant_id: uuid.UUID, year: Models.FinancialYear) -> List[Models.FinancialPeriod]:
    return db.query(Models.FinancialPeriod).filter(
        Models.FinancialPeriod.tenant_id == tenant_id,
        Models.FinancialPeriod.year_id == year.year_id,
        Models.FinancialPeriod.period_type == "month",
    ).order_by(Models.FinancialPeriod.period_number).all()


# ── 1. KPI summary tiles ────────────────────────────────────────────

@router.get("/departments/summary")
def department_summary(
    fiscal_year: Optional[str] = Query(None, description="Financial year label, e.g. 2026-27"),
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization(REPORT_PERMISSION)),
):
    tenant_id = _tenant_uuid(ctx)
    year = _resolve_year(db, tenant_id, fiscal_year)
    currency = _currency(db, tenant_id)

    departments = _departments(db, tenant_id)
    headcounts = _headcount_map(db, tenant_id)
    spend = _spend_map(db, tenant_id, year)

    return {
        "fiscal_year": year.label,
        "departments_count": len(departments),
        "total_headcount": sum(headcounts.values()),
        "total_attributed_spend_minor": sum(spend.values()),
        "currency": currency,
    }


# ── 2. Spend by department ──────────────────────────────────────────

@router.get("/departments/spend")
def department_spend(
    fiscal_year: Optional[str] = Query(None, description="Financial year label, e.g. 2026-27"),
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization(REPORT_PERMISSION)),
):
    tenant_id = _tenant_uuid(ctx)
    year = _resolve_year(db, tenant_id, fiscal_year)
    currency = _currency(db, tenant_id)

    departments = _departments(db, tenant_id)
    spend = _spend_map(db, tenant_id, year)

    items = [
        {
            "id": str(d.org_unit_id),
            "label": d.name,
            "value_minor": spend.get(d.org_unit_id, 0),
            "display_value": _fmt_money(spend.get(d.org_unit_id, 0), currency),
        }
        for d in departments
    ]
    items.sort(key=lambda i: i["value_minor"], reverse=True)

    return {"fiscal_year": year.label, "currency": currency, "items": items}


# ── 3. Headcount by department ──────────────────────────────────────

@router.get("/departments/headcount")
def department_headcount(
    fiscal_year: Optional[str] = Query(None, description="Financial year label, e.g. 2026-27"),
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization(REPORT_PERMISSION)),
):
    tenant_id = _tenant_uuid(ctx)
    year = _resolve_year(db, tenant_id, fiscal_year)

    departments = _departments(db, tenant_id)
    headcounts = _headcount_map(db, tenant_id)

    items = [
        {
            "id": str(d.org_unit_id),
            "label": d.name,
            "value": headcounts.get(d.org_unit_id, 0),
            "display_value": str(headcounts.get(d.org_unit_id, 0)),
        }
        for d in departments
    ]
    items.sort(key=lambda i: i["value"], reverse=True)

    return {"fiscal_year": year.label, "items": items}


# ── 4. Spend per head (with monthly breakdown) ─────────────────────

@router.get("/departments/spend-per-head")
def department_spend_per_head(
    fiscal_year: Optional[str] = Query(None, description="Financial year label, e.g. 2026-27"),
    period: str = Query("total", description="total | month name, e.g. january"),
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization(REPORT_PERMISSION)),
):
    tenant_id = _tenant_uuid(ctx)
    year = _resolve_year(db, tenant_id, fiscal_year)
    currency = _currency(db, tenant_id)

    month_periods = _month_periods(db, tenant_id, year)
    # Unique month names in period order (a 4-4-5 calendar may repeat a month)
    month_names: List[str] = []
    for p in month_periods:
        name = p.start_date.strftime("%B").lower()
        if name not in month_names:
            month_names.append(name)
    available_periods = ["total"] + month_names

    period_key = (period or "total").strip().lower()
    selected: Optional[Models.FinancialPeriod] = None
    if period_key != "total":
        if period_key not in month_names:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown period '{period}'. Available: {available_periods}",
            )
        selected = next(p for p in month_periods if p.start_date.strftime("%B").lower() == period_key)

    departments = _departments(db, tenant_id)
    headcounts = _headcount_map(db, tenant_id)
    spend = _spend_map(db, tenant_id, year, period=selected)

    items = []
    for d in departments:
        total = spend.get(d.org_unit_id, 0)
        heads = headcounts.get(d.org_unit_id, 0)
        per_head = int(round(total / heads)) if heads else 0
        items.append({
            "department_id": str(d.org_unit_id),
            "department": d.name,
            "spend_minor": per_head,
            "display_amount": _fmt_money(per_head, currency),
            "headcount": heads,
        })
    items.sort(key=lambda i: i["spend_minor"], reverse=True)

    return {
        "fiscal_year": year.label,
        "period": period_key,
        "currency": currency,
        "available_periods": available_periods,
        "items": items,
    }
