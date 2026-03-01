"""
Graph Query: Approved Universe.

Given a user (or their org unit), returns the set of product IDs
they are allowed to see/order. This is the graph-native replacement
for the SQL-based approved_product_ids in the context enricher.

Traversal:
  (:User)-[:BELONGS_TO]->(:OrgUnit)-[:GOVERNED_BY]->(:ApprovedRange)-[:INCLUDES]->(:Product)
  UNION
  (:ApprovedRange {is_universal: true})-[:INCLUDES]->(:Product)

For tenant admins: returns '__all__' (bypass).
"""
from typing import List, Union

from graph_service.core.neo4j_client import get_session
from graph_service.core.logger import logger


def get_approved_product_ids(
    tenant_id: str,
    user_id: str,
    org_unit_id: str | None = None,
    is_admin: bool = False,
) -> Union[str, List[str]]:
    """Return product IDs the user may access.

    Returns '__all__' for admin users, or a list of product ID strings.
    """
    if is_admin:
        return "__all__"

    with get_session() as session:
        result = session.run(
            """
            // Products from org-unit-specific approved ranges
            MATCH (u:User {user_id: $uid})-[:BELONGS_TO]->(d:OrgUnit)
                  -[:GOVERNED_BY]->(ar:ApprovedRange {status: 'active'})
                  -[:INCLUDES]->(p:Product {status: 'active'})
            WHERE ar.is_universal = false
            RETURN DISTINCT p.product_id AS pid

            UNION

            // Products from universal approved ranges (same tenant)
            MATCH (t:Tenant {tenant_id: $tid})-[:HAS_APPROVED_RANGE]->(ar:ApprovedRange {status: 'active', is_universal: true})
                  -[:INCLUDES]->(p:Product {status: 'active'})
            RETURN DISTINCT p.product_id AS pid
            """,
            uid=user_id,
            tid=tenant_id,
        )
        product_ids = [record["pid"] for record in result]

    logger.debug(f"Approved universe for user {user_id}: {len(product_ids)} products")
    return product_ids


def get_approved_product_ids_for_org_unit(
    tenant_id: str,
    org_unit_id: str,
) -> List[str]:
    """Return product IDs approved for a specific org unit (includes universal)."""
    with get_session() as session:
        result = session.run(
            """
            MATCH (d:OrgUnit {org_unit_id: $oid})
                  -[:GOVERNED_BY]->(ar:ApprovedRange {status: 'active'})
                  -[:INCLUDES]->(p:Product {status: 'active'})
            RETURN DISTINCT p.product_id AS pid

            UNION

            MATCH (t:Tenant {tenant_id: $tid})-[:HAS_APPROVED_RANGE]->(ar:ApprovedRange {status: 'active', is_universal: true})
                  -[:INCLUDES]->(p:Product {status: 'active'})
            RETURN DISTINCT p.product_id AS pid
            """,
            oid=org_unit_id,
            tid=tenant_id,
        )
        return [record["pid"] for record in result]
