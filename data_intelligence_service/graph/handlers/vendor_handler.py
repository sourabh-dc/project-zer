"""
Handler: Vendor events → Neo4j.

Manages :Vendor nodes:
  (:Tenant)-[:HAS_VENDOR]->(:Vendor)
  (:Vendor)-[:SUPPLIES]->(:Product)
"""
from data_intelligence_service.core.neo4j_client import get_session
from data_intelligence_service.core.logger import logger


def handle(event: dict):
    action = event["event_type"].split(".")[-1]
    payload = event["payload"]
    vid = str(event["aggregate_id"])
    tid = str(event["tenant_id"])

    if action == "created":
        _create(tid, vid, payload)
    elif action == "updated":
        _update(vid, payload)
    elif action == "deleted":
        _soft_delete(vid)


def _create(tenant_id: str, vendor_id: str, payload: dict):
    with get_session() as session:
        session.run(
            """
            MERGE (v:Vendor {vendor_id: $vid})
            SET v.name          = $name,
                v.contact_email = $email,
                v.status        = 'active',
                v.created_at    = datetime()
            WITH v
            MATCH (t:Tenant {tenant_id: $tid})
            MERGE (t)-[:HAS_VENDOR]->(v)
            """,
            vid=vendor_id,
            tid=tenant_id,
            name=payload.get("name", ""),
            email=payload.get("contact_email", ""),
        )
    logger.info(f"Graph: Vendor created {vendor_id}")


def _update(vendor_id: str, payload: dict):
    props = {k: v for k, v in payload.items()
             if v is not None and k not in ("vendor_id", "tenant_id")}
    if not props:
        return
    set_clauses = ", ".join(f"v.{k} = ${k}" for k in props)
    with get_session() as session:
        session.run(
            f"MATCH (v:Vendor {{vendor_id: $vid}}) SET {set_clauses}, v.updated_at = datetime()",
            vid=vendor_id,
            **props,
        )
    logger.info(f"Graph: Vendor updated {vendor_id}")


def _soft_delete(vendor_id: str):
    with get_session() as session:
        session.run(
            "MATCH (v:Vendor {vendor_id: $vid}) SET v.status = 'deleted', v.deleted_at = datetime()",
            vid=vendor_id,
        )
    logger.info(f"Graph: Vendor soft-deleted {vendor_id}")
