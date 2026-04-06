"""
graph_service.handlers
----------------------
Event handlers that project Postgres entities into Neo4j graph topology.

Each handler receives an event dict and executes Cypher to create/update
nodes and relationships.

Topology:
    (Tenant) -[:HAS_SITE]-> (Site) -[:HAS_STORE]-> (Store)
    (Tenant) -[:HAS_USER]-> (User)
    (Tenant) -[:HAS_VENDOR]-> (Vendor)
    (Tenant) -[:HAS_COST_CENTRE]-> (CostCentre)
    (Tenant) -[:HAS_ORG_UNIT]-> (OrgUnit)
    (User) -[:HAS_ROLE]-> (Role)
    (User) -[:BELONGS_TO]-> (OrgUnit)
    (User) -[:MANAGES]-> (CostCentre)
"""
import logging
from typing import Any, Dict

from graph_service.neo4j_client import run_cypher

logger = logging.getLogger("graph_service.handlers")

_HANDLERS = {}


def _register(prefix: str):
    def decorator(fn):
        _HANDLERS[prefix] = fn
        return fn
    return decorator


def dispatch(event: Dict[str, Any]) -> bool:
    """Route event to the correct handler. Returns True if handled."""
    event_type = event.get("event_type", "")
    prefix = event_type.split(".")[0]

    handler = _HANDLERS.get(prefix)
    if not handler:
        logger.debug(f"No graph handler for '{event_type}'")
        return False

    handler(event)
    return True


# ── Handlers ──────────────────────────────────────────────────────────

@_register("tenant")
def handle_tenant(event: Dict[str, Any]):
    payload = event.get("payload", {})
    action = event["event_type"].split(".")[-1]
    tenant_id = event.get("tenant_id") or payload.get("tenant_id")

    if action in ("signup", "created"):
        run_cypher(
            """
            MERGE (t:Tenant {tenant_id: $tenant_id})
            SET t.name = $name,
                t.type = $type,
                t.email = $email,
                t.org_id = $org_id,
                t.updated_at = datetime()
            """,
            {
                "tenant_id": tenant_id,
                "name": payload.get("tenant_name", ""),
                "type": payload.get("type", ""),
                "email": payload.get("email", ""),
                "org_id": payload.get("org_id", ""),
            },
        )
        logger.info(f"Graph: tenant MERGE {tenant_id}")


@_register("site")
def handle_site(event: Dict[str, Any]):
    payload = event.get("payload", {})
    tenant_id = event.get("tenant_id") or payload.get("tenant_id")
    site_id = payload.get("site_id")

    run_cypher(
        """
        MERGE (t:Tenant {tenant_id: $tenant_id})
        MERGE (s:Site {site_id: $site_id})
        SET s.name = $name, s.site_type = $site_type, s.updated_at = datetime()
        MERGE (t)-[:HAS_SITE]->(s)
        """,
        {
            "site_id": site_id,
            "name": payload.get("name", ""),
            "site_type": payload.get("site_type", payload.get("type", "")),
            "tenant_id": tenant_id,
        },
    )
    logger.info(f"Graph: site MERGE {site_id}")


@_register("store")
def handle_store(event: Dict[str, Any]):
    payload = event.get("payload", {})
    tenant_id = event.get("tenant_id") or payload.get("tenant_id")
    store_id = payload.get("store_id")
    site_id = payload.get("site_id")

    run_cypher(
        """
        MERGE (s:Site {site_id: $site_id})
        MERGE (st:Store {store_id: $store_id})
        SET st.name = $name, st.store_type = $store_type, st.updated_at = datetime()
        MERGE (s)-[:HAS_STORE]->(st)
        """,
        {
            "store_id": store_id,
            "name": payload.get("name", ""),
            "store_type": payload.get("store_type", ""),
            "site_id": site_id,
        },
    )
    logger.info(f"Graph: store MERGE {store_id}")


@_register("user")
def handle_user(event: Dict[str, Any]):
    payload = event.get("payload", {})
    tenant_id = event.get("tenant_id") or payload.get("tenant_id")
    user_id = payload.get("user_id")

    run_cypher(
        """
        MERGE (t:Tenant {tenant_id: $tenant_id})
        MERGE (u:User {user_id: $user_id})
        SET u.email = $email,
            u.name = $name,
            u.first_name = $first_name,
            u.last_name = $last_name,
            u.updated_at = datetime()
        MERGE (t)-[:HAS_USER]->(u)
        """,
        {
            "user_id": user_id,
            "email": payload.get("email", ""),
            "name": payload.get("display_name", payload.get("first_name", "")),
            "first_name": payload.get("first_name", ""),
            "last_name": payload.get("last_name", ""),
            "tenant_id": tenant_id,
        },
    )
    logger.info(f"Graph: user MERGE {user_id}")

    roles = payload.get("roles", [])
    for role_code in roles:
        run_cypher(
            """
            MERGE (u:User {user_id: $user_id})
            MERGE (r:Role {code: $role_code})
            SET r.name = $role_code, r.updated_at = datetime()
            MERGE (u)-[:HAS_ROLE]->(r)
            """,
            {"user_id": user_id, "role_code": role_code},
        )
        logger.info(f"Graph: user {user_id} -[:HAS_ROLE]-> {role_code}")


@_register("vendor")
def handle_vendor(event: Dict[str, Any]):
    payload = event.get("payload", {})
    tenant_id = event.get("tenant_id") or payload.get("tenant_id")
    vendor_id = payload.get("vendor_id")

    run_cypher(
        """
        MERGE (t:Tenant {tenant_id: $tenant_id})
        MERGE (v:Vendor {vendor_id: $vendor_id})
        SET v.name = $name, v.updated_at = datetime()
        MERGE (t)-[:HAS_VENDOR]->(v)
        """,
        {"vendor_id": vendor_id, "name": payload.get("name", ""), "tenant_id": tenant_id},
    )
    logger.info(f"Graph: vendor MERGE {vendor_id}")


@_register("cost_centre")
def handle_cost_centre(event: Dict[str, Any]):
    payload = event.get("payload", {})
    tenant_id = event.get("tenant_id") or payload.get("tenant_id")
    cc_id = payload.get("cost_centre_id")

    run_cypher(
        """
        MERGE (t:Tenant {tenant_id: $tenant_id})
        MERGE (cc:CostCentre {cost_centre_id: $cc_id})
        SET cc.name = $name, cc.updated_at = datetime()
        MERGE (t)-[:HAS_COST_CENTRE]->(cc)
        """,
        {"cc_id": cc_id, "name": payload.get("name", ""), "tenant_id": tenant_id},
    )
    logger.info(f"Graph: cost_centre MERGE {cc_id}")


@_register("org_unit")
def handle_org_unit(event: Dict[str, Any]):
    payload = event.get("payload", {})
    tenant_id = event.get("tenant_id") or payload.get("tenant_id")
    ou_id = payload.get("org_unit_id")

    run_cypher(
        """
        MERGE (t:Tenant {tenant_id: $tenant_id})
        MERGE (ou:OrgUnit {org_unit_id: $ou_id})
        SET ou.name = $name, ou.type = $type, ou.updated_at = datetime()
        MERGE (t)-[:HAS_ORG_UNIT]->(ou)
        """,
        {
            "ou_id": ou_id,
            "name": payload.get("name", ""),
            "type": payload.get("type", ""),
            "tenant_id": tenant_id,
        },
    )
    logger.info(f"Graph: org_unit MERGE {ou_id}")


@_register("role")
def handle_role(event: Dict[str, Any]):
    payload = event.get("payload", {})
    role_id = payload.get("role_id")

    run_cypher(
        """
        MERGE (r:Role {role_id: $role_id})
        SET r.code = $code, r.description = $desc, r.updated_at = datetime()
        """,
        {
            "role_id": role_id,
            "code": payload.get("code", ""),
            "desc": payload.get("description", ""),
        },
    )
    logger.info(f"Graph: role MERGE {role_id}")


@_register("user_role")
def handle_user_role(event: Dict[str, Any]):
    payload = event.get("payload", {})
    user_id = payload.get("user_id")
    role_id = payload.get("role_id")

    run_cypher(
        """
        MATCH (u:User {user_id: $user_id})
        MATCH (r:Role {role_id: $role_id})
        MERGE (u)-[:HAS_ROLE]->(r)
        """,
        {"user_id": user_id, "role_id": role_id},
    )
    logger.info(f"Graph: user_role {user_id} → {role_id}")


@_register("product")
def handle_product(event: Dict[str, Any]):
    payload = event.get("payload", {})
    tenant_id = event.get("tenant_id") or payload.get("tenant_id")
    product_id = payload.get("product_id")

    run_cypher(
        """
        MERGE (t:Tenant {tenant_id: $tenant_id})
        MERGE (p:Product {product_id: $product_id})
        SET p.name = $name, p.sku = $sku, p.updated_at = datetime()
        MERGE (t)-[:HAS_PRODUCT]->(p)
        """,
        {
            "product_id": product_id,
            "name": payload.get("name", ""),
            "sku": payload.get("sku", ""),
            "tenant_id": tenant_id,
        },
    )
    logger.info(f"Graph: product MERGE {product_id}")
