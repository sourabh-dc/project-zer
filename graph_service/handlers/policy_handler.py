"""
Handler: Policy events → Neo4j.

Manages :Policy nodes and assignment edges:
  (:Policy)-[:ASSIGNED_TO]->(:Tenant | :OrgUnit | :Role)

The policy graph enables quick traversal to answer:
  "Which policies apply to this user given their roles and org units?"
"""
from graph_service.core.neo4j_client import get_session
from graph_service.core.logger import logger


def handle(event: dict):
    etype = event["event_type"]
    payload = event["payload"]
    aid = str(event["aggregate_id"])
    tid = str(event["tenant_id"])

    if etype == "policy.created":
        _create(tid, aid, payload)
    elif etype == "policy.updated":
        _update(aid, payload)
    elif etype == "policy.deleted":
        _soft_delete(aid)
    elif etype == "policy_assignment.created":
        _create_assignment(aid, payload)
    elif etype == "policy_assignment.deleted":
        _delete_assignment(aid, payload)
    elif etype == "policy.seed_completed":
        logger.info(f"Graph: Policy seed completed — seeded={payload.get('seeded')}, skipped={payload.get('skipped')}")
    elif etype.startswith("policy_rule."):
        logger.debug(f"Graph: Policy rule event {etype} (no graph projection needed)")


def _create(tenant_id: str, policy_id: str, payload: dict):
    with get_session() as session:
        session.run(
            """
            MERGE (p:Policy {policy_id: $pid})
            SET p.code        = $code,
                p.name        = $name,
                p.policy_type = $ptype,
                p.status      = 'active',
                p.created_at  = datetime()
            WITH p
            MATCH (t:Tenant {tenant_id: $tid})
            MERGE (t)-[:HAS_POLICY]->(p)
            """,
            pid=policy_id,
            tid=tenant_id,
            code=payload.get("code", ""),
            name=payload.get("name", ""),
            ptype=payload.get("policy_type", ""),
        )
    logger.info(f"Graph: Policy created {policy_id}")


def _update(policy_id: str, payload: dict):
    props = {k: v for k, v in payload.items()
             if v is not None and k not in ("policy_id", "tenant_id")}
    if not props:
        return
    set_clauses = ", ".join(f"p.{k} = ${k}" for k in props)
    with get_session() as session:
        session.run(
            f"MATCH (p:Policy {{policy_id: $pid}}) SET {set_clauses}, p.updated_at = datetime()",
            pid=policy_id,
            **props,
        )
    logger.info(f"Graph: Policy updated {policy_id}")


def _soft_delete(policy_id: str):
    with get_session() as session:
        session.run(
            "MATCH (p:Policy {policy_id: $pid}) SET p.status = 'deleted', p.deleted_at = datetime()",
            pid=policy_id,
        )
    logger.info(f"Graph: Policy soft-deleted {policy_id}")


def _create_assignment(assignment_id: str, payload: dict):
    policy_id = payload.get("policy_id")
    scope_type = payload.get("scope_type", "")  # tenant | org_unit | role
    scope_value = payload.get("scope_value", "")

    label_map = {
        "tenant": ("Tenant", "tenant_id"),
        "org_unit": ("OrgUnit", "org_unit_id"),
        "role": ("Role", "role_id"),
    }
    target = label_map.get(scope_type)
    if not target or not policy_id:
        logger.warning(f"Graph: Unknown assignment scope '{scope_type}' for assignment {assignment_id}")
        return

    label, prop = target
    with get_session() as session:
        session.run(
            f"""
            MATCH (p:Policy {{policy_id: $pid}}), (n:{label} {{{prop}: $sv}})
            MERGE (p)-[:ASSIGNED_TO {{assignment_id: $aid}}]->(n)
            """,
            pid=str(policy_id),
            sv=scope_value,
            aid=assignment_id,
        )
    logger.info(f"Graph: Policy {policy_id} assigned to {scope_type}={scope_value}")


def _delete_assignment(assignment_id: str, payload: dict):
    with get_session() as session:
        session.run(
            "MATCH ()-[r:ASSIGNED_TO {assignment_id: $aid}]->() DELETE r",
            aid=assignment_id,
        )
    logger.info(f"Graph: Policy assignment {assignment_id} deleted")
