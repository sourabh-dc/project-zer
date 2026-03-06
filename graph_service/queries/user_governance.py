"""
Graph Query: User Governance Context.

Resolves the full governance context for a user from the graph:
  - Roles and permissions (via HAS_ROLE → GRANTS)
  - Org units (via BELONGS_TO)
  - Cost centres (via ASSIGNED_TO_CC / MANAGES)
  - Applicable policies (via org unit → policy assignments)
  - Budget/entitlement info (stored as node properties)

This replaces multiple SQL joins in the context enricher with
a single graph traversal.
"""
from typing import Dict, Any, List

from graph_service.core.neo4j_client import get_session
from graph_service.core.logger import logger


def get_user_context(user_id: str, tenant_id: str) -> Dict[str, Any]:
    """Build a governance context dict for the user from the graph."""
    ctx: Dict[str, Any] = {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "roles": [],
        "permissions": [],
        "org_units": [],
        "cost_centres": [],
        "policies": [],
    }

    with get_session() as session:
        # Roles
        roles_result = session.run(
            """
            MATCH (u:User {user_id: $uid})-[:HAS_ROLE]->(r:Role {status: 'active'})
            RETURN r.role_id AS role_id, r.code AS code, r.name AS name
            """,
            uid=user_id,
        )
        ctx["roles"] = [dict(rec) for rec in roles_result]

        # Permissions (via roles)
        perms_result = session.run(
            """
            MATCH (u:User {user_id: $uid})-[:HAS_ROLE]->(r:Role)-[:GRANTS]->(p:Permission)
            RETURN DISTINCT p.code AS code
            """,
            uid=user_id,
        )
        ctx["permissions"] = [rec["code"] for rec in perms_result]

        # Org units
        orgs_result = session.run(
            """
            MATCH (u:User {user_id: $uid})-[:BELONGS_TO]->(d:OrgUnit {status: 'active'})
            RETURN d.org_unit_id AS org_unit_id, d.name AS name, d.code AS code
            """,
            uid=user_id,
        )
        ctx["org_units"] = [dict(rec) for rec in orgs_result]

        # Cost centres
        cc_result = session.run(
            """
            MATCH (u:User {user_id: $uid})-[:ASSIGNED_TO_CC|MANAGES]->(cc:CostCentre {status: 'active'})
            RETURN cc.cost_centre_id AS cost_centre_id, cc.name AS name, cc.code AS code,
                   type(head([(u)-[r]->(cc) | r])) AS relationship
            """,
            uid=user_id,
        )
        ctx["cost_centres"] = [dict(rec) for rec in cc_result]

        # Policies that apply via org unit or tenant
        policies_result = session.run(
            """
            MATCH (u:User {user_id: $uid})-[:BELONGS_TO]->(d:OrgUnit)
                  <-[:ASSIGNED_TO]-(p:Policy {status: 'active'})
            RETURN DISTINCT p.policy_id AS policy_id, p.code AS code, p.name AS name

            UNION

            MATCH (t:Tenant {tenant_id: $tid})<-[:ASSIGNED_TO]-(p:Policy {status: 'active'})
            RETURN DISTINCT p.policy_id AS policy_id, p.code AS code, p.name AS name

            UNION

            MATCH (u:User {user_id: $uid})-[:HAS_ROLE]->(r:Role)
                  <-[:ASSIGNED_TO]-(p:Policy {status: 'active'})
            RETURN DISTINCT p.policy_id AS policy_id, p.code AS code, p.name AS name
            """,
            uid=user_id,
            tid=tenant_id,
        )
        ctx["policies"] = [dict(rec) for rec in policies_result]

    logger.debug(f"Graph context for user {user_id}: {len(ctx['roles'])} roles, "
                 f"{len(ctx['permissions'])} perms, {len(ctx['org_units'])} orgs, "
                 f"{len(ctx['policies'])} policies")
    return ctx


def get_user_hierarchy(user_id: str) -> List[Dict[str, Any]]:
    """Return the org unit hierarchy chain for a user (leaf → root)."""
    with get_session() as session:
        result = session.run(
            """
            MATCH (u:User {user_id: $uid})-[:BELONGS_TO]->(d:OrgUnit)
            MATCH path = (d)-[:CHILD_OF*0..10]->(root:OrgUnit)
            WHERE NOT (root)-[:CHILD_OF]->()
            RETURN [n IN nodes(path) |
                    {org_unit_id: n.org_unit_id, name: n.name, code: n.code, level: n.level}
                   ] AS chain
            ORDER BY length(path) DESC
            LIMIT 1
            """,
            uid=user_id,
        )
        record = result.single()
        return record["chain"] if record else []
