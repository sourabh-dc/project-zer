"""
Handler: Role & Permission events → Neo4j.

Manages :Role nodes and assignment edges:
  (:User)-[:HAS_ROLE]->(:Role)
  (:Role)-[:GRANTS]->(:Permission)
"""
from data_intelligence_service.core.neo4j_client import get_session
from data_intelligence_service.core.logger import logger


def handle(event: dict):
    etype = event["event_type"]
    payload = event["payload"]

    if etype == "role.assigned":
        _assign_role(payload)
    elif etype == "role.removed":
        _remove_role(payload)
    elif etype == "role.created":
        _create_role(payload)
    elif etype == "role.deleted":
        _delete_role(payload)
    elif etype == "role_permission.created":
        _add_permission(payload)
    elif etype == "role_permission.deleted":
        _remove_permission(payload)


def _create_role(payload: dict):
    role_id = payload.get("role_id") or str(payload.get("role_code", ""))
    with get_session() as session:
        session.run(
            """
            MERGE (r:Role {role_id: $rid})
            SET r.name       = $name,
                r.code       = $code,
                r.status     = 'active',
                r.created_at = datetime()
            """,
            rid=role_id,
            name=payload.get("name", ""),
            code=payload.get("code", ""),
        )
    logger.info(f"Graph: Role created {role_id}")


def _delete_role(payload: dict):
    role_id = payload.get("role_id") or str(payload.get("role_code", ""))
    with get_session() as session:
        session.run(
            "MATCH (r:Role {role_id: $rid}) SET r.status = 'deleted', r.deleted_at = datetime()",
            rid=role_id,
        )
    logger.info(f"Graph: Role soft-deleted {role_id}")


def _assign_role(payload: dict):
    user_id = payload.get("user_id")
    role_id = payload.get("role_id")
    if not user_id or not role_id:
        return
    with get_session() as session:
        session.run(
            """
            MATCH (u:User {user_id: $uid}), (r:Role {role_id: $rid})
            MERGE (u)-[:HAS_ROLE]->(r)
            """,
            uid=str(user_id),
            rid=str(role_id),
        )
    logger.info(f"Graph: Role {role_id} assigned to user {user_id}")


def _remove_role(payload: dict):
    user_id = payload.get("user_id")
    role_id = payload.get("role_id")
    if not user_id or not role_id:
        return
    with get_session() as session:
        session.run(
            """
            MATCH (u:User {user_id: $uid})-[r:HAS_ROLE]->(ro:Role {role_id: $rid})
            DELETE r
            """,
            uid=str(user_id),
            rid=str(role_id),
        )
    logger.info(f"Graph: Role {role_id} removed from user {user_id}")


def _add_permission(payload: dict):
    role_code = payload.get("role_code", "")
    perm_code = payload.get("permission_code", "")
    with get_session() as session:
        session.run(
            """
            MERGE (p:Permission {code: $pcode})
            SET p.updated_at = datetime()
            WITH p
            MATCH (r:Role {code: $rcode})
            MERGE (r)-[:GRANTS]->(p)
            """,
            rcode=role_code,
            pcode=perm_code,
        )
    logger.info(f"Graph: Permission {perm_code} granted to role {role_code}")


def _remove_permission(payload: dict):
    role_code = payload.get("role_code", "")
    perm_code = payload.get("permission_code", "")
    with get_session() as session:
        session.run(
            """
            MATCH (r:Role {code: $rcode})-[rel:GRANTS]->(p:Permission {code: $pcode})
            DELETE rel
            """,
            rcode=role_code,
            pcode=perm_code,
        )
    logger.info(f"Graph: Permission {perm_code} removed from role {role_code}")
