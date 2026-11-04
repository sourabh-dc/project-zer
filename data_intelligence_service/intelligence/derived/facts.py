"""
Derived Knowledge — fact computation functions.

Each function computes ONE fact type by querying Postgres and/or Neo4j.
Results are stored as JSONB in derived_knowledge table via store.save_fact().

WHY precompute instead of query live?
  Facts like supplier performance require multi-table joins that are slow and
  expensive to run on every query. Precomputing means:
  - LLM prompt gets a 2-line summary instead of running complex aggregations
  - Consistent numbers within a session (no drift between planner + summarizer)
  - Zero DB load for common analytical questions

WHY graceful failure?
  If Postgres is slow or the query fails, we return None. The agent still
  works — partial context is better than no answer.

Confidence scoring:
  Each function sets confidence_score < 1.0 when data is partial
  (e.g. query returned 0 rows but we expected some — data may be missing).
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
    FACT_SUPPLIER_PERFORMANCE,
    FACT_SUPPLIER_RISK,
    FACT_SPEND_BY_DEPARTMENT,
    FACT_PRODUCT_SUBSTITUTION,
)


def _db_session():
    """Get a fresh DB session. Lazy import to avoid circular dependencies."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from data_intelligence_service.core.config import SETTINGS
    engine = create_engine(SETTINGS.POSTGRES_URL, pool_pre_ping=True)
    return sessionmaker(bind=engine)()


# ---------------------------------------------------------------------------
# Existing facts (unchanged logic, updated to set confidence)
# ---------------------------------------------------------------------------

def compute_top_categories_by_spend(tenant_id: str) -> Optional[DerivedFact]:
    from sqlalchemy import text
    session = _db_session()
    try:
        result = session.execute(text("""
            SELECT
                c.name                                    AS category_name,
                COALESCE(SUM(pr.amount_minor), 0) / 100.0 AS total_spend,
                COUNT(DISTINCT pr.request_id)             AS order_count
            FROM purchase_requests pr
            JOIN categories c ON c.category_id = pr.category_id
            WHERE pr.tenant_id = :tid
              AND pr.created_at >= date_trunc('quarter', NOW())
              AND pr.status NOT IN ('cancelled', 'rejected')
              AND pr.category_id IS NOT NULL
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
                {"name": row[0], "total_spend": float(row[1] or 0), "order_count": int(row[2] or 0)}
                for row in rows
            ],
        }
        confidence = 1.0 if rows else 0.5
        fact = DerivedFact(fact_type=FACT_TOP_CATEGORIES_BY_SPEND, tenant_id=tenant_id,
                           payload=payload, confidence_score=confidence, is_complete=bool(rows))
        logger.info(f"[DerivedFact] top_categories computed for {tenant_id}: {len(rows)} categories")
        return fact
    except Exception as exc:
        logger.warning(f"[DerivedFact] top_categories_by_spend failed: {exc}")
        return None
    finally:
        session.close()


def compute_approval_policy_summary(tenant_id: str) -> Optional[DerivedFact]:
    from sqlalchemy import text
    session = _db_session()
    try:
        result = session.execute(text("""
            SELECT p.name, p.routing_mode, p.is_active,
                   (SELECT COUNT(*) FROM approval_stages s
                     WHERE s.policy_id = p.policy_id) AS stage_count
            FROM approval_policies p
            WHERE p.tenant_id = :tid AND p.is_active
            ORDER BY p.name ASC
            LIMIT 20
        """), {"tid": tenant_id})
        rows = result.fetchall()
        payload: Dict[str, Any] = {
            "active_policy_count": len(rows),
            "policies": [
                {"name": row[0], "routing_mode": row[1],
                 "is_active": bool(row[2]), "stage_count": int(row[3] or 0)}
                for row in rows
            ],
        }
        fact = DerivedFact(fact_type=FACT_APPROVAL_POLICY_SUMMARY, tenant_id=tenant_id,
                           payload=payload, confidence_score=1.0, is_complete=True)
        logger.info(f"[DerivedFact] approval_policy_summary for {tenant_id}: {len(rows)} policies")
        return fact
    except Exception as exc:
        logger.warning(f"[DerivedFact] approval_policy_summary failed: {exc}")
        return None
    finally:
        session.close()


def compute_org_unit_budget_status(tenant_id: str) -> Optional[DerivedFact]:
    from sqlalchemy import text
    session = _db_session()
    try:
        # Budgets live on cost centres (cost_center_budget). Map to org units
        # via user assignments: org_unit → user_org_assignments →
        # user_cc_assignments → cost_center_budget. DISTINCT prevents double
        # counting when several users in a dept share one cost centre.
        result = session.execute(text("""
            WITH dept_budgets AS (
                SELECT DISTINCT
                    ou.org_unit_id,
                    ou.name               AS org_unit_name,
                    b.budget_id,
                    b.budget_amount_minor,
                    b.total_spent_minor
                FROM cost_center_budget b
                JOIN user_cc_assignments ucca
                     ON ucca.cost_centre_id = b.cost_centre_id
                    AND ucca.is_active
                JOIN user_org_assignments uoa
                     ON uoa.user_id = ucca.user_id
                JOIN org_units ou
                     ON ou.org_unit_id = uoa.org_unit_id
                WHERE b.tenant_id = :tid
                  AND b.period_start <= CURRENT_DATE
                  AND b.period_end   >= CURRENT_DATE
                  AND b.status = 'active'
            )
            SELECT
                org_unit_name,
                SUM(budget_amount_minor) AS allocated,
                SUM(total_spent_minor)   AS spent,
                CASE WHEN SUM(budget_amount_minor) > 0
                     THEN ROUND((SUM(total_spent_minor)::numeric / SUM(budget_amount_minor)) * 100, 1)
                     ELSE 0 END AS utilization_pct
            FROM dept_budgets
            GROUP BY org_unit_name
            ORDER BY utilization_pct DESC
            LIMIT 20
        """), {"tid": tenant_id})
        rows = result.fetchall()
        now = datetime.now(timezone.utc)
        quarter = f"{now.year}-Q{(now.month - 1) // 3 + 1}"
        payload: Dict[str, Any] = {
            "period": quarter,
            "org_units": [
                {"name": row[0], "allocated_minor": int(row[1] or 0),
                 "spent_minor": int(row[2] or 0), "utilization_pct": float(row[3] or 0)}
                for row in rows
            ],
        }
        fact = DerivedFact(fact_type=FACT_ORG_UNIT_BUDGET_STATUS, tenant_id=tenant_id,
                           payload=payload, confidence_score=1.0 if rows else 0.5,
                           is_complete=bool(rows))
        logger.info(f"[DerivedFact] org_unit_budget_status for {tenant_id}: {len(rows)} org units")
        return fact
    except Exception as exc:
        logger.warning(f"[DerivedFact] org_unit_budget_status failed: {exc}")
        return None
    finally:
        session.close()


def compute_vendor_activity_summary(tenant_id: str) -> Optional[DerivedFact]:
    from sqlalchemy import text
    session = _db_session()
    try:
        result = session.execute(text("""
            SELECT v.name, COUNT(DISTINCT pr.request_id) AS order_count,
                   MAX(pr.created_at)::date AS last_order_date
            FROM purchase_requests pr
            JOIN vendors v ON v.vendor_id = pr.vendor_id
            WHERE pr.tenant_id = :tid
              AND pr.created_at >= NOW() - INTERVAL '90 days'
              AND pr.status NOT IN ('cancelled', 'rejected')
            GROUP BY v.name ORDER BY order_count DESC LIMIT 20
        """), {"tid": tenant_id})
        active_rows = result.fetchall()
        inactive_result = session.execute(text("""
            SELECT COUNT(*) FROM vendors v
            WHERE v.tenant_id = :tid AND v.status = 'active'
              AND v.vendor_id NOT IN (
                SELECT DISTINCT vendor_id FROM purchase_requests
                WHERE tenant_id = :tid AND created_at >= NOW() - INTERVAL '90 days'
                  AND vendor_id IS NOT NULL
              )
        """), {"tid": tenant_id})
        inactive_count = inactive_result.scalar() or 0
        payload: Dict[str, Any] = {
            "window_days": 90,
            "vendors": [
                {"name": row[0], "order_count": int(row[1] or 0),
                 "last_order_date": str(row[2]) if row[2] else None}
                for row in active_rows
            ],
            "inactive_vendor_count": int(inactive_count),
        }
        fact = DerivedFact(fact_type=FACT_VENDOR_ACTIVITY_SUMMARY, tenant_id=tenant_id,
                           payload=payload, confidence_score=1.0, is_complete=True)
        logger.info(f"[DerivedFact] vendor_activity_summary for {tenant_id}: {len(active_rows)} vendors")
        return fact
    except Exception as exc:
        logger.warning(f"[DerivedFact] vendor_activity_summary failed: {exc}")
        return None
    finally:
        session.close()


def compute_approved_product_count(tenant_id: str) -> Optional[DerivedFact]:
    try:
        from data_intelligence_service.core.neo4j_client import get_session as neo_session
        with neo_session() as session:
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
                       COUNT(DISTINCT ou) AS org_unit_count,
                       is_universal
                ORDER BY product_count DESC
            """, tid=tenant_id)
            rows = result.data()
            total = sum(r["product_count"] for r in rows)
            universal_exists = any(r.get("is_universal") for r in rows)
            payload: Dict[str, Any] = {
                "total_approved_products": total,
                "universal_range_exists": universal_exists,
                "ranges": [
                    {"name": r["range_name"], "product_count": r["product_count"],
                     "org_units": r["org_unit_count"]}
                    for r in rows
                ],
            }
        fact = DerivedFact(fact_type=FACT_APPROVED_PRODUCT_COUNT, tenant_id=tenant_id,
                           payload=payload, confidence_score=1.0 if rows else 0.3,
                           is_complete=bool(rows))
        logger.info(f"[DerivedFact] approved_product_count for {tenant_id}: {total} products")
        return fact
    except Exception as exc:
        logger.warning(f"[DerivedFact] approved_product_count failed (Neo4j may be down): {exc}")
        return None


# ---------------------------------------------------------------------------
# New facts — Phase 1 required (spec §21)
# ---------------------------------------------------------------------------

def compute_supplier_performance(tenant_id: str) -> Optional[DerivedFact]:
    """Supplier performance metrics: acceptance rate + response speed.

    purchase_requests has no delivery tracking, so performance is measured on
    the vendor's response to requests (accepted / rejected / pending) and how
    fast they respond.

    Payload shape:
      {
        "window_days": 180,
        "suppliers": [
          {
            "vendor_id": "...", "name": "CleanCo Ltd",
            "total_orders": 45, "on_time_count": 38,
            "on_time_rate_pct": 84.4,
            "avg_lead_time_days": 3.2,
            "late_orders": 7
          },
          ...
        ]
      }
    """
    from sqlalchemy import text
    session = _db_session()
    try:
        result = session.execute(text("""
            SELECT
                v.vendor_id::text                          AS vendor_id,
                v.name                                     AS vendor_name,
                COUNT(pr.request_id)                       AS total_requests,
                COUNT(pr.request_id) FILTER (
                    WHERE pr.vendor_response_status = 'accepted'
                )                                          AS accepted_count,
                ROUND(
                    100.0 * COUNT(pr.request_id) FILTER (
                        WHERE pr.vendor_response_status = 'accepted'
                    ) / NULLIF(COUNT(pr.request_id) FILTER (
                        WHERE pr.vendor_response_status IS NOT NULL
                    ), 0),
                1)                                         AS acceptance_rate_pct,
                ROUND(
                    AVG(EXTRACT(EPOCH FROM (pr.vendor_response_at - pr.created_at)) / 86400.0)::numeric,
                1)                                         AS avg_response_days
            FROM purchase_requests pr
            JOIN vendors v ON v.vendor_id = pr.vendor_id
            WHERE pr.tenant_id = :tid
              AND pr.created_at >= NOW() - INTERVAL '180 days'
              AND pr.status NOT IN ('cancelled', 'rejected', 'draft')
            GROUP BY v.vendor_id, v.name
            HAVING COUNT(pr.request_id) >= 3
            ORDER BY acceptance_rate_pct DESC NULLS LAST
            LIMIT 30
        """), {"tid": tenant_id})

        rows = result.fetchall()
        payload: Dict[str, Any] = {
            "window_days": 180,
            "suppliers": [
                {
                    "vendor_id":           row[0],
                    "name":                row[1],
                    "total_requests":      int(row[2] or 0),
                    "accepted_count":      int(row[3] or 0),
                    "acceptance_rate_pct": float(row[4] or 0),
                    "avg_response_days":   float(row[5] or 0) if row[5] is not None else None,
                    "declined_or_pending": int(row[2] or 0) - int(row[3] or 0),
                }
                for row in rows
            ],
        }
        confidence = 1.0 if len(rows) >= 3 else (0.7 if rows else 0.2)
        fact = DerivedFact(fact_type=FACT_SUPPLIER_PERFORMANCE, tenant_id=tenant_id,
                           payload=payload, confidence_score=confidence, is_complete=bool(rows))
        logger.info(f"[DerivedFact] supplier_performance for {tenant_id}: {len(rows)} suppliers")
        return fact
    except Exception as exc:
        logger.warning(f"[DerivedFact] supplier_performance failed: {exc}")
        return None
    finally:
        session.close()


def compute_supplier_risk(tenant_id: str) -> Optional[DerivedFact]:
    """Composite supplier risk score (0-100) combining rejection rate and spend concentration.

    Risk formula (adapted — no delivery/defect tracking in purchase_requests):
      score = reject_rate * 40 + concentration_pct * 20
      where reject_rate is [0,1] and concentration_pct = vendor's share of total spend

    Payload shape:
      {
        "window_days": 90,
        "risk_threshold": 50,
        "suppliers": [
          {
            "vendor_id": "...", "name": "RiskySupplier Ltd",
            "risk_score": 72, "risk_level": "high",
            "late_rate": 0.35, "concentration_pct": 0.18,
            "total_orders": 22, "spend_share_pct": 18.0
          },
          ...
        ],
        "high_risk_count": 2
      }
    """
    from sqlalchemy import text
    session = _db_session()
    try:
        # No delivery tracking in purchase_requests — vendor rejection rate is
        # used as the reliability signal, plus spend concentration.
        result = session.execute(text("""
            WITH vendor_stats AS (
                SELECT
                    v.vendor_id::text                       AS vendor_id,
                    v.name                                  AS vendor_name,
                    COUNT(pr.request_id)                    AS total_requests,
                    COALESCE(SUM(pr.amount_minor), 0)       AS total_spend,
                    COUNT(pr.request_id) FILTER (
                        WHERE pr.vendor_response_status = 'rejected'
                    )                                       AS rejected_count
                FROM purchase_requests pr
                JOIN vendors v ON v.vendor_id = pr.vendor_id
                WHERE pr.tenant_id = :tid
                  AND pr.created_at >= NOW() - INTERVAL '90 days'
                  AND pr.status NOT IN ('cancelled', 'draft')
                GROUP BY v.vendor_id, v.name
            ),
            totals AS (
                SELECT SUM(total_spend) AS grand_total FROM vendor_stats
            )
            SELECT
                vs.vendor_id,
                vs.vendor_name,
                vs.total_requests,
                vs.total_spend,
                ROUND(100.0 * vs.rejected_count / NULLIF(vs.total_requests, 0), 2) AS reject_rate_pct,
                ROUND(100.0 * vs.total_spend / NULLIF(t.grand_total, 0), 2)        AS spend_share_pct
            FROM vendor_stats vs, totals t
            WHERE vs.total_requests > 0
            ORDER BY reject_rate_pct DESC NULLS LAST
            LIMIT 30
        """), {"tid": tenant_id})

        rows = result.fetchall()
        suppliers = []
        high_risk = 0
        for row in rows:
            reject_rate   = float(row[4] or 0) / 100.0
            concentration = float(row[5] or 0) / 100.0
            score = round(reject_rate * 40 + concentration * 20, 1)
            score = min(score, 100.0)
            risk_level = "high" if score >= 50 else ("medium" if score >= 25 else "low")
            if risk_level == "high":
                high_risk += 1
            suppliers.append({
                "vendor_id":       row[0],
                "name":            row[1],
                "total_requests":  int(row[2] or 0),
                "risk_score":      score,
                "risk_level":      risk_level,
                "reject_rate_pct": float(row[4] or 0),
                "spend_share_pct": float(row[5] or 0),
            })

        payload: Dict[str, Any] = {
            "window_days":     90,
            "risk_threshold":  50,
            "suppliers":       suppliers,
            "high_risk_count": high_risk,
        }
        confidence = 1.0 if len(rows) >= 3 else (0.6 if rows else 0.1)
        fact = DerivedFact(fact_type=FACT_SUPPLIER_RISK, tenant_id=tenant_id,
                           payload=payload, confidence_score=confidence, is_complete=bool(rows))
        logger.info(f"[DerivedFact] supplier_risk for {tenant_id}: {high_risk} high-risk suppliers")
        return fact
    except Exception as exc:
        logger.warning(f"[DerivedFact] supplier_risk failed: {exc}")
        return None
    finally:
        session.close()


def compute_spend_by_department(tenant_id: str) -> Optional[DerivedFact]:
    """Total spend broken down by department (top-level org units).

    Payload shape:
      {
        "period": "2026-Q2",
        "departments": [
          {"name": "Operations", "total_spend": 128500.00, "request_count": 42},
          ...
        ],
        "grand_total": 289400.00
      }
    """
    from sqlalchemy import text
    session = _db_session()
    try:
        # users have no org_unit_id column — resolve the department via the
        # latest user_org_assignments row, falling back to home_org_unit_id.
        result = session.execute(text("""
            SELECT
                ou.name                                        AS dept_name,
                COUNT(DISTINCT pr.request_id)                  AS request_count,
                COALESCE(SUM(pr.amount_minor) / 100.0, 0)      AS total_spend
            FROM purchase_requests pr
            JOIN users u ON u.user_id = pr.requester_id
            JOIN org_units ou ON ou.org_unit_id = COALESCE(
                (SELECT uoa.org_unit_id
                   FROM user_org_assignments uoa
                  WHERE uoa.user_id = u.user_id
                  ORDER BY uoa.assigned_at DESC
                  LIMIT 1),
                u.home_org_unit_id
            )
            WHERE pr.tenant_id = :tid
              AND pr.created_at >= date_trunc('quarter', NOW())
              AND pr.status NOT IN ('cancelled', 'rejected')
            GROUP BY ou.name
            ORDER BY total_spend DESC
            LIMIT 20
        """), {"tid": tenant_id})
        rows = result.fetchall()
        now = datetime.now(timezone.utc)
        quarter = f"{now.year}-Q{(now.month - 1) // 3 + 1}"
        departments = [
            {"name": row[0], "request_count": int(row[1] or 0),
             "total_spend": float(row[2] or 0)}
            for row in rows
        ]
        grand_total = sum(d["total_spend"] for d in departments)
        payload: Dict[str, Any] = {
            "period":      quarter,
            "departments": departments,
            "grand_total": grand_total,
        }
        confidence = 1.0 if rows else 0.4
        fact = DerivedFact(fact_type=FACT_SPEND_BY_DEPARTMENT, tenant_id=tenant_id,
                           payload=payload, confidence_score=confidence, is_complete=bool(rows))
        logger.info(f"[DerivedFact] spend_by_department for {tenant_id}: {len(rows)} depts, total={grand_total:.0f}")
        return fact
    except Exception as exc:
        logger.warning(f"[DerivedFact] spend_by_department failed: {exc}")
        return None
    finally:
        session.close()


def compute_product_substitution_map(tenant_id: str) -> Optional[DerivedFact]:
    """Products grouped by category — substitutes within the same category.

    For each category with multiple active products, lists alternatives ranked by
    historical order frequency. Lets the LLM suggest substitutes without a live
    DB query.

    Payload shape:
      {
        "categories": [
          {
            "category": "PPE", "product_count": 8,
            "products": [
              {"product_id": "...", "name": "Nitrile Gloves S", "sku": "NIT-S-100",
               "order_count": 45, "unit": "box"},
              ...
            ]
          },
          ...
        ]
      }
    """
    from sqlalchemy import text
    session = _db_session()
    try:
        # No order_items table — purchase_requests.line_items is JSONB shaped
        # [{product_id, qty, unit_price_minor, description}]; unpack it for the
        # order-frequency ranking.
        result = session.execute(text("""
            SELECT
                c.name                             AS category_name,
                p.product_id::text                 AS product_id,
                p.display_name                     AS product_name,
                p.sku                              AS sku,
                COALESCE(cnt.order_count, 0)       AS order_count
            FROM products p
            JOIN categories c ON c.category_id = p.category_id
            LEFT JOIN (
                SELECT (item->>'product_id')::uuid AS product_id,
                       COUNT(DISTINCT pr.request_id) AS order_count
                FROM purchase_requests pr
                CROSS JOIN LATERAL jsonb_array_elements(pr.line_items) AS item
                WHERE pr.tenant_id = :tid
                  AND pr.created_at >= NOW() - INTERVAL '90 days'
                  AND pr.status NOT IN ('cancelled', 'rejected')
                  AND pr.line_items IS NOT NULL
                GROUP BY (item->>'product_id')
            ) cnt ON cnt.product_id = p.product_id
            WHERE p.tenant_id = :tid AND p.active
            GROUP BY c.name, p.product_id, p.display_name, p.sku, cnt.order_count
            ORDER BY c.name, order_count DESC
        """), {"tid": tenant_id})

        rows = result.fetchall()

        # Group by category
        categories_map: Dict[str, list] = {}
        for row in rows:
            cat = row[0] or "Uncategorised"
            if cat not in categories_map:
                categories_map[cat] = []
            categories_map[cat].append({
                "product_id":  row[1],
                "name":        row[2],
                "sku":         row[3],
                "order_count": int(row[4] or 0),
            })

        # Only include categories with 2+ products (substitution only makes sense then)
        categories = [
            {"category": cat, "product_count": len(prods), "products": prods[:10]}
            for cat, prods in sorted(categories_map.items())
            if len(prods) >= 2
        ]

        payload: Dict[str, Any] = {"categories": categories}
        confidence = 1.0 if categories else 0.3
        fact = DerivedFact(fact_type=FACT_PRODUCT_SUBSTITUTION, tenant_id=tenant_id,
                           payload=payload, confidence_score=confidence, is_complete=bool(categories))
        logger.info(f"[DerivedFact] product_substitution_map for {tenant_id}: {len(categories)} categories")
        return fact
    except Exception as exc:
        logger.warning(f"[DerivedFact] product_substitution_map failed: {exc}")
        return None
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_COMPUTERS = {
    FACT_TOP_CATEGORIES_BY_SPEND: compute_top_categories_by_spend,
    FACT_APPROVAL_POLICY_SUMMARY: compute_approval_policy_summary,
    FACT_ORG_UNIT_BUDGET_STATUS:  compute_org_unit_budget_status,
    FACT_VENDOR_ACTIVITY_SUMMARY: compute_vendor_activity_summary,
    FACT_APPROVED_PRODUCT_COUNT:  compute_approved_product_count,
    FACT_SUPPLIER_PERFORMANCE:    compute_supplier_performance,
    FACT_SUPPLIER_RISK:           compute_supplier_risk,
    FACT_SPEND_BY_DEPARTMENT:     compute_spend_by_department,
    FACT_PRODUCT_SUBSTITUTION:    compute_product_substitution_map,
}


def compute_and_save(tenant_id: str, fact_type: str) -> bool:
    from data_intelligence_service.intelligence.derived.store import save_fact
    computer = _COMPUTERS.get(fact_type)
    if not computer:
        logger.warning(f"[DerivedFact] Unknown fact type: {fact_type}")
        return False
    fact = computer(tenant_id)
    if fact is None:
        return False
    return save_fact(fact)
