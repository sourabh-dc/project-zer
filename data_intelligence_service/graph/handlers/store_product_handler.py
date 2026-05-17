"""
Handler: StoreProduct events → Neo4j.

Manages the (:Store)-[:STOCKS]->(:Product) edge.
When a product is added to a store, create the STOCKS edge.
When removed, delete it.
"""
from data_intelligence_service.core.neo4j_client import get_session
from data_intelligence_service.core.logger import logger


def handle(event: dict):
    etype = event["event_type"]
    payload = event["payload"]

    if etype == "store_product.created":
        _add(payload)
    elif etype == "store_product.deleted":
        _remove(payload)


def _add(payload: dict):
    store_id = payload.get("store_id")
    product_id = payload.get("product_id")
    if not store_id or not product_id:
        return
    with get_session() as session:
        session.run(
            """
            MATCH (st:Store {store_id: $stid}), (p:Product {product_id: $pid})
            MERGE (st)-[:STOCKS]->(p)
            """,
            stid=str(store_id),
            pid=str(product_id),
        )
    logger.info(f"Graph: Store {store_id} now stocks product {product_id}")


def _remove(payload: dict):
    store_id = payload.get("store_id")
    product_id = payload.get("product_id")
    if not store_id or not product_id:
        return
    with get_session() as session:
        session.run(
            """
            MATCH (st:Store {store_id: $stid})-[r:STOCKS]->(p:Product {product_id: $pid})
            DELETE r
            """,
            stid=str(store_id),
            pid=str(product_id),
        )
    logger.info(f"Graph: Store {store_id} no longer stocks product {product_id}")
