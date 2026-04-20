"""
shared/policy_engine/context_enricher.py
-----------------------------------------
Enriches the OPA subject context with data from the shared PostgreSQL DB.

Uses raw SQL queries — zero dependency on any service's ORM models.

Tables queried:
  users, user_roles, roles, role_permissions,
  user_cost_centres, tenant_subscriptions,
  approved_ranges, approved_range_org_units, approved_range_products.

Keys added to the subject dict:
  user_id, tenant_id, email, display_name, is_active,
  home_org_unit_id, max_order_limit_minor,
  roles, permissions, is_tenant_admin,
  budget_remaining, allocated_budget, spent_budget, cost_centre_id,
  subscription_active, subscription_status, plan_code,
  approved_product_ids.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger("policy_engine.context_enricher")


def _fetch_approved_product_ids(
    db: Session,
    tenant_id: uuid.UUID,
    org_unit_id: uuid.UUID | None,
) -> List[str]:
    """Fetch approved product IDs for a user's org unit + universal ranges."""
    product_ids: set[str] = set()

    try:
        rows = db.execute(
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
        for r in rows:
            product_ids.add(str(r["product_id"]))
    except Exception as exc:
        logger.warning(f"Universal approved range lookup failed: {exc}")

    if org_unit_id:
        try:
            rows = db.execute(
                text("""
                    SELECT arp.product_id
                    FROM approved_range_products arp
                    JOIN approved_ranges ar ON ar.approved_range_id = arp.approved_range_id
                    JOIN approved_range_org_units arou
                         ON arou.approved_range_id = ar.approved_range_id
                    WHERE ar.tenant_id = :tid
                      AND arou.org_unit_id = :ouid
                      AND ar.status = 'active'
                      AND ar.is_universal = false
                """),
                {"tid": tenant_id, "ouid": org_unit_id},
            ).mappings().all()
            for r in rows:
                product_ids.add(str(r["product_id"]))
        except Exception as exc:
            logger.warning(f"OrgUnit approved range lookup failed: {exc}")

    return list(product_ids)


def enrich_subject(db: Session, user_id: str, tenant_id: str) -> Dict[str, Any]:
    """Build a rich subject context dict from the shared DB.

    Returns a dict merged into the OPA input.subject field.
    All errors are caught and logged — partial enrichment is returned
    rather than failing the request.
    """
    enriched: Dict[str, Any] = {"user_id": user_id, "tenant_id": tenant_id}

    try:
        uid = uuid.UUID(user_id)
        tid = uuid.UUID(tenant_id)
    except (ValueError, TypeError):
        logger.warning(f"Invalid UUID for enrichment: user_id={user_id}, tenant_id={tenant_id}")
        return enriched

    org_unit_id = None

    # ── User ──────────────────────────────────────────────────────────
    try:
        row = db.execute(
            text("""
                SELECT email, display_name, is_active,
                       home_org_unit_id, max_order_limit_minor
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

    # ── Roles ─────────────────────────────────────────────────────────
    try:
        rows = db.execute(
            text("""
                SELECT r.code
                FROM user_roles ur
                JOIN roles r ON r.role_id = ur.role_id
                WHERE ur.user_id = :uid
            """),
            {"uid": uid},
        ).mappings().all()
        enriched["roles"] = [r["code"] for r in rows if r["code"]]
    except Exception as exc:
        logger.warning(f"Roles lookup failed: {exc}")
        enriched["roles"] = []

    is_admin = "tenant_admin" in enriched.get("roles", [])
    enriched["is_tenant_admin"] = is_admin

    # ── Permissions ───────────────────────────────────────────────────
    try:
        roles = enriched.get("roles", [])
        if roles:
            rows = db.execute(
                text("""
                    SELECT DISTINCT rp.permission_code
                    FROM role_permissions rp
                    WHERE rp.role_code IN :codes
                """),
                {"codes": tuple(roles)},
            ).mappings().all()
            enriched["permissions"] = [p["permission_code"] for p in rows]
        else:
            enriched["permissions"] = []
    except Exception as exc:
        logger.warning(f"Permissions lookup failed: {exc}")
        enriched["permissions"] = []

    if "*" in enriched.get("permissions", []):
        enriched["is_tenant_admin"] = True
        is_admin = True

    # ── Budget ────────────────────────────────────────────────────────
    try:
        row = db.execute(
            text("""
                SELECT available_minor, allocated_minor, spent_minor,
                       max_budget_minor, cost_centre_id
                FROM user_cost_centres
                WHERE user_id = :uid AND is_blocked = false
                LIMIT 1
            """),
            {"uid": uid},
        ).mappings().first()

        if row:
            enriched["budget_remaining"] = row["available_minor"] or 0
            enriched["allocated_budget"] = row["allocated_minor"] or 0
            enriched["spent_budget"] = row["spent_minor"] or 0
            enriched.setdefault("max_order_limit_minor", row["max_budget_minor"] or 0)
            enriched["cost_centre_id"] = str(row["cost_centre_id"])
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

    # ── Subscription ──────────────────────────────────────────────────
    now = datetime.now(timezone.utc)
    try:
        row = db.execute(
            text("""
                SELECT plan_code, status
                FROM tenant_subscriptions
                WHERE tenant_id = :tid
                  AND is_active = true
                  AND current_period_end > :now
                LIMIT 1
            """),
            {"tid": tid, "now": now},
        ).mappings().first()

        enriched["subscription_active"] = row is not None
        enriched["subscription_status"] = row["status"] if row else "inactive"
        enriched["plan_code"] = row["plan_code"] if row else None
    except Exception as exc:
        logger.warning(f"Subscription lookup failed: {exc}")
        enriched["subscription_active"] = False
        enriched["subscription_status"] = "inactive"
        enriched["plan_code"] = None

    # ── Approved Product IDs ──────────────────────────────────────────
    if is_admin:
        enriched["approved_product_ids"] = "__all__"
    else:
        enriched["approved_product_ids"] = _fetch_approved_product_ids(db, tid, org_unit_id)

    return enriched
