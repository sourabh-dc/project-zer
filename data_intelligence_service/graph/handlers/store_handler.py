"""
Handler: Store events → Neo4j.

Manages :Store nodes:
  (:Site)-[:HAS_STORE]->(:Store)
  (:Store)-[:STOCKS]->(:Product)
"""
from data_intelligence_service.core.neo4j_client import get_session
from data_intelligence_service.core.logger import logger


def handle(event: dict):
    action = event["event_type"].split(".")[-1]
    payload = event["payload"]
    store_id = str(event["aggregate_id"])

    if action == "created":
        _create(store_id, payload)
    elif action == "updated":
        _update(store_id, payload)
    elif action == "deleted":
        _soft_delete(store_id)


def _create(store_id: str, payload: dict):
    site_id = payload.get("site_id", "")
    with get_session() as session:
        session.run(
            """
            MERGE (st:Store {store_id: $stid})
            SET st.name        = $name,
                st.store_type  = $store_type,
                st.geo         = $geo,
                st.status      = 'active',
                st.created_at  = datetime()
            WITH st
            MATCH (s:Site {site_id: $sid})
            MERGE (s)-[:HAS_STORE]->(st)
            """,
            stid=store_id,
            sid=str(site_id),
            name=payload.get("name", ""),
            store_type=payload.get("store_type", ""),
            geo=payload.get("geo", ""),
        )
    logger.info(f"Graph: Store created {store_id}")


def _update(store_id: str, payload: dict):
    props = {k: v for k, v in payload.items() if v is not None and k not in ("store_id", "tenant_id", "site_id")}
    if not props:
        return
    set_clauses = ", ".join(f"st.{k} = ${k}" for k in props)
    with get_session() as session:
        session.run(
            f"MATCH (st:Store {{store_id: $stid}}) SET {set_clauses}, st.updated_at = datetime()",
            stid=store_id,
            **props,
        )
    logger.info(f"Graph: Store updated {store_id}")


def _soft_delete(store_id: str):
    with get_session() as session:
        session.run(
            "MATCH (st:Store {store_id: $stid}) SET st.status = 'deleted', st.deleted_at = datetime()",
            stid=store_id,
        )
    logger.info(f"Graph: Store soft-deleted {store_id}")
