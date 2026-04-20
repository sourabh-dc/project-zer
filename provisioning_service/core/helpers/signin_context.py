"""
signin_context.py
-----------------
Builds the full status-check context returned on every user sign-in.

Validates and returns:
  - Subscription: active/inactive, trial, plan details
  - Limits: per-feature usage vs quota
  - Balance: aggregated budget across user's cost centres
  - Tenant: resolved tenant info
  - RBAC: roles, permissions, enabled feature flags
"""

from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from provisioning_service.Models import (
    Tenant, TenantSubscription, SubscriptionPlan, PlanFeature, Feature,
    CostCentre, UserCostCentre, CostCenterBudget,
)
from provisioning_service.Schemas import (
    SubscriptionContext, TenantContext, BalanceContext, RBACContext,
    FeatureLimitStatus,
)
from provisioning_service.core.entitlement_helpers import load_tenant_features


def build_subscription_context(
    db: Session, tenant_id, *, active_sub: Optional[TenantSubscription] = None,
) -> Optional[SubscriptionContext]:
    """Build full subscription context with feature limits."""
    if active_sub is None:
        active_sub = db.query(TenantSubscription).filter(
            TenantSubscription.tenant_id == tenant_id,
            TenantSubscription.is_active == True,
        ).first()

    if not active_sub:
        return SubscriptionContext(is_active=False)

    plan = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.code == active_sub.plan_code
    ).first()

    # Feature codes for backwards compat
    feature_rows = db.query(PlanFeature.feature_code).filter(
        PlanFeature.plan_code == active_sub.plan_code,
    ).all()
    feature_codes = [f[0] for f in feature_rows]

    # Full feature usage/limits
    is_active, _, _, features_dict = load_tenant_features(db, str(tenant_id))

    feature_limits: List[FeatureLimitStatus] = []
    any_exceeded = False
    for code, fu in features_dict.items():
        exceeded = False
        if fu.limit is not None and fu.used >= fu.limit:
            exceeded = True
            any_exceeded = True
        feature_limits.append(FeatureLimitStatus(
            code=fu.code,
            name=fu.name,
            limit=fu.limit,
            used=fu.used,
            remaining=fu.remaining,
            reset_period=fu.reset_period,
            resets_at=fu.resets_at.isoformat() if fu.resets_at else None,
            exceeded=exceeded,
        ))

    trial_ends = None
    if active_sub.is_trial and active_sub.current_period_end:
        trial_ends = active_sub.current_period_end.isoformat()

    return SubscriptionContext(
        plan_code=active_sub.plan_code,
        plan_name=plan.name if plan else active_sub.plan_code,
        billing_cycle=active_sub.billing_cycle,
        is_active=active_sub.is_active,
        is_trial=active_sub.is_trial,
        trial_ends_at=trial_ends,
        current_period_end=(
            active_sub.current_period_end.isoformat()
            if active_sub.current_period_end else None
        ),
        features=feature_codes,
        feature_limits=feature_limits,
        any_limit_exceeded=any_exceeded,
    )


def build_tenant_context(db: Session, tenant_id) -> Optional[TenantContext]:
    """Resolve tenant info."""
    tenant = db.query(Tenant).filter(Tenant.tenant_id == tenant_id).first()
    if not tenant:
        return None
    return TenantContext(
        tenant_id=str(tenant.tenant_id),
        tenant_name=tenant.tenant_name,
        tenant_type=tenant.tenant_type,
        default_currency=tenant.default_currency,
        timezone=tenant.timezone,
        locale=tenant.locale,
        industry=tenant.industry,
        logo=tenant.logo,
        is_active=tenant.active,
    )


def build_balance_context(db: Session, user_id, tenant_id) -> BalanceContext:
    """Aggregate budget balance across user's active cost centres."""
    user_ccs = (
        db.query(UserCostCentre)
        .filter(UserCostCentre.user_id == user_id)
        .all()
    )

    total_budget = 0
    total_spent = 0
    total_available = 0
    currency = None

    for ucc in user_ccs:
        if ucc.is_blocked:
            continue
        total_budget += ucc.allocated_minor or 0
        total_spent += ucc.spent_minor or 0
        total_available += ucc.available_minor or 0

        if currency is None and ucc.cc_budget:
            # Try to get currency from the related CC budget's tenant
            tenant = db.query(Tenant).filter(Tenant.tenant_id == tenant_id).first()
            if tenant:
                currency = tenant.default_currency

    total_committed = total_budget - total_available - total_spent
    if total_committed < 0:
        total_committed = 0

    return BalanceContext(
        total_budget_minor=total_budget,
        total_committed_minor=total_committed,
        total_spent_minor=total_spent,
        total_available_minor=total_available,
        currency=currency,
    )


def build_rbac_context(
    roles: List[str],
    permissions: List[str],
    feature_codes: Optional[List[str]] = None,
) -> RBACContext:
    """Bundle RBAC info."""
    return RBACContext(
        roles=roles,
        permissions=permissions,
        feature_flags=feature_codes or [],
    )
