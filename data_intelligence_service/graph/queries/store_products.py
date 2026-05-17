"""
Graph Query: Store → Product relationships.

Answers: "What products does this store stock?"
and "Which stores carry this product?"
"""
from typing import List, Dict, Any

from data_intelligence_service.core.neo4j_client import get_session


def get_products_for_store(store_id: str) -> List[str]:
    """Return product IDs stocked by a store."""
    with get_session() as session:
        result = session.run(
            """
            MATCH (st:Store {store_id: $stid, status: 'active'})-[:STOCKS]->(p:Product {status: 'active'})
            RETURN p.product_id AS pid
            """,
            stid=store_id,
        )
        return [rec["pid"] for rec in result]


def get_stores_for_product(product_id: str) -> List[str]:
    """Return store IDs that stock a product."""
    with get_session() as session:
        result = session.run(
            """
            MATCH (st:Store {status: 'active'})-[:STOCKS]->(p:Product {product_id: $pid, status: 'active'})
            RETURN st.store_id AS stid
            """,
            pid=product_id,
        )
        return [rec["stid"] for rec in result]


def get_tenant_topology(tenant_id: str) -> Dict[str, Any]:
    """Return a full tenant topology snapshot.

    Useful for dashboards: sites → stores, org units, user counts.
    """
    with get_session() as session:
        result = session.run(
            """
            MATCH (t:Tenant {tenant_id: $tid})
            OPTIONAL MATCH (t)-[:HAS_SITE]->(s:Site {status: 'active'})
            OPTIONAL MATCH (s)-[:HAS_STORE]->(st:Store {status: 'active'})
            OPTIONAL MATCH (t)-[:HAS_ORG_UNIT]->(d:OrgUnit {status: 'active'})
            OPTIONAL MATCH (t)-[:HAS_USER]->(u:User {status: 'active'})
            RETURN t.name AS tenant_name,
                   count(DISTINCT s) AS site_count,
                   count(DISTINCT st) AS store_count,
                   count(DISTINCT d) AS org_unit_count,
                   count(DISTINCT u) AS user_count
            """,
            tid=tenant_id,
        )
        rec = result.single()
        if not rec:
            return {}
        return dict(rec)
