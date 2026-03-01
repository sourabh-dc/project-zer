"""
Handler: OrgUnit events → Neo4j.

Manages :OrgUnit nodes and hierarchy:
  (:Tenant)-[:HAS_ORG_UNIT]->(:OrgUnit)
  (:OrgUnit)-[:CHILD_OF]->(:OrgUnit)
  (:User)-[:BELONGS_TO]->(:OrgUnit)
"""
from graph_service.core.neo4j_client import get_session
from graph_service.core.logger import logger


def handle(event: dict):
    action = event["event_type"].split(".")[-1]
    payload = event["payload"]
    oid = str(event["aggregate_id"])
    tid = str(event["tenant_id"])

    if action == "created":
        _create(tid, oid, payload)
    elif action == "updated":
        _update(oid, payload)
    elif action == "deleted":
        _soft_delete(oid)
    elif action == "assign_user":
        _assign_user(oid, payload)
    elif action == "remove_user":
        _remove_user(oid, payload)


def _create(tenant_id: str, org_unit_id: str, payload: dict):
    with get_session() as session:
        session.run(
            """
            MERGE (d:OrgUnit {org_unit_id: $oid})
            SET d.name       = $name,
                d.code       = $code,
                d.level      = $level,
                d.status     = 'active',
                d.created_at = datetime()
            WITH d
            MATCH (t:Tenant {tenant_id: $tid})
            MERGE (t)-[:HAS_ORG_UNIT]->(d)
            """,
            oid=org_unit_id,
            tid=tenant_id,
            name=payload.get("name", ""),
            code=payload.get("code", ""),
            level=payload.get("level", 0),
        )

        parent_id = payload.get("parent_org_unit_id")
        if parent_id:
            session.run(
                """
                MATCH (child:OrgUnit {org_unit_id: $cid}),
                      (parent:OrgUnit {org_unit_id: $pid})
                MERGE (child)-[:CHILD_OF]->(parent)
                """,
                cid=org_unit_id,
                pid=str(parent_id),
            )
    logger.info(f"Graph: OrgUnit created {org_unit_id}")


def _update(org_unit_id: str, payload: dict):
    props = {k: v for k, v in payload.items()
             if v is not None and k not in ("org_unit_id", "tenant_id", "parent_org_unit_id")}
    if props:
        set_clauses = ", ".join(f"d.{k} = ${k}" for k in props)
        with get_session() as session:
            session.run(
                f"MATCH (d:OrgUnit {{org_unit_id: $oid}}) SET {set_clauses}, d.updated_at = datetime()",
                oid=org_unit_id,
                **props,
            )

    new_parent = payload.get("parent_org_unit_id")
    if new_parent is not None:
        with get_session() as session:
            session.run(
                "MATCH (d:OrgUnit {org_unit_id: $oid})-[r:CHILD_OF]->() DELETE r",
                oid=org_unit_id,
            )
            if new_parent:
                session.run(
                    """
                    MATCH (child:OrgUnit {org_unit_id: $cid}),
                          (parent:OrgUnit {org_unit_id: $pid})
                    MERGE (child)-[:CHILD_OF]->(parent)
                    """,
                    cid=org_unit_id,
                    pid=str(new_parent),
                )
    logger.info(f"Graph: OrgUnit updated {org_unit_id}")


def _soft_delete(org_unit_id: str):
    with get_session() as session:
        session.run(
            "MATCH (d:OrgUnit {org_unit_id: $oid}) SET d.status = 'deleted', d.deleted_at = datetime()",
            oid=org_unit_id,
        )
    logger.info(f"Graph: OrgUnit soft-deleted {org_unit_id}")


def _assign_user(org_unit_id: str, payload: dict):
    user_id = payload.get("user_id")
    if not user_id:
        return
    with get_session() as session:
        session.run(
            """
            MATCH (u:User {user_id: $uid}), (d:OrgUnit {org_unit_id: $oid})
            MERGE (u)-[:BELONGS_TO]->(d)
            """,
            uid=str(user_id),
            oid=org_unit_id,
        )
    logger.info(f"Graph: User {user_id} assigned to OrgUnit {org_unit_id}")


def _remove_user(org_unit_id: str, payload: dict):
    user_id = payload.get("user_id")
    if not user_id:
        return
    with get_session() as session:
        session.run(
            """
            MATCH (u:User {user_id: $uid})-[r:BELONGS_TO]->(d:OrgUnit {org_unit_id: $oid})
            DELETE r
            """,
            uid=str(user_id),
            oid=org_unit_id,
        )
    logger.info(f"Graph: User {user_id} removed from OrgUnit {org_unit_id}")
