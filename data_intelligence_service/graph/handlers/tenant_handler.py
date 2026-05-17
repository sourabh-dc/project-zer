"""
Handler: Tenant events → Neo4j.

Manages :Tenant nodes and their relationships:
  (:Tenant)-[:HAS_SITE]->(:Site)
  (:Tenant)-[:SUBSCRIBES_TO]->(:Plan)
"""
from data_intelligence_service.core.neo4j_client import get_session
from data_intelligence_service.core.logger import logger


def handle(event: dict):
    action = event["event_type"].split(".")[-1]  # created | updated | deleted
    payload = event["payload"]
    tid = str(event["tenant_id"])

    if action == "created":
        _create_tenant(tid, payload)
    elif action == "updated":
        _update_tenant(tid, payload)
    elif action == "deleted":
        _soft_delete_tenant(tid)
    else:
        logger.debug(f"Unhandled tenant action: {action}")


def _create_tenant(tenant_id: str, payload: dict):
    with get_session() as session:
        session.run(
            """
            MERGE (t:Tenant {tenant_id: $tid})
            SET t.name       = $name,
                t.domain     = $domain,
                t.status     = 'active',
                t.created_at = datetime()
            """,
            tid=tenant_id,
            name=payload.get("name", ""),
            domain=payload.get("domain", ""),
        )
    logger.info(f"Graph: Tenant created {tenant_id}")


def _update_tenant(tenant_id: str, payload: dict):
    props = {k: v for k, v in payload.items() if k not in ("tenant_id",) and v is not None}
    if not props:
        return
    set_clauses = ", ".join(f"t.{k} = ${k}" for k in props)
    with get_session() as session:
        session.run(
            f"MATCH (t:Tenant {{tenant_id: $tid}}) SET {set_clauses}, t.updated_at = datetime()",
            tid=tenant_id,
            **props,
        )
    logger.info(f"Graph: Tenant updated {tenant_id}")


def _soft_delete_tenant(tenant_id: str):
    with get_session() as session:
        session.run(
            """
            MATCH (t:Tenant {tenant_id: $tid})
            SET t.status = 'deleted', t.deleted_at = datetime()
            """,
            tid=tenant_id,
        )
    logger.info(f"Graph: Tenant soft-deleted {tenant_id}")
