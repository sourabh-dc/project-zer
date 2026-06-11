"""
Derived Knowledge — fact computation functions.

Each function computes ONE fact type by querying Postgres and/or Neo4j.
Results are stored as JSONB in derived_knowledge table via store.save_fact().

WHY precompute instead of query live?
  Facts like "top categories by spend this quarter" require multi-table
  aggregation joins that are slow (100ms+) and expensive. Precomputing means:
  - LLM prompt gets a 2-line summary instead of running a 5-table JOIN
  - Consistent numbers within a session (no drift between planner + summarizer)
  - Zero DB load for common analytical questions

HOW recomputation is triggered:
  Outbox events → handlers.py → compute_*() → store.save_fact()
  e.g. purchase_request.submitted → recompute top_categories_by_spend

WHY graceful failure?
  If Postgres is slow or the query fails, we return None. The agent still
  works — it just doesn't have derived context. Partial context is better
  than no answer.
"""
from typing import Optional, Dict, Any
from datetime import datetime, timezone

from data_intelligence_service.core.logger import logger
from data_intelligence_service.intelligence.derived.models import (
    DerivedFact,
    FACT_TOP_CATEGORIES_BY_SPEND,
    FACT_APPROVAL_POLICY_SUMMARY,
    FACT_ORG_UNIT_BUDGET_STATUS,
    FACT_VENDOR_ACTIVITY_SUMMARY,
    FACT_APPROVED_PRODUCT_COUNT,
)


def _db_session():
    """Get a fresh DB session. Lazy import to avoid circular dependencies."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from data_intelligence_service.core.config import SETTINGS
    engine = create_engine(SETTINGS.POSTGRES_URL, pool_pre_ping=True)
    return sessionmaker(bind=engine)()


def compute_top_categories_by_spend(tenant_id: str) -> Optional[DerivedFact]:
    """Top 10 product categories ranked by total spend this quarter.

    Payload shape:
      {
        "period": "2026-Q2",
        "categories": [
          {"name": "PPE", "total_spend": 45200.00, "order_count": 87},
          ...
        ]
      }
    """
    from sqlalchemy import text
    session = _db_session()
    try:
        result = session.execute(text("""
            SELECT
                c.name                         AS category_name,
                SUM(oi.unit_price * oi.quantity) AS total_spend,
                COUNT(DISTINCT oi.order_id)      AS order_count
            FROM order_items oi
            JOIN products   p  ON p.product_id  = oi.product_id
            JOIN categories c  ON c.category_id = p.category_id
            JOIN orders     o  ON o.order_id     = oi.order_id
            WHERE o.tenant_id = :tid
              AND o.created_at >= date_trunc('quarter', NOW())
              AND o.status NOT IN ('cancelled', 'rejected')
            GROUP BY c.name
            ORDER BY total_spend DESC
            LIMIT 10
        """), {"tid": tenant_id})

        rows = result.fetchall()
        now = datetime.now(timezone.utc)
        quarter = f"{now.year}-Q{(now.month - 1) // 3 + 1}"

        payload: Dict[str, Any] = {
            "period": quarter,
            "categories": [
                {
                    "name":        row[0],
                    "total_spend": float(row[1] or 0),
                    "order_count": int(row[2] or 0),
                }
                for row in rows
            ],
        }
        logger.info(f"[DerivedFact] top_categories computed for {tenant_id}: {len(rows)} categories")
        return DerivedFact(fact_type=FACT_TOP_CATEGORIES_BY_SPEND, tenant_id=tenant_id, payload=payload)

    except Exception as exc:
        logger.warning(f"[DerivedFact] top_categories_by_spend failed: {exc}")
        return None
    finally:
        session.close()


def compute_approval_policy_summary(tenant_id: str) -> Optional[DerivedFact]:
    """Summary of active approval policies for a tenant.

    Queries Postgres for policy metadata (Neo4j has relationship graph,
    Postgres has the authoritative policy records).

    Payload shape:
      {
        "active_policy_count": 4,
        "policies": [
          {"name": "Finance Approval", "threshold_minor": 50000, "approval_required": true},
          ...
        ]
      }
    """
    from sqlalchemy import text
    session = _db_session()
    try:
        result = session.execute(text("""
            SELECT
                p.name,
                p.approval_required,
                p.auto_approve_threshold_minor,
                p.status
            FROM policies p
            WHERE p.tenant_id = :tid
              AND p.status = 'active'
            ORDER BY p.auto_approve_threshold_minor ASC NULLS LAST
            LIMIT 20
        """), {"tid": tenant_id})

        rows = result.fetchall()
        payload: Dict[str, Any] = {
            "active_policy_count": len(rows),
            "policies": [
                {
                    "name":                    row[0],
                    "approval_required":       bool(row[1]),
                    "threshold_minor":         row[2],  # in minor currency units (cents)
                    "status":                  row[3],
                }
                for row in rows
            ],
        }
        logger.info(f"[DerivedFact] approval_policy_summary computed for {tenant_id}: {len(rows)} policies")
        return DerivedFact(fact_type=FACT_APPROVAL_POLICY_SUMMARY, tenant_id=tenant_id, payload=payload)

    except Exception as exc:
        logger.warning(f"[DerivedFact] approval_policy_summary failed: {exc}")
        return None
    finally:
        session.close()


def compute_org_unit_budget_status(tenant_id: str) -> Optional[DerivedFact]:
    """Budget utilization per org unit for the current financial period.

    Payload shape:
      {
        "period": "2026-Q2",
        "org_units": [
          {"name": "Finance", "allocated_minor": 500000, "spent_minor": 320000, "utilization_pct": 64.0},
          ...
        ]
      }
    """
    from sqlalchemy import text
    session = _db_session()
    try:
        result = session.execute(text("""
            SELECT
                ou.name                AS org_unit_name,
                b.allocated_minor      AS allocated,
                b.spent_minor          AS spent,
                CASE
                    WHEN b.allocated_minor > 0
                    THEN ROUND((b.spent_minor::numeric / b.allocated_minor) * 100, 1)
                    ELSE 0
                END                    AS utilization_pct
            FROM budgets b
            JOIN org_units ou ON ou.org_unit_id = b.org_unit_id
            WHERE b.tenant_id = :tid
              AND b.period_start <= NOW()
              AND b.period_end   >= NOW()
              AND b.status = 'active'
            ORDER BY utilization_pct DESC
            LIMIT 20
        """), {"tid": tenant_id})

        rows = result.fetchall()
        now = datetime.now(timezone.utc)
        quarter = f"{now.year}-Q{(now.month - 1) // 3 + 1}"

        payload: Dict[str, Any] = {
            "period": quarter,
            "org_units": [
                {
                    "name":             row[0],
                    "allocated_minor":  int(row[1] or 0),
                    "spent_minor":      int(row[2] or 0),
                    "utilization_pct":  float(row[3] or 0),
                }
                for row in rows
            ],
        }
        logger.info(f"[DerivedFact] org_unit_budget_status computed for {tenant_id}: {len(rows)} org units")
        return DerivedFact(fact_type=FACT_ORG_UNIT_BUDGET_STATUS, tenant_id=tenant_id, payload=payload)

    except Exception as exc:
        logger.warning(f"[DerivedFact] org_unit_budget_status failed: {exc}")
        return None
    finally:
        session.close()


def compute_vendor_activity_summary(tenant_id: str) -> Optional[DerivedFact]:
    """Vendor order activity — last order date + order count for the past 90 days.

    Payload shape:
      {
        "window_days": 90,
        "vendors": [
          {"name": "CleanCo Ltd", "order_count": 12, "last_order_date": "2026-06-01"},
          ...
        ],
        "inactive_vendor_count": 3
      }
    """
    from sqlalchemy import text
    session = _db_session()
    try:
        result = session.execute(text("""
            SELECT
                v.name                         AS vendor_name,
                COUNT(DISTINCT o.order_id)     AS order_count,
                MAX(o.created_at)::date        AS last_order_date
            FROM orders o
            JOIN vendors v ON v.vendor_id = o.vendor_id
            WHERE o.tenant_id = :tid
              AND o.created_at >= NOW() - INTERVAL '90 days'
              AND o.status NOT IN ('cancelled')
            GROUP BY v.name
            ORDER BY order_count DESC
            LIMIT 20
        """), {"tid": tenant_id})

        active_rows = result.fetchall()

        # Count inactive vendors (no orders in 90 days)
        inactive_result = session.execute(text("""
            SELECT COUNT(*) FROM vendors v
            WHERE v.tenant_id = :tid
              AND v.status = 'active'
              AND v.vendor_id NOT IN (
                SELECT DISTINCT vendor_id FROM orders
                WHERE tenant_id = :tid
                  AND created_at >= NOW() - INTERVAL '90 days'
              )
        """), {"tid": tenant_id})
        inactive_count = inactive_result.scalar() or 0

        payload: Dict[str, Any] = {
            "window_days": 90,
            "vendors": [
                {
                    "name":            row[0],
                    "order_count":     int(row[1] or 0),
                    "last_order_date": str(row[2]) if row[2] else None,
                }
                for row in active_rows
            ],
            "inactive_vendor_count": int(inactive_count),
        }
        logger.info(f"[DerivedFact] vendor_activity_summary computed for {tenant_id}: {len(active_rows)} active vendors")
        return DerivedFact(fact_type=FACT_VENDOR_ACTIVITY_SUMMARY, tenant_id=tenant_id, payload=payload)

    except Exception as exc:
        logger.warning(f"[DerivedFact] vendor_activity_summary failed: {exc}")
        return None
    finally:
        session.close()


def compute_approved_product_count(tenant_id: str) -> Optional[DerivedFact]:
    """Count of approved products per org unit — from Neo4j approved universe.

    WHY Neo4j for this fact?
      The approved universe is a graph traversal. The canonical implementation
      is in graph/queries/approved_universe.py. We reuse that logic here.

    Payload shape:
      {
        "total_approved_products": 142,
        "universal_range_exists": true,
        "ranges": [
          {"name": "Standard Office Range", "org_units": 5, "category_count": 8},
          ...
        ]
      }
    """
    try:
        from data_intelligence_service.core.neo4j_client import get_session as neo_session
        with neo_session() as session:
            # Count distinct products accessible via any approved range for this tenant
            result = session.run("""
                MATCH (t:Tenant {tenant_id: $tid})-[:HAS_APPROVED_RANGE]->(ar:ApprovedRange {status: 'active'})
                OPTIONAL MATCH (ar)-[:INCLUDES_CATEGORY]->(c:Category)<-[:IN_CATEGORY]-(p:Product {status:'active'})
                OPTIONAL MATCH (ar)-[:INCLUDES]->(p2:Product {status:'active'})
                WITH ar,
                     COUNT(DISTINCT p)  AS cat_products,
                     COUNT(DISTINCT p2) AS direct_products,
                     ar.is_universal    AS is_universal,
                     ar.name            AS range_name
                OPTIONAL MATCH (ou:OrgUnit)-[:GOVERNED_BY]->(ar)
                RETURN range_name,
                       cat_products + direct_products AS product_count,
                       COUNT(DISTINCT ou)             AS org_unit_count,
                       is_universal
                ORDER BY product_count DESC
            """, tid=tenant_id)

            rows = result.data()
            total = sum(r["product_count"] for r in rows)
            universal_exists = any(r.get("is_universal") for r in rows)

            payload: Dict[str, Any] = {
                "total_approved_products": total,
                "universal_range_exists":  universal_exists,
                "ranges": [
                    {
                        "name":          r["range_name"],
                        "product_count": r["product_count"],
                        "org_units":     r["org_unit_count"],
                    }
                    for r in rows
                ],
            }
        logger.info(f"[DerivedFact] approved_product_count computed for {tenant_id}: {total} products")
        return DerivedFact(fact_type=FACT_APPROVED_PRODUCT_COUNT, tenant_id=tenant_id, payload=payload)

    except Exception as exc:
        logger.warning(f"[DerivedFact] approved_product_count failed (Neo4j may be down): {exc}")
        return None


# ---------------------------------------------------------------------------
# Dispatcher — compute a fact by name
# ---------------------------------------------------------------------------

_COMPUTERS = {
    FACT_TOP_CATEGORIES_BY_SPEND: compute_top_categories_by_spend,
    FACT_APPROVAL_POLICY_SUMMARY: compute_approval_policy_summary,
    FACT_ORG_UNIT_BUDGET_STATUS:  compute_org_unit_budget_status,
    FACT_VENDOR_ACTIVITY_SUMMARY: compute_vendor_activity_summary,
    FACT_APPROVED_PRODUCT_COUNT:  compute_approved_product_count,
}


def compute_and_save(tenant_id: str, fact_type: str) -> bool:
    """Compute one fact and persist it. Returns True on success.

    Called by handlers when an outbox event triggers a recomputation.
    Fails silently — a failed recomputation never blocks event processing.
    """
    from data_intelligence_service.intelligence.derived.store import save_fact

    computer = _COMPUTERS.get(fact_type)
    if not computer:
        logger.warning(f"[DerivedFact] Unknown fact type: {fact_type}")
        return False

    fact = computer(tenant_id)
    if fact is None:
        return False

    return save_fact(fact)
