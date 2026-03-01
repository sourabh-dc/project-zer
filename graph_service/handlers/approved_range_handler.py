"""
Handler: ApprovedRange events → Neo4j.

This is a governance-critical handler. It manages:
  (:ApprovedRange)-[:INCLUDES]->(:Product)
  (:OrgUnit)-[:GOVERNED_BY]->(:ApprovedRange)
  (:ApprovedRange {is_universal: true})  → applies to all org units

These edges drive the "Approved Universe" query — the set of
products a user is allowed to see/order based on their org unit.
"""
from graph_service.core.neo4j_client import get_session
from graph_service.core.logger import logger


def handle(event: dict):
    etype = event["event_type"]
    payload = event["payload"]
    aid = str(event["aggregate_id"])
    tid = str(event["tenant_id"])

    if etype == "approved_range.created":
        _create(tid, aid, payload)
    elif etype == "approved_range.updated":
        _update(aid, payload)
    elif etype == "approved_range.deleted":
        _soft_delete(aid)
    elif etype == "approved_range.org_units_mapped":
        _map_org_units(aid, payload)
    elif etype == "approved_range.org_unit_unmapped":
        _unmap_org_unit(aid, payload)
    elif etype == "approved_range.products_added":
        _add_products(aid, payload)
    elif etype == "approved_range.product_removed":
        _remove_product(aid, payload)


def _create(tenant_id: str, range_id: str, payload: dict):
    with get_session() as session:
        session.run(
            """
            MERGE (ar:ApprovedRange {approved_range_id: $rid})
            SET ar.name         = $name,
                ar.is_universal = $is_universal,
                ar.status       = 'active',
                ar.created_at   = datetime()
            WITH ar
            MATCH (t:Tenant {tenant_id: $tid})
            MERGE (t)-[:HAS_APPROVED_RANGE]->(ar)
            """,
            rid=range_id,
            tid=tenant_id,
            name=payload.get("name", ""),
            is_universal=payload.get("is_universal", False),
        )
    logger.info(f"Graph: ApprovedRange created {range_id}")


def _update(range_id: str, payload: dict):
    props = {k: v for k, v in payload.items()
             if v is not None and k not in ("approved_range_id", "tenant_id")}
    if not props:
        return
    set_clauses = ", ".join(f"ar.{k} = ${k}" for k in props)
    with get_session() as session:
        session.run(
            f"MATCH (ar:ApprovedRange {{approved_range_id: $rid}}) SET {set_clauses}, ar.updated_at = datetime()",
            rid=range_id,
            **props,
        )
    logger.info(f"Graph: ApprovedRange updated {range_id}")


def _soft_delete(range_id: str):
    with get_session() as session:
        session.run(
            """
            MATCH (ar:ApprovedRange {approved_range_id: $rid})
            SET ar.status = 'deleted', ar.deleted_at = datetime()
            """,
            rid=range_id,
        )
    logger.info(f"Graph: ApprovedRange soft-deleted {range_id}")


def _map_org_units(range_id: str, payload: dict):
    org_unit_ids = payload.get("org_unit_ids", [])
    with get_session() as session:
        for oid in org_unit_ids:
            session.run(
                """
                MATCH (d:OrgUnit {org_unit_id: $oid}),
                      (ar:ApprovedRange {approved_range_id: $rid})
                MERGE (d)-[:GOVERNED_BY]->(ar)
                """,
                oid=str(oid),
                rid=range_id,
            )
    logger.info(f"Graph: {len(org_unit_ids)} org units mapped to range {range_id}")


def _unmap_org_unit(range_id: str, payload: dict):
    org_unit_id = payload.get("org_unit_id")
    if not org_unit_id:
        return
    with get_session() as session:
        session.run(
            """
            MATCH (d:OrgUnit {org_unit_id: $oid})-[r:GOVERNED_BY]->(ar:ApprovedRange {approved_range_id: $rid})
            DELETE r
            """,
            oid=str(org_unit_id),
            rid=range_id,
        )
    logger.info(f"Graph: OrgUnit {org_unit_id} unmapped from range {range_id}")


def _add_products(range_id: str, payload: dict):
    """Add products to an approved range.

    This is the ONLY path through which Product nodes enter the graph.
    Products are MERGE'd (created if absent) so they exist for traversal.
    Product details (display_name, sku etc.) come from the event payload
    which the approved_range_routes endpoint includes when emitting.
    """
    product_ids = payload.get("product_ids", [])
    product_details = payload.get("product_details", {})
    tenant_id = payload.get("tenant_id", "")

    with get_session() as session:
        for pid in product_ids:
            pid_str = str(pid)
            details = product_details.get(pid_str, {})

            session.run(
                """
                MERGE (ar:ApprovedRange {approved_range_id: $rid})
                ON CREATE SET ar.status = 'active', ar.created_at = datetime()
                WITH ar
                MERGE (p:Product {product_id: $pid})
                ON CREATE SET p.display_name = $name,
                              p.sku          = $sku,
                              p.item_code    = $item_code,
                              p.status       = 'active',
                              p.created_at   = datetime()
                ON MATCH SET  p.updated_at   = datetime()
                WITH ar, p
                MERGE (ar)-[:INCLUDES]->(p)
                """,
                pid=pid_str,
                rid=range_id,
                name=details.get("display_name", ""),
                sku=details.get("sku", ""),
                item_code=details.get("item_code", ""),
            )

            if tenant_id:
                session.run(
                    """
                    MATCH (p:Product {product_id: $pid}), (t:Tenant {tenant_id: $tid})
                    MERGE (t)-[:HAS_PRODUCT]->(p)
                    """,
                    pid=pid_str,
                    tid=str(tenant_id),
                )

            cat_id = details.get("category_id")
            if cat_id:
                session.run(
                    """
                    MATCH (p:Product {product_id: $pid}), (c:Category {category_id: $cid})
                    MERGE (p)-[:IN_CATEGORY]->(c)
                    """,
                    pid=pid_str,
                    cid=str(cat_id),
                )

    logger.info(f"Graph: {len(product_ids)} products added to range {range_id} (nodes MERGE'd)")


def _remove_product(range_id: str, payload: dict):
    product_id = payload.get("product_id")
    if not product_id:
        return
    with get_session() as session:
        session.run(
            """
            MATCH (ar:ApprovedRange {approved_range_id: $rid})-[r:INCLUDES]->(p:Product {product_id: $pid})
            DELETE r
            """,
            rid=range_id,
            pid=str(product_id),
        )
    logger.info(f"Graph: Product {product_id} removed from range {range_id}")
