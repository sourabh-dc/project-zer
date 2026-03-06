"""
Context Enricher — queries the shared DB to build a rich subject context
for policy evaluation.

Uses raw SQL queries so this service has ZERO dependency on provisioning_service.
Tables queried: users, user_roles, roles, user_cost_centres, tenant_subscriptions,
                approved_ranges, approved_range_org_units, approved_range_products,
                role_permissions.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.orm import Session

from policy_service.utils.logger import logger


def _fetch_approved_product_ids(db: Session, tenant_id: uuid.UUID, org_unit_id: uuid.UUID | None) -> List[str]:
    """Fetch product IDs from active approved ranges for a user's org unit + universal ranges.

    Per engineering doc section 1.5.1 (Approved Universe):
    - Traverse: Tenant → Department → ApprovedRange → Product
    - If no departments or no approvals → return empty set (default-deny for products)
    """
    product_ids: set[str] = set()

    try:
        universal_rows = db.execute(
            text("""
                SELECT arp.product_id
                FROM approved_range_products arp
                JOIN approved_ranges ar ON ar.approved_range_id = arp.approved_range_id
                WHERE ar.tenant_id = :tid
                  AND ar.is_universal = true
                  AND ar.status = 'active'
            """),
            {"tid": tenant_id},
        ).mappings().all()

        for r in universal_rows:
            product_ids.add(str(r["product_id"]))
    except Exception as exc:
        logger.warning(f"Universal approved range lookup failed: {exc}")

    if org_unit_id:
        try:
            ou_rows = db.execute(
                text("""
                    SELECT arp.product_id
                    FROM approved_range_products arp
                    JOIN approved_ranges ar ON ar.approved_range_id = arp.approved_range_id
                    JOIN approved_range_org_units arou ON arou.approved_range_id = ar.approved_range_id
                    WHERE ar.tenant_id = :tid
                      AND arou.org_unit_id = :ouid
                      AND ar.status = 'active'
                      AND ar.is_universal = false
                """),
                {"tid": tenant_id, "ouid": org_unit_id},
            ).mappings().all()

            for r in ou_rows:
                product_ids.add(str(r["product_id"]))
        except Exception as exc:
            logger.warning(f"OrgUnit approved range lookup failed: {exc}")

    return list(product_ids)


def enrich_subject(db: Session, user_id: str, tenant_id: str) -> Dict[str, Any]:
    """Enrich a subject dict with data from the shared DB.

    Returns a dict that can be merged into the evaluation context under "subject".
    Keys added:
      - user_id, tenant_id, email, display_name, is_active
      - home_org_unit_id: str | None
      - roles: list[str]
      - permissions: list[str]
      - budget_remaining, allocated_budget, spent_budget (minor units)
      - max_order_limit_minor
      - subscription_active: bool
      - plan_code: str | None
      - approved_product_ids: list[str]
      - is_tenant_admin: bool
    """
    enriched: Dict[str, Any] = {
        "user_id": user_id,
        "tenant_id": tenant_id,
    }

    try:
        uid = uuid.UUID(user_id)
        tid = uuid.UUID(tenant_id)
    except (ValueError, TypeError):
        logger.warning(f"Invalid UUID for enrichment: user_id={user_id}, tenant_id={tenant_id}")
        return enriched

    # --- User (including home_org_unit_id and max_order_limit_minor from user table) ---
    org_unit_id = None
    try:
        row = db.execute(
            text("""
                SELECT email, display_name, is_active, home_org_unit_id, max_order_limit_minor
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
            if row["home_org_unit_id"]:
                org_unit_id = row["home_org_unit_id"]
                enriched["home_org_unit_id"] = str(org_unit_id)
            enriched["max_order_limit_minor"] = row["max_order_limit_minor"] or 0
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

    is_admin = "tenant_admin" in enriched.get("roles", [])
    enriched["is_tenant_admin"] = is_admin

    # --- Permissions (resolved from roles) ---
    try:
        if enriched.get("roles"):
            perm_rows = db.execute(
                text("""
                    SELECT DISTINCT rp.permission_code
                    FROM role_permissions rp
                    WHERE rp.role_code IN :role_codes
                """),
                {"role_codes": tuple(enriched["roles"])},
            ).mappings().all()
            enriched["permissions"] = [p["permission_code"] for p in perm_rows]
        else:
            enriched["permissions"] = []
    except Exception as exc:
        logger.warning(f"Permissions lookup failed: {exc}")
        enriched["permissions"] = []

    if "*" in enriched.get("permissions", []):
        is_admin = True
        enriched["is_tenant_admin"] = True

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
            if not enriched.get("max_order_limit_minor"):
                enriched["max_order_limit_minor"] = budget_row["max_budget_minor"] or 0
            enriched["cost_centre_id"] = str(budget_row["cost_centre_id"])
        else:
            enriched.setdefault("budget_remaining", 0)
            enriched.setdefault("allocated_budget", 0)
            enriched.setdefault("spent_budget", 0)
    except Exception as exc:
        logger.warning(f"Budget lookup failed: {exc}")
        enriched.setdefault("budget_remaining", 0)
        enriched.setdefault("allocated_budget", 0)
        enriched.setdefault("spent_budget", 0)
        enriched.setdefault("max_order_limit_minor", 0)

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

    # --- Approved Product IDs (for product visibility governance) ---
    # Tenant admins see all products; regular users only see products in their approved ranges
    if is_admin:
        enriched["approved_product_ids"] = "__all__"
    else:
        enriched["approved_product_ids"] = _fetch_approved_product_ids(db, tid, org_unit_id)

    return enriched

