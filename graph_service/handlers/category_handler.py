"""
Handler: Category events → Neo4j.

Manages :Category nodes:
  (:Tenant)-[:HAS_CATEGORY]->(:Category)
  (:Category)-[:CHILD_OF]->(:Category)
  (:Product)-[:IN_CATEGORY]->(:Category)
"""
from graph_service.core.neo4j_client import get_session
from graph_service.core.logger import logger


def handle(event: dict):
    action = event["event_type"].split(".")[-1]
    payload = event["payload"]
    cid = str(event["aggregate_id"])
    tid = str(event["tenant_id"])

    if action == "created":
        _create(tid, cid, payload)
    elif action == "updated":
        _update(cid, payload)
    elif action == "deleted":
        _soft_delete(cid)


def _create(tenant_id: str, category_id: str, payload: dict):
    with get_session() as session:
        session.run(
            """
            MERGE (c:Category {category_id: $cid})
            SET c.name       = $name,
                c.code       = $code,
                c.status     = 'active',
                c.created_at = datetime()
            WITH c
            MATCH (t:Tenant {tenant_id: $tid})
            MERGE (t)-[:HAS_CATEGORY]->(c)
            """,
            cid=category_id,
            tid=tenant_id,
            name=payload.get("name", ""),
            code=payload.get("code", ""),
        )

        parent_id = payload.get("parent_category_id")
        if parent_id:
            session.run(
                """
                MATCH (child:Category {category_id: $cid}),
                      (parent:Category {category_id: $pid})
                MERGE (child)-[:CHILD_OF]->(parent)
                """,
                cid=category_id,
                pid=str(parent_id),
            )
    logger.info(f"Graph: Category created {category_id}")


def _update(category_id: str, payload: dict):
    props = {k: v for k, v in payload.items()
             if v is not None and k not in ("category_id", "tenant_id", "parent_category_id")}
    if props:
        set_clauses = ", ".join(f"c.{k} = ${k}" for k in props)
        with get_session() as session:
            session.run(
                f"MATCH (c:Category {{category_id: $cid}}) SET {set_clauses}, c.updated_at = datetime()",
                cid=category_id,
                **props,
            )

    new_parent = payload.get("parent_category_id")
    if new_parent is not None:
        with get_session() as session:
            session.run("MATCH (c:Category {category_id: $cid})-[r:CHILD_OF]->() DELETE r", cid=category_id)
            if new_parent:
                session.run(
                    """
                    MATCH (child:Category {category_id: $cid}),
                          (parent:Category {category_id: $pid})
                    MERGE (child)-[:CHILD_OF]->(parent)
                    """,
                    cid=category_id,
                    pid=str(new_parent),
                )
    logger.info(f"Graph: Category updated {category_id}")


def _soft_delete(category_id: str):
    with get_session() as session:
        session.run(
            "MATCH (c:Category {category_id: $cid}) SET c.status = 'deleted', c.deleted_at = datetime()",
            cid=category_id,
        )
    logger.info(f"Graph: Category soft-deleted {category_id}")
