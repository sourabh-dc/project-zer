"""
Handler: CostCentre events → Neo4j.

Manages :CostCentre nodes:
  (:Tenant)-[:HAS_COST_CENTRE]->(:CostCentre)
  (:User)-[:MANAGES]->(:CostCentre)  [owner]
  (:User)-[:ASSIGNED_TO_CC]->(:CostCentre)
"""
from graph_service.core.neo4j_client import get_session
from graph_service.core.logger import logger


def handle(event: dict):
    etype = event["event_type"]
    action = etype.split(".")[-1]
    payload = event["payload"]
    ccid = str(event["aggregate_id"])
    tid = str(event["tenant_id"])

    if action == "created":
        _create(tid, ccid, payload)
    elif action == "updated":
        _update(ccid, payload)
    elif action == "deleted":
        _soft_delete(ccid)
    elif action == "assign_user" or etype == "cost_centre.user_assigned":
        _assign_user(ccid, payload)


def _create(tenant_id: str, cc_id: str, payload: dict):
    with get_session() as session:
        session.run(
            """
            MERGE (cc:CostCentre {cost_centre_id: $ccid})
            SET cc.name       = $name,
                cc.code       = $code,
                cc.status     = 'active',
                cc.created_at = datetime()
            WITH cc
            MATCH (t:Tenant {tenant_id: $tid})
            MERGE (t)-[:HAS_COST_CENTRE]->(cc)
            """,
            ccid=cc_id,
            tid=tenant_id,
            name=payload.get("name", ""),
            code=payload.get("code", ""),
        )

        owner_id = payload.get("owner_user_id")
        if owner_id:
            session.run(
                """
                MATCH (u:User {user_id: $uid}), (cc:CostCentre {cost_centre_id: $ccid})
                MERGE (u)-[:MANAGES]->(cc)
                """,
                uid=str(owner_id),
                ccid=cc_id,
            )
    logger.info(f"Graph: CostCentre created {cc_id}")


def _update(cc_id: str, payload: dict):
    props = {k: v for k, v in payload.items()
             if v is not None and k not in ("cost_centre_id", "tenant_id", "owner_user_id")}
    if props:
        set_clauses = ", ".join(f"cc.{k} = ${k}" for k in props)
        with get_session() as session:
            session.run(
                f"MATCH (cc:CostCentre {{cost_centre_id: $ccid}}) SET {set_clauses}, cc.updated_at = datetime()",
                ccid=cc_id,
                **props,
            )

    new_owner = payload.get("owner_user_id")
    if new_owner is not None:
        with get_session() as session:
            session.run("MATCH ()-[r:MANAGES]->(cc:CostCentre {cost_centre_id: $ccid}) DELETE r", ccid=cc_id)
            if new_owner:
                session.run(
                    """
                    MATCH (u:User {user_id: $uid}), (cc:CostCentre {cost_centre_id: $ccid})
                    MERGE (u)-[:MANAGES]->(cc)
                    """,
                    uid=str(new_owner),
                    ccid=cc_id,
                )
    logger.info(f"Graph: CostCentre updated {cc_id}")


def _soft_delete(cc_id: str):
    with get_session() as session:
        session.run(
            "MATCH (cc:CostCentre {cost_centre_id: $ccid}) SET cc.status = 'deleted', cc.deleted_at = datetime()",
            ccid=cc_id,
        )
    logger.info(f"Graph: CostCentre soft-deleted {cc_id}")


def _assign_user(cc_id: str, payload: dict):
    user_id = payload.get("user_id")
    if not user_id:
        return
    with get_session() as session:
        session.run(
            """
            MATCH (u:User {user_id: $uid}), (cc:CostCentre {cost_centre_id: $ccid})
            MERGE (u)-[:ASSIGNED_TO_CC]->(cc)
            """,
            uid=str(user_id),
            ccid=cc_id,
        )
    logger.info(f"Graph: User {user_id} assigned to CostCentre {cc_id}")
