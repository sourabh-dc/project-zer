"""
Handler: Site events → Neo4j.

Manages :Site nodes:
  (:Tenant)-[:HAS_SITE]->(:Site)
  (:Site)-[:HAS_STORE]->(:Store)
"""
from data_intelligence_service.core.neo4j_client import get_session
from data_intelligence_service.core.logger import logger


def handle(event: dict):
    action = event["event_type"].split(".")[-1]
    payload = event["payload"]
    tid = str(event["tenant_id"])
    sid = str(event["aggregate_id"])

    if action == "created":
        _create(tid, sid, payload)
    elif action == "updated":
        _update(sid, payload)
    elif action == "deleted":
        _soft_delete(sid)


def _create(tenant_id: str, site_id: str, payload: dict):
    with get_session() as session:
        session.run(
            """
            MERGE (s:Site {site_id: $sid})
            SET s.name      = $name,
                s.site_type = $site_type,
                s.currency  = $currency,
                s.timezone  = $timezone,
                s.geo       = $geo,
                s.status    = 'active',
                s.created_at = datetime()
            WITH s
            MATCH (t:Tenant {tenant_id: $tid})
            MERGE (t)-[:HAS_SITE]->(s)
            """,
            sid=site_id,
            tid=tenant_id,
            name=payload.get("name", ""),
            site_type=payload.get("site_type", ""),
            currency=payload.get("currency", ""),
            timezone=payload.get("timezone", ""),
            geo=payload.get("geo", ""),
        )
    logger.info(f"Graph: Site created {site_id}")


def _update(site_id: str, payload: dict):
    props = {k: v for k, v in payload.items() if v is not None and k not in ("site_id", "tenant_id")}
    if not props:
        return
    set_clauses = ", ".join(f"s.{k} = ${k}" for k in props)
    with get_session() as session:
        session.run(
            f"MATCH (s:Site {{site_id: $sid}}) SET {set_clauses}, s.updated_at = datetime()",
            sid=site_id,
            **props,
        )
    logger.info(f"Graph: Site updated {site_id}")


def _soft_delete(site_id: str):
    with get_session() as session:
        session.run(
            "MATCH (s:Site {site_id: $sid}) SET s.status = 'deleted', s.deleted_at = datetime()",
            sid=site_id,
        )
    logger.info(f"Graph: Site soft-deleted {site_id}")
