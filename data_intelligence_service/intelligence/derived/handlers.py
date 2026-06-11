"""
Derived Knowledge — outbox event handlers.

WHY trigger recomputation from outbox events?
  We want derived facts to stay current without polling or scheduled jobs.
  Outbox events are the source of truth for "something changed" — when
  a purchase_request is submitted, we know spend data changed, so we
  recompute spend-based facts immediately.

  This is the same pattern as graph/handlers/ and vector/handlers/ —
  one handler per entity type, registered in main.py at startup.

HOW facts are recomputed:
  Each handler maps its event type to a list of affected fact types
  (defined in models.FACT_TRIGGERS), then calls facts.compute_and_save()
  for each affected fact type.

  compute_and_save() queries the live DB and writes the result to
  derived_knowledge. The agent's next query will pick up the fresh fact
  (cache TTL is 5 minutes — see store.py).

WHY ignore individual event sub-types (e.g. purchase_request.submitted vs .auto_approved)?
  For spend facts, any purchase_request change is a trigger regardless of
  the sub-type. Trying to be smarter (e.g. only recompute on .submitted)
  risks missing edge cases. Recomputation is cheap enough to do on all.

REGISTRATION in main.py:
  from data_intelligence_service.intelligence.derived import handlers as derived_handlers
  register_handler("purchase_request", derived_handlers.handle_purchase_request)
  register_handler("approved_range",   derived_handlers.handle_approved_range)
  register_handler("budget",           derived_handlers.handle_budget)
  register_handler("policy",           derived_handlers.handle_policy)
  register_handler("org_unit",         derived_handlers.handle_org_unit)
"""
from data_intelligence_service.core.logger import logger
from data_intelligence_service.intelligence.derived.models import FACT_TRIGGERS
from data_intelligence_service.intelligence.derived.facts import compute_and_save


def _recompute(tenant_id: str, trigger_prefix: str) -> None:
    """Recompute all facts triggered by the given event prefix.

    Runs synchronously — fact computation is fast (< 500ms) and the
    outbox consumer handles errors gracefully (retry on exception).
    """
    fact_types = FACT_TRIGGERS.get(trigger_prefix, [])
    if not fact_types:
        return

    for fact_type in fact_types:
        try:
            success = compute_and_save(tenant_id, fact_type)
            if success:
                logger.info(f"[DerivedKnowledge] Recomputed {fact_type} for tenant {tenant_id}")
            else:
                logger.warning(f"[DerivedKnowledge] Recomputation returned no result: {fact_type}")
        except Exception as exc:
            # Log but don't re-raise — a failed recomputation should not
            # block the outbox event from being marked as completed.
            logger.error(f"[DerivedKnowledge] Failed to recompute {fact_type} for {tenant_id}: {exc}")


def handle_purchase_request(event: dict) -> None:
    """Recompute spend-based facts when any purchase request changes."""
    tenant_id = str(event.get("tenant_id", ""))
    if not tenant_id:
        return
    logger.debug(f"[DerivedKnowledge] purchase_request event → recomputing spend facts for {tenant_id}")
    _recompute(tenant_id, "purchase_request")


def handle_approved_range(event: dict) -> None:
    """Recompute governance facts when approved ranges change."""
    tenant_id = str(event.get("tenant_id", ""))
    if not tenant_id:
        return
    logger.debug(f"[DerivedKnowledge] approved_range event → recomputing governance facts for {tenant_id}")
    _recompute(tenant_id, "approved_range")


def handle_budget(event: dict) -> None:
    """Recompute budget facts when budgets are created or modified."""
    tenant_id = str(event.get("tenant_id", ""))
    if not tenant_id:
        return
    logger.debug(f"[DerivedKnowledge] budget event → recomputing budget facts for {tenant_id}")
    _recompute(tenant_id, "budget")


def handle_policy(event: dict) -> None:
    """Recompute policy summary when policies change."""
    tenant_id = str(event.get("tenant_id", ""))
    if not tenant_id:
        return
    logger.debug(f"[DerivedKnowledge] policy event → recomputing policy facts for {tenant_id}")
    _recompute(tenant_id, "policy")


def handle_org_unit(event: dict) -> None:
    """Recompute org-unit budget status when org unit structure changes."""
    tenant_id = str(event.get("tenant_id", ""))
    if not tenant_id:
        return
    logger.debug(f"[DerivedKnowledge] org_unit event → recomputing org unit facts for {tenant_id}")
    _recompute(tenant_id, "org_unit")
