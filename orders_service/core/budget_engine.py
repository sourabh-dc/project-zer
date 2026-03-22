from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

from sqlalchemy.orm import Session

from orders_service.Models import CompanyBudgetCap, CostCentre, CostCentreBudgetVersion, UserBudgetLimit
from orders_service.utils.logger import logger


@dataclass
class WindowCheck:
    window_type: str
    limit_type: str
    limit_amount_minor: int
    committed_minor: int
    spent_minor: int
    carry_forward_minor: int
    breached: bool
    available_minor: int
    limit_id: uuid.UUID


@dataclass
class BudgetCheckResult:
    can_self_approve: bool
    needs_approval: bool
    is_blocked: bool
    block_reason: Optional[str] = None
    requester_breaches: List[WindowCheck] = field(default_factory=list)
    cc_headroom_minor: Optional[int] = None
    company_cap_headroom_minor: Optional[int] = None


def check_request_headroom(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    requester_id: uuid.UUID,
    cost_centre_id: uuid.UUID,
    amount_minor: int,
    year_id: Optional[uuid.UUID] = None,
    period_id: Optional[uuid.UUID] = None,
    as_of: Optional[date] = None,
) -> BudgetCheckResult:
    today = as_of or date.today()
    result = BudgetCheckResult(can_self_approve=False, needs_approval=True, is_blocked=False)

    cc_version = _resolve_cc_version(db, cost_centre_id, year_id, period_id, today)
    if cc_version:
        available_cc = (
            cc_version.budget_minor
            + cc_version.carry_forward_minor
            - cc_version.committed_minor
            - cc_version.spent_minor
        )
        result.cc_headroom_minor = available_cc
        if available_cc < amount_minor:
            result.is_blocked = True
            result.block_reason = (
                f"Cost centre budget insufficient: available {available_cc}, requested {amount_minor}"
            )
            result.needs_approval = False
            return result
    else:
        logger.warning(
            f"No active CC budget version for cost_centre={cost_centre_id}, year={year_id}, period={period_id}"
        )

    if year_id:
        cap = (
            db.query(CompanyBudgetCap)
            .filter(
                CompanyBudgetCap.tenant_id == tenant_id,
                CompanyBudgetCap.year_id == year_id,
            )
            .first()
        )
        if cap:
            available_cap = cap.total_budget_minor - cap.committed_minor - cap.spent_minor
            result.company_cap_headroom_minor = available_cap
            if cap.hard_cap and available_cap < amount_minor:
                result.is_blocked = True
                result.block_reason = (
                    f"Company budget cap exceeded: available {available_cap}, requested {amount_minor}"
                )
                result.needs_approval = False
                return result

    requester_limits = (
        db.query(UserBudgetLimit)
        .filter(
            UserBudgetLimit.user_id == requester_id,
            UserBudgetLimit.cost_centre_id == cost_centre_id,
            UserBudgetLimit.limit_type == "requester",
            UserBudgetLimit.is_active.is_(True),
        )
        .all()
    )

    breaches: List[WindowCheck] = []
    for lim in requester_limits:
        if not _is_limit_in_window(lim, today):
            continue
        carry = lim.carry_forward_minor if lim.carry_forward_enabled else 0
        available = lim.limit_amount_minor + carry - lim.committed_minor - lim.spent_minor
        breached = available < amount_minor
        check = WindowCheck(
            window_type=lim.window_type,
            limit_type="requester",
            limit_amount_minor=lim.limit_amount_minor,
            committed_minor=lim.committed_minor,
            spent_minor=lim.spent_minor,
            carry_forward_minor=carry,
            breached=breached,
            available_minor=available,
            limit_id=lim.limit_id,
        )
        if breached:
            breaches.append(check)

    result.requester_breaches = breaches
    if not breaches:
        result.can_self_approve = True
        result.needs_approval = False
    else:
        result.can_self_approve = False
        result.needs_approval = True
    return result


def commit_approver_limits(
    db: Session,
    *,
    approver_id: uuid.UUID,
    cost_centre_id: uuid.UUID,
    amount_minor: int,
    as_of: Optional[date] = None,
) -> None:
    today = as_of or date.today()
    limits = (
        db.query(UserBudgetLimit)
        .filter(
            UserBudgetLimit.user_id == approver_id,
            UserBudgetLimit.cost_centre_id == cost_centre_id,
            UserBudgetLimit.limit_type == "approver",
            UserBudgetLimit.is_active.is_(True),
        )
        .all()
    )
    for lim in limits:
        if _is_limit_in_window(lim, today):
            lim.committed_minor = (lim.committed_minor or 0) + amount_minor
    db.flush()


def commit_cc_budget(
    db: Session,
    *,
    cost_centre_id: uuid.UUID,
    year_id: Optional[uuid.UUID],
    period_id: Optional[uuid.UUID],
    amount_minor: int,
    as_of: Optional[date] = None,
) -> None:
    today = as_of or date.today()
    version = _resolve_cc_version(db, cost_centre_id, year_id, period_id, today)
    if version:
        version.committed_minor = (version.committed_minor or 0) + amount_minor

    if year_id:
        cc = db.query(CostCentre).filter(CostCentre.cost_centre_id == cost_centre_id).first()
        if cc:
            cap = (
                db.query(CompanyBudgetCap)
                .filter(CompanyBudgetCap.tenant_id == cc.tenant_id, CompanyBudgetCap.year_id == year_id)
                .first()
            )
            if cap:
                cap.committed_minor = (cap.committed_minor or 0) + amount_minor
    db.flush()


def _resolve_cc_version(db: Session, cost_centre_id, year_id, period_id, today: date):
    q = db.query(CostCentreBudgetVersion).filter(
        CostCentreBudgetVersion.cost_centre_id == cost_centre_id,
        CostCentreBudgetVersion.status == "active",
    )
    if year_id:
        q = q.filter(CostCentreBudgetVersion.year_id == year_id)
    if period_id:
        specific = q.filter(CostCentreBudgetVersion.period_id == period_id).first()
        if specific:
            return specific
        return q.filter(CostCentreBudgetVersion.period_id.is_(None)).first()
    return q.filter(CostCentreBudgetVersion.period_id.is_(None)).first()


def _is_limit_in_window(lim, today: date) -> bool:
    if lim.window_start and lim.window_end:
        return lim.window_start <= today <= lim.window_end
    return True

