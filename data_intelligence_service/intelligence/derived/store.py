"""
Derived Knowledge Store — read/write to the derived_knowledge Postgres table.

WHY Postgres and not Redis?
  Facts need to survive process restarts and be shared across service instances.
  Postgres gives us versioning (we keep old rows for audit), JSONB queries,
  and no extra infrastructure. Redis would add infra complexity with no benefit.

WHY keep old versions?
  Versioning lets us see how facts changed over time — useful for debugging
  "why did the answer change?" and for compliance audits.

Table schema (created by migration in migrations/derived_knowledge.sql):

  CREATE TABLE IF NOT EXISTS derived_knowledge (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL,
    fact_type   VARCHAR(100) NOT NULL,
    payload     JSONB NOT NULL,
    version     INTEGER NOT NULL DEFAULT 1,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_derived_latest UNIQUE (tenant_id, fact_type, version)
  );
  CREATE INDEX IF NOT EXISTS idx_derived_tenant_type ON derived_knowledge (tenant_id, fact_type);
"""
import json
import time
from typing import Dict, List, Optional, Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from data_intelligence_service.core.config import SETTINGS
from data_intelligence_service.core.logger import logger
from data_intelligence_service.intelligence.derived.models import DerivedFact

# In-memory cache: {(tenant_id, fact_type): (DerivedFact, expires_at)}
# Avoids hitting Postgres on every query — facts change infrequently
_cache: Dict[tuple, tuple] = {}
_CACHE_TTL_SECONDS = 300  # 5 minutes


def _get_engine():
    return create_engine(SETTINGS.POSTGRES_URL, pool_pre_ping=True)


def _get_session():
    return sessionmaker(bind=_get_engine())()


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def save_fact(fact: DerivedFact) -> bool:
    """Upsert a derived fact. Returns True on success.

    Versioning strategy: increment version each time a fact is recomputed.
    New row inserted, no DELETE of old rows — keeps full history.
    """
    session = _get_session()
    try:
        # Get current max version for this tenant+fact_type
        result = session.execute(
            text("""
                SELECT COALESCE(MAX(version), 0)
                FROM derived_knowledge
                WHERE tenant_id = :tenant_id AND fact_type = :fact_type
            """),
            {"tenant_id": fact.tenant_id, "fact_type": fact.fact_type},
        )
        current_version = result.scalar() or 0
        new_version = current_version + 1

        session.execute(
            text("""
                INSERT INTO derived_knowledge (id, tenant_id, fact_type, payload, version, computed_at)
                VALUES (:id, :tenant_id, :fact_type, :payload::jsonb, :version, :computed_at)
            """),
            {
                "id":          fact.id,
                "tenant_id":   fact.tenant_id,
                "fact_type":   fact.fact_type,
                "payload":     json.dumps(fact.payload),
                "version":     new_version,
                "computed_at": fact.computed_at,
            },
        )
        session.commit()

        # Invalidate cache entry so next read gets fresh data
        _cache.pop((fact.tenant_id, fact.fact_type), None)

        logger.info(f"[DerivedKnowledge] Saved {fact.fact_type} v{new_version} for tenant {fact.tenant_id}")
        return True

    except Exception as exc:
        logger.error(f"[DerivedKnowledge] Save failed ({fact.fact_type}): {exc}")
        session.rollback()
        return False
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_latest_fact(tenant_id: str, fact_type: str) -> Optional[DerivedFact]:
    """Return the latest version of a fact, or None if not yet computed.

    Uses an in-memory cache (5 min TTL) to avoid repeated DB hits.
    """
    cache_key = (tenant_id, fact_type)
    now = time.monotonic()

    # Check cache
    if cache_key in _cache:
        fact, expires_at = _cache[cache_key]
        if now < expires_at:
            return fact

    session = _get_session()
    try:
        result = session.execute(
            text("""
                SELECT id, tenant_id, fact_type, payload, version, computed_at
                FROM derived_knowledge
                WHERE tenant_id = :tenant_id AND fact_type = :fact_type
                ORDER BY version DESC
                LIMIT 1
            """),
            {"tenant_id": tenant_id, "fact_type": fact_type},
        )
        row = result.fetchone()
        if not row:
            return None

        payload = row[3] if isinstance(row[3], dict) else json.loads(row[3] or "{}")
        fact = DerivedFact(
            id=str(row[0]),
            tenant_id=str(row[1]),
            fact_type=row[2],
            payload=payload,
            version=row[4],
            computed_at=row[5],
        )
        _cache[cache_key] = (fact, now + _CACHE_TTL_SECONDS)
        return fact

    except Exception as exc:
        # DB unavailable — return None so caller can skip fact injection gracefully
        logger.warning(f"[DerivedKnowledge] Read failed ({fact_type}): {exc}")
        return None
    finally:
        session.close()


def get_facts_for_query(tenant_id: str, fact_types: List[str]) -> List[DerivedFact]:
    """Batch-fetch multiple fact types for a tenant.

    Used by the agent planner to get all relevant context at once.
    Facts not yet computed are silently omitted (returns partial list).
    """
    facts = []
    for ft in fact_types:
        fact = get_latest_fact(tenant_id, ft)
        if fact:
            facts.append(fact)
    return facts


def ensure_table_exists() -> None:
    """Create the derived_knowledge table if it doesn't exist.

    Called at service startup. Idempotent — safe to call multiple times.
    Run the proper migration SQL in staging/prod instead of this.
    """
    session = _get_session()
    try:
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS derived_knowledge (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id   UUID NOT NULL,
                fact_type   VARCHAR(100) NOT NULL,
                payload     JSONB NOT NULL DEFAULT '{}',
                version     INTEGER NOT NULL DEFAULT 1,
                computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_derived_tenant_type
            ON derived_knowledge (tenant_id, fact_type)
        """))
        session.commit()
        logger.info("[DerivedKnowledge] Table verified/created")
    except Exception as exc:
        logger.warning(f"[DerivedKnowledge] Table setup failed (will retry at next startup): {exc}")
        session.rollback()
    finally:
        session.close()
