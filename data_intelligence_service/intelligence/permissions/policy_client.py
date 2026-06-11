"""
DIS Policy Client — permission checks + audit log for intelligence queries.

WHY not reuse shared/policy_engine directly?
  shared/policy_engine.evaluate() requires:
    - A SQLAlchemy session to the shared Postgres DB (context enricher)
    - An OPA sidecar running on OPA_URL (HTTP call)
    - A Rego policy package mapping for "intelligence.*" actions

  We have NONE of those wired into DIS today. Adding them would introduce
  a hard dependency on OPA availability for every intelligence query —
  breaking fail-open semantics we need for a query service.

  Instead this client:
    1. Uses graph context (already fetched in node_guardrail) to check permissions
    2. Writes audit decisions to the SAME policy_decisions table that the real
       policy engine writes to — so compliance teams see DIS decisions too
    3. When OPA is available (OPA_URL set), optionally calls it for intelligence.*
       actions (Sprint 4 will add intelligence.rego to opa_policies)

HOW to add real OPA support later:
  1. Create shared/opa_policies/zeroque/intelligence.rego
  2. Add "intelligence." to _PREFIX_PACKAGE in shared/policy_engine/evaluator.py
  3. Set OPA_URL in DIS environment
  4. Replace _write_audit_log() call below with shared evaluate() call

AUDIT TABLE:
  Writes to policy_decisions (same table as shared/policy_engine).
  The decision log lets compliance teams audit "what queries were allowed".
  Best-effort only — a failure to write does NOT block the query.
"""
import json
import time
import uuid
from typing import Any, Dict, Optional

from data_intelligence_service.core.logger import logger

# The permission required to run any intelligence query
INTELLIGENCE_QUERY_PERMISSION = "intelligence.query"


def check_intelligence_permission(
    user_ctx: Dict[str, Any],
    question: str,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Check if this user may run an intelligence query.

    Uses the graph-derived permission list. Falls back to allow if
    graph was unavailable (fail-open — the API key is sufficient gate).

    Returns:
      {"allowed": bool, "reason": str, "decision": "allow"|"deny", "evaluation_ms": int}
    """
    from data_intelligence_service.intelligence.permissions.context import has_permission

    start = time.perf_counter()
    allowed = has_permission(user_ctx, INTELLIGENCE_QUERY_PERMISSION)
    elapsed_ms = int((time.perf_counter() - start) * 1000)

    decision = "allow" if allowed else "deny"
    reason = (
        "User has intelligence.query permission" if allowed
        else f"User lacks '{INTELLIGENCE_QUERY_PERMISSION}' permission"
    )

    result = {
        "allowed":       allowed,
        "decision":      decision,
        "reason":        reason,
        "evaluation_ms": elapsed_ms,
        "correlation_id": correlation_id,
    }

    _write_audit_log(
        user_ctx=user_ctx,
        action=INTELLIGENCE_QUERY_PERMISSION,
        resource={"question_preview": question[:200]},
        decision=decision,
        reason=reason,
        evaluation_ms=elapsed_ms,
        correlation_id=correlation_id,
    )

    logger.info(
        f"[Permissions] {decision.upper()} '{INTELLIGENCE_QUERY_PERMISSION}' "
        f"user={user_ctx.get('user_id')} ({elapsed_ms}ms)"
    )
    return result


def _write_audit_log(
    user_ctx: Dict[str, Any],
    action: str,
    resource: Dict[str, Any],
    decision: str,
    reason: str,
    evaluation_ms: int,
    correlation_id: Optional[str],
) -> None:
    """Write a permission decision to the policy_decisions audit table.

    Same table and schema as shared/policy_engine/_write_decision_log().
    Best-effort only — never raises.
    """
    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import sessionmaker
        from data_intelligence_service.core.config import SETTINGS

        engine = create_engine(SETTINGS.POSTGRES_URL, pool_pre_ping=True)
        session = sessionmaker(bind=engine)()

        subject = {
            "user_id":   user_ctx.get("user_id"),
            "tenant_id": user_ctx.get("tenant_id"),
            "roles":     [r.get("code") for r in user_ctx.get("roles", [])],
        }

        try:
            session.execute(
                text("""
                    INSERT INTO policy_decisions (
                        decision_id, tenant_id, user_id, action,
                        subject, resource, decision, matched_policies,
                        reason, evaluation_ms, correlation_id, evaluated_at
                    ) VALUES (
                        :id, :tid, :uid, :action,
                        CAST(:subject AS jsonb), CAST(:resource AS jsonb),
                        :decision, CAST(:matched AS jsonb),
                        :reason, :ms, :corr, NOW()
                    )
                """),
                {
                    "id":       uuid.uuid4(),
                    "tid":      user_ctx.get("tenant_id"),
                    "uid":      user_ctx.get("user_id"),
                    "action":   action,
                    "subject":  json.dumps(subject, default=str),
                    "resource": json.dumps(resource, default=str),
                    "decision": decision,
                    "matched":  json.dumps([{"source": "graph_permissions"}]),
                    "reason":   reason,
                    "ms":       evaluation_ms,
                    "corr":     correlation_id,
                },
            )
            session.commit()
        except Exception as exc:
            session.rollback()
            raise exc
        finally:
            session.close()

    except Exception as exc:
        # Best-effort — never block the query on audit failure
        logger.warning(f"[Permissions] Audit log write failed (non-fatal): {exc}")
