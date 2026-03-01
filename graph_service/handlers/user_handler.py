"""
Handler: User events → Neo4j.

Manages :User nodes and edges:
  (:User)-[:BELONGS_TO]->(:OrgUnit)
  (:User)-[:HAS_ROLE]->(:Role)
  (:User)-[:WORKS_AT]->(:Store)
  (:User)-[:REPORTS_TO]->(:User)   [via org hierarchy]
"""
from graph_service.core.neo4j_client import get_session
from graph_service.core.logger import logger


def handle(event: dict):
    action = event["event_type"].split(".")[-1]
    payload = event["payload"]
    uid = str(event["aggregate_id"])
    tid = str(event["tenant_id"])

    if action == "created":
        _create(tid, uid, payload)
    elif action == "updated":
        _update(uid, payload)
    elif action == "deleted":
        _soft_delete(uid)


def _create(tenant_id: str, user_id: str, payload: dict):
    with get_session() as session:
        session.run(
            """
            MERGE (u:User {user_id: $uid})
            SET u.email        = $email,
                u.display_name = $display_name,
                u.status       = 'active',
                u.created_at   = datetime()
            WITH u
            MATCH (t:Tenant {tenant_id: $tid})
            MERGE (t)-[:HAS_USER]->(u)
            """,
            uid=user_id,
            tid=tenant_id,
            email=payload.get("email", ""),
            display_name=payload.get("display_name", ""),
        )

        home_store_id = payload.get("home_store_id")
        if home_store_id:
            session.run(
                """
                MATCH (u:User {user_id: $uid}), (st:Store {store_id: $stid})
                MERGE (u)-[:WORKS_AT]->(st)
                """,
                uid=user_id,
                stid=str(home_store_id),
            )

        home_org_unit_id = payload.get("home_org_unit_id")
        if home_org_unit_id:
            session.run(
                """
                MATCH (u:User {user_id: $uid}), (d:OrgUnit {org_unit_id: $oid})
                MERGE (u)-[:BELONGS_TO]->(d)
                """,
                uid=user_id,
                oid=str(home_org_unit_id),
            )

    logger.info(f"Graph: User created {user_id}")


def _update(user_id: str, payload: dict):
    scalar_props = {k: v for k, v in payload.items()
                    if v is not None and k not in ("user_id", "tenant_id", "home_store_id", "home_org_unit_id")}
    if scalar_props:
        set_clauses = ", ".join(f"u.{k} = ${k}" for k in scalar_props)
        with get_session() as session:
            session.run(
                f"MATCH (u:User {{user_id: $uid}}) SET {set_clauses}, u.updated_at = datetime()",
                uid=user_id,
                **scalar_props,
            )

    new_store = payload.get("home_store_id")
    if new_store:
        with get_session() as session:
            session.run(
                """
                MATCH (u:User {user_id: $uid})-[r:WORKS_AT]->()
                DELETE r
                """,
                uid=user_id,
            )
            session.run(
                """
                MATCH (u:User {user_id: $uid}), (st:Store {store_id: $stid})
                MERGE (u)-[:WORKS_AT]->(st)
                """,
                uid=user_id,
                stid=str(new_store),
            )

    new_org = payload.get("home_org_unit_id")
    if new_org:
        with get_session() as session:
            session.run(
                """
                MATCH (u:User {user_id: $uid})-[r:BELONGS_TO]->(:OrgUnit)
                DELETE r
                """,
                uid=user_id,
            )
            session.run(
                """
                MATCH (u:User {user_id: $uid}), (d:OrgUnit {org_unit_id: $oid})
                MERGE (u)-[:BELONGS_TO]->(d)
                """,
                uid=user_id,
                oid=str(new_org),
            )

    logger.info(f"Graph: User updated {user_id}")


def _soft_delete(user_id: str):
    with get_session() as session:
        session.run(
            "MATCH (u:User {user_id: $uid}) SET u.status = 'deleted', u.deleted_at = datetime()",
            uid=user_id,
        )
    logger.info(f"Graph: User soft-deleted {user_id}")
