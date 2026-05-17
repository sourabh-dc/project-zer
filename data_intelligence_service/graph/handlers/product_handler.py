"""
Handler: Product events → Neo4j.

IMPORTANT RULE: Products are NOT projected to the graph on creation.
Only products that are part of an approved range appear in Neo4j.
The approved_range_handler creates :Product nodes when products are
added to a range (via INCLUDES edge).

This handler only manages property updates and soft-deletes for
products that already exist in the graph (i.e., were previously
added to an approved range).

Relationships managed:
  (:Product)-[:IN_CATEGORY]->(:Category)
  (:Vendor)-[:SUPPLIES]->(:Product)
  (:ApprovedRange)-[:INCLUDES]->(:Product)  [managed by approved_range_handler]
"""
from data_intelligence_service.core.neo4j_client import get_session
from data_intelligence_service.core.logger import logger


def handle(event: dict):
    etype = event["event_type"]
    action = etype.split(".")[-1]
    payload = event["payload"]
    pid = str(event["aggregate_id"])
    tid = str(event["tenant_id"])

    if action == "created":
        # Products do NOT go to graph on creation.
        # They enter the graph only via approved_range_handler (products_added).
        logger.debug(f"Graph: Product {pid} created in Postgres — skipped (graph entry via approved range only)")
        return
    elif action == "updated":
        _update_if_exists(pid, payload)
    elif action == "deleted":
        _soft_delete_if_exists(pid)


def _update_if_exists(product_id: str, payload: dict):
    """Update a product node only if it already exists in the graph."""
    with get_session() as session:
        exists = session.run(
            "MATCH (p:Product {product_id: $pid}) RETURN p.product_id AS pid LIMIT 1",
            pid=product_id,
        ).single()

        if not exists:
            logger.debug(f"Graph: Product {product_id} not in graph — update skipped")
            return

    scalar_props = {k: v for k, v in payload.items()
                    if v is not None and k not in ("product_id", "tenant_id", "category_id", "vendor_id")}
    if scalar_props:
        set_clauses = ", ".join(f"p.{k} = ${k}" for k in scalar_props)
        with get_session() as session:
            session.run(
                f"MATCH (p:Product {{product_id: $pid}}) SET {set_clauses}, p.updated_at = datetime()",
                pid=product_id,
                **scalar_props,
            )

    new_cat = payload.get("category_id")
    if new_cat is not None:
        with get_session() as session:
            session.run("MATCH (p:Product {product_id: $pid})-[r:IN_CATEGORY]->() DELETE r", pid=product_id)
            if new_cat:
                session.run(
                    """
                    MATCH (p:Product {product_id: $pid}), (c:Category {category_id: $cid})
                    MERGE (p)-[:IN_CATEGORY]->(c)
                    """,
                    pid=product_id,
                    cid=str(new_cat),
                )

    new_vendor = payload.get("vendor_id")
    if new_vendor is not None:
        with get_session() as session:
            session.run("MATCH ()-[r:SUPPLIES]->(p:Product {product_id: $pid}) DELETE r", pid=product_id)
            if new_vendor:
                session.run(
                    """
                    MATCH (p:Product {product_id: $pid}), (v:Vendor {vendor_id: $vid})
                    MERGE (v)-[:SUPPLIES]->(p)
                    """,
                    pid=product_id,
                    vid=str(new_vendor),
                )

    logger.info(f"Graph: Product {product_id} updated (was in approved range)")


def _soft_delete_if_exists(product_id: str):
    """Soft-delete a product node only if it exists in the graph."""
    with get_session() as session:
        result = session.run(
            """
            MATCH (p:Product {product_id: $pid})
            SET p.status = 'deleted', p.deleted_at = datetime()
            RETURN p.product_id AS pid
            """,
            pid=product_id,
        ).single()

    if result:
        logger.info(f"Graph: Product {product_id} soft-deleted (was in approved range)")
    else:
        logger.debug(f"Graph: Product {product_id} not in graph — delete skipped")
