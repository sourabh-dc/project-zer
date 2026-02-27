"""
Context Enricher — queries the shared DB to build a rich subject context
for policy evaluation.

Uses raw SQL queries so this service has ZERO dependency on provisioning_service.
Tables queried: users, user_roles, roles, user_cost_centres, tenant_subscriptions.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy import text
from sqlalchemy.orm import Session

from policy_service.utils.logger import logger


def enrich_subject(db: Session, user_id: str, tenant_id: str) -> Dict[str, Any]:
    """Enrich a subject dict with data from the shared DB.

    Returns a dict that can be merged into the evaluation context under "subject".
    Keys added:
      - user_id, tenant_id, email, display_name, is_active
      - roles: list[str]
      - budget_remaining, allocated_budget, spent_budget (minor units)
      - max_order_limit_minor
      - subscription_active: bool
      - plan_code: str | None
    """
    enriched: Dict[str, Any] = {
        "user_id": user_id,
        "tenant_id": tenant_id,
    }

    # Validate UUIDs early
    try:
        uid = uuid.UUID(user_id)
        tid = uuid.UUID(tenant_id)
    except (ValueError, TypeError):
        logger.warning(f"Invalid UUID for enrichment: user_id={user_id}, tenant_id={tenant_id}")
        return enriched

    # --- User ---
    try:
        row = db.execute(
            text("""
                SELECT email, display_name, is_active
                FROM users
                WHERE user_id = :uid
                LIMIT 1
            """),
            {"uid": uid},
        ).mappings().first()

        if row:
            enriched["email"] = row["email"]
            enriched["display_name"] = row["display_name"]
            enriched["is_active"] = row["is_active"]
    except Exception as exc:
        logger.warning(f"User lookup failed: {exc}")

    # --- Roles ---
    try:
        role_rows = db.execute(
            text("""
                SELECT r.code
                FROM user_roles ur
                JOIN roles r ON r.role_id = ur.role_id
                WHERE ur.user_id = :uid
            """),
            {"uid": uid},
        ).mappings().all()

        enriched["roles"] = [r["code"] for r in role_rows if r["code"]]
    except Exception as exc:
        logger.warning(f"Roles lookup failed: {exc}")
        enriched["roles"] = []

    # --- Budget (first non-blocked UserCostCentre) ---
    try:
        budget_row = db.execute(
            text("""
                SELECT available_minor, allocated_minor, spent_minor,
                       max_budget_minor, cost_centre_id
                FROM user_cost_centres
                WHERE user_id = :uid AND is_blocked = false
                LIMIT 1
            """),
            {"uid": uid},
        ).mappings().first()

        if budget_row:
            enriched["budget_remaining"] = budget_row["available_minor"] or 0
            enriched["allocated_budget"] = budget_row["allocated_minor"] or 0
            enriched["spent_budget"] = budget_row["spent_minor"] or 0
            enriched["max_order_limit_minor"] = budget_row["max_budget_minor"] or 0
            enriched["cost_centre_id"] = str(budget_row["cost_centre_id"])
        else:
            enriched["budget_remaining"] = 0
            enriched["allocated_budget"] = 0
            enriched["spent_budget"] = 0
            enriched["max_order_limit_minor"] = 0
    except Exception as exc:
        logger.warning(f"Budget lookup failed: {exc}")
        enriched["budget_remaining"] = 0
        enriched["allocated_budget"] = 0
        enriched["spent_budget"] = 0
        enriched["max_order_limit_minor"] = 0

    # --- Subscription ---
    now = datetime.now(timezone.utc)
    try:
        sub_row = db.execute(
            text("""
                SELECT plan_code
                FROM tenant_subscriptions
                WHERE tenant_id = :tid
                  AND is_active = true
                  AND current_period_end > :now
                LIMIT 1
            """),
            {"tid": tid, "now": now},
        ).mappings().first()

        enriched["subscription_active"] = sub_row is not None
        enriched["plan_code"] = sub_row["plan_code"] if sub_row else None
    except Exception as exc:
        logger.warning(f"Subscription lookup failed: {exc}")
        enriched["subscription_active"] = False
        enriched["plan_code"] = None

    return enriched

