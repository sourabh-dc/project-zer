"""
graph_service/handlers/mandate_handler.py
------------------------------------------
Projects Mandate lifecycle events into the governance graph.

Mandates are NOT persisted as standalone nodes — they are ephemeral billing
intents.  However, when a mandate is activated (status='active'), the
resulting Tenant node gets a ``mandate_id`` property and a
``(:Tenant)-[:SUBSCRIBES_TO]->(:Plan)`` relationship is created.

This handler is intentionally lightweight because the tenant_handler already
creates the Tenant node on ``tenant.created`` / ``tenant.signup``.  The
mandate handler only enriches the Tenant node with subscription metadata
that arrives via the mandate activation event.
"""

import logging
from graph_service.core.neo4j_client import get_session

logger = logging.getLogger("graph_service.mandate_handler")


def handle(event: dict):
    """Entry point called by the outbox consumer."""
    event_type = event.get("event_type", "")
    action = event_type.split(".")[-1] if "." in event_type else event_type
    payload = event.get("payload", {})

    if action == "activated":
        _on_activated(payload)
    elif action == "created":
        # Nothing to project on mandate creation (no tenant yet)
        logger.debug(f"Mandate created — no graph projection needed")
    else:
        logger.debug(f"Unhandled mandate action: {action}")


def _on_activated(payload: dict):
    """Enrich the Tenant node with mandate/subscription metadata."""
    tenant_id = payload.get("tenant_id")
    mandate_id = payload.get("mandate_id")
    plan_code = payload.get("plan_code")
    is_trial = payload.get("is_trial", False)
    stripe_customer_id = payload.get("stripe_customer_id")

    if not tenant_id:
        logger.warning("mandate.activated event missing tenant_id — skipping")
        return

    session = get_session()
    try:
        # Set mandate metadata on Tenant node
        session.run(
            """
            MATCH (t:Tenant {tenant_id: $tid})
            SET t.mandate_id = $mid,
                t.stripe_customer_id = $scid,
                t.is_trial = $trial,
                t.updated_at = datetime()
            """,
            tid=tenant_id,
            mid=mandate_id,
            scid=stripe_customer_id,
            trial=is_trial,
        )

        # Create or merge Plan node and SUBSCRIBES_TO relationship
        if plan_code:
            session.run(
                """
                MATCH (t:Tenant {tenant_id: $tid})
                MERGE (p:Plan {code: $pc})
                MERGE (t)-[:SUBSCRIBES_TO]->(p)
                """,
                tid=tenant_id,
                pc=plan_code,
            )

        logger.info(f"Graph enriched for mandate activation: tenant={tenant_id}")
    finally:
        session.close()
