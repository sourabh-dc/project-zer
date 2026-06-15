"""
Cost tracker — records per-query token usage and cost per tenant/user.

WHY track cost at query level?
  The spec (§16, §17) requires: cost by tenant, cost by model, cost by user,
  and abuse detection. Token counts from the LLM response are the ground truth.
  We convert tokens → USD using standard Azure OpenAI pricing.

Storage:
  Postgres table intelligence_usage — one row per query.
  Schema in migrations/002_intelligence_usage.sql.
  Falls back to no-op if table doesn't exist (non-fatal).

Cost model (approximate Azure OpenAI pricing — update when Azure changes):
  gpt-5-nano:  $0.000003/prompt token,  $0.000012/completion token
  gpt-4o-mini: $0.00000015/prompt token, $0.0000006/completion token
  embeddings:  $0.00000002/token (text-embedding-3-small)

Abuse detection:
  A tenant is flagged if they spend more than ABUSE_COST_THRESHOLD_USD
  in a rolling 1-hour window. Flagged tenants are surfaced in the
  GET /intelligence/cost/abuse endpoint.
"""
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from data_intelligence_service.core.logger import logger

# ---------------------------------------------------------------------------
# Pricing table (USD per token)
# ---------------------------------------------------------------------------

_PRICING: Dict[str, Dict[str, float]] = {
    # gpt-5-nano (reasoning model)
    "gpt-5-nano":        {"prompt": 0.000003,  "completion": 0.000012},
    # gpt-4o-mini (fast tier)
    "gpt-4o-mini":       {"prompt": 0.00000015, "completion": 0.0000006},
    # gpt-4o
    "gpt-4o":            {"prompt": 0.000005,   "completion": 0.000015},
    # embeddings
    "text-embedding-3-small": {"prompt": 0.00000002, "completion": 0.0},
}

_DEFAULT_PRICING = {"prompt": 0.000003, "completion": 0.000012}

# Abuse threshold — flag tenant if they spend this much USD in 1 hour
_ABUSE_THRESHOLD_USD = float(os.getenv("ABUSE_COST_THRESHOLD_USD", "5.0"))


def _calc_cost(deployment: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Calculate USD cost for a single LLM call."""
    pricing = _PRICING.get(deployment, _DEFAULT_PRICING)
    return round(
        prompt_tokens * pricing["prompt"] + completion_tokens * pricing["completion"],
        8,
    )


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_engine():
    from sqlalchemy import create_engine
    from data_intelligence_service.core.config import SETTINGS
    return create_engine(SETTINGS.POSTGRES_URL, pool_pre_ping=True)


def ensure_usage_table() -> None:
    """Create intelligence_usage table if it doesn't exist."""
    from sqlalchemy import text
    try:
        engine = _get_engine()
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS intelligence_usage (
                    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    tenant_id       UUID NOT NULL,
                    user_id         UUID,
                    session_id      TEXT,
                    correlation_id  TEXT,
                    model_tier      TEXT,
                    deployment      TEXT,
                    prompt_tokens   INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens    INTEGER NOT NULL DEFAULT 0,
                    cost_usd        NUMERIC(12, 8) NOT NULL DEFAULT 0,
                    engine          TEXT,
                    latency_ms      NUMERIC(10, 2),
                    query_hash      TEXT,
                    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_usage_tenant_recorded
                    ON intelligence_usage (tenant_id, recorded_at DESC);
                CREATE INDEX IF NOT EXISTS idx_usage_user_recorded
                    ON intelligence_usage (user_id, recorded_at DESC);
                CREATE INDEX IF NOT EXISTS idx_usage_recorded
                    ON intelligence_usage (recorded_at DESC);
            """))
            conn.commit()
        logger.info("[CostTracker] intelligence_usage table ready")
    except Exception as exc:
        logger.warning(f"[CostTracker] Could not create usage table: {exc}")


def record_usage(
    tenant_id: str,
    user_id: Optional[str],
    session_id: Optional[str],
    deployment: str,
    model_tier: str,
    prompt_tokens: int,
    completion_tokens: int,
    engine: str,
    latency_ms: float,
    question: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> None:
    """Insert one usage row. Best-effort — never raises."""
    from sqlalchemy import text
    import hashlib

    cost_usd = _calc_cost(deployment, prompt_tokens, completion_tokens)
    total = prompt_tokens + completion_tokens
    query_hash = hashlib.md5((question or "").encode()).hexdigest()[:16] if question else None

    try:
        engine_db = _get_engine()
        with engine_db.connect() as conn:
            conn.execute(text("""
                INSERT INTO intelligence_usage
                    (tenant_id, user_id, session_id, correlation_id,
                     model_tier, deployment,
                     prompt_tokens, completion_tokens, total_tokens,
                     cost_usd, engine, latency_ms, query_hash)
                VALUES
                    (:tenant_id, :user_id, :session_id, :correlation_id,
                     :model_tier, :deployment,
                     :prompt_tokens, :completion_tokens, :total_tokens,
                     :cost_usd, :engine, :latency_ms, :query_hash)
            """), {
                "tenant_id":         tenant_id,
                "user_id":           user_id,
                "session_id":        session_id,
                "correlation_id":    correlation_id or str(uuid.uuid4()),
                "model_tier":        model_tier,
                "deployment":        deployment,
                "prompt_tokens":     prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens":      total,
                "cost_usd":          cost_usd,
                "engine":            engine,
                "latency_ms":        latency_ms,
                "query_hash":        query_hash,
            })
            conn.commit()
        logger.debug(
            f"[CostTracker] tenant={tenant_id} user={user_id} "
            f"tokens={total} cost=${cost_usd:.6f} tier={model_tier}"
        )
    except Exception as exc:
        logger.warning(f"[CostTracker] Failed to record usage (non-fatal): {exc}")


# ---------------------------------------------------------------------------
# Dashboard queries
# ---------------------------------------------------------------------------

def get_cost_by_tenant(days: int = 30) -> List[Dict[str, Any]]:
    """Total cost + token usage grouped by tenant, last N days."""
    from sqlalchemy import text
    try:
        engine = _get_engine()
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT
                    tenant_id::text,
                    COUNT(*)                        AS query_count,
                    SUM(total_tokens)               AS total_tokens,
                    SUM(prompt_tokens)              AS prompt_tokens,
                    SUM(completion_tokens)          AS completion_tokens,
                    ROUND(SUM(cost_usd)::numeric, 4) AS total_cost_usd,
                    MAX(recorded_at)                AS last_query_at
                FROM intelligence_usage
                WHERE recorded_at >= NOW() - INTERVAL ':days days'
                GROUP BY tenant_id
                ORDER BY total_cost_usd DESC
            """.replace(":days days", f"{int(days)} days")))
            return [dict(row._mapping) for row in result.fetchall()]
    except Exception as exc:
        logger.warning(f"[CostTracker] get_cost_by_tenant failed: {exc}")
        return []


def get_cost_by_user(tenant_id: str, days: int = 30) -> List[Dict[str, Any]]:
    """Per-user cost breakdown for a tenant, last N days."""
    from sqlalchemy import text
    try:
        engine = _get_engine()
        with engine.connect() as conn:
            result = conn.execute(text(f"""
                SELECT
                    user_id::text,
                    COUNT(*)                         AS query_count,
                    SUM(total_tokens)                AS total_tokens,
                    ROUND(SUM(cost_usd)::numeric, 6) AS total_cost_usd,
                    MAX(recorded_at)                 AS last_query_at,
                    MODE() WITHIN GROUP (ORDER BY model_tier) AS primary_tier
                FROM intelligence_usage
                WHERE tenant_id = :tid
                  AND recorded_at >= NOW() - INTERVAL '{int(days)} days'
                GROUP BY user_id
                ORDER BY total_cost_usd DESC
                LIMIT 50
            """), {"tid": tenant_id})
            return [dict(row._mapping) for row in result.fetchall()]
    except Exception as exc:
        logger.warning(f"[CostTracker] get_cost_by_user failed: {exc}")
        return []


def get_cost_by_model(days: int = 30) -> List[Dict[str, Any]]:
    """Cost breakdown by model/deployment, last N days."""
    from sqlalchemy import text
    try:
        engine = _get_engine()
        with engine.connect() as conn:
            result = conn.execute(text(f"""
                SELECT
                    deployment,
                    model_tier,
                    COUNT(*)                         AS query_count,
                    SUM(total_tokens)                AS total_tokens,
                    ROUND(SUM(cost_usd)::numeric, 4) AS total_cost_usd
                FROM intelligence_usage
                WHERE recorded_at >= NOW() - INTERVAL '{int(days)} days'
                GROUP BY deployment, model_tier
                ORDER BY total_cost_usd DESC
            """))
            return [dict(row._mapping) for row in result.fetchall()]
    except Exception as exc:
        logger.warning(f"[CostTracker] get_cost_by_model failed: {exc}")
        return []


def get_abuse_candidates(hours: int = 1) -> List[Dict[str, Any]]:
    """Tenants spending more than threshold in a rolling window.

    Returns list of {tenant_id, cost_usd, query_count} sorted by cost DESC.
    These are candidates for throttling or investigation.
    """
    from sqlalchemy import text
    try:
        engine = _get_engine()
        with engine.connect() as conn:
            result = conn.execute(text(f"""
                SELECT
                    tenant_id::text,
                    COUNT(*)                          AS query_count,
                    ROUND(SUM(cost_usd)::numeric, 4)  AS cost_usd,
                    MIN(recorded_at)                  AS window_start,
                    MAX(recorded_at)                  AS window_end
                FROM intelligence_usage
                WHERE recorded_at >= NOW() - INTERVAL '{int(hours)} hours'
                GROUP BY tenant_id
                HAVING SUM(cost_usd) > :threshold
                ORDER BY cost_usd DESC
            """), {"threshold": _ABUSE_THRESHOLD_USD})
            return [dict(row._mapping) for row in result.fetchall()]
    except Exception as exc:
        logger.warning(f"[CostTracker] get_abuse_candidates failed: {exc}")
        return []
