"""
shared/policy_engine/db.py
---------------------------
SQLAlchemy session for the shared PostgreSQL database, used by the
policy engine for subject context enrichment and decision logging.
Reuses the same DATABASE_URL that every other service already sets —
no extra env variable needed.

Reads connection URL from the standard DATABASE_URL environment variable —
the same one every service already configures.

The policy engine needs access to: users, user_roles, roles,
user_cost_centres, tenant_subscriptions, approved_ranges, role_permissions.
These tables all live in the shared PostgreSQL instance.
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/zeroque_dev")

_engine = create_engine(
    _DB_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    pool_timeout=30,
    pool_recycle=3600,
)
_SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


def get_policy_db():
    """FastAPI dependency — yields a SQLAlchemy session for policy evaluation."""
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()
