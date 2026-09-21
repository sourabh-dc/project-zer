"""
shared/policy_engine/db.py
---------------------------
SQLAlchemy session for the shared PostgreSQL database, used by the
policy engine for subject context enrichment and decision logging.

URL resolution order:
  1. Explicit configure_database_url() (preferred — services pass SETTINGS.DATABASE_URL)
  2. DATABASE_URL env var
  3. POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_HOST / POSTGRES_DB[/PORT]
  4. Local default (dev only)

Provisioning/orders often load DB pieces from Key Vault into SETTINGS without
setting DATABASE_URL on the container. Call configure_database_url() at startup
(or set os.environ["DATABASE_URL"]) so enrichment hits the same DB as the ORM.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger("policy_engine.db")

_engine: Optional[Engine] = None
_SessionLocal = None
_configured_url: Optional[str] = None


def _build_url_from_postgres_env() -> Optional[str]:
    user = os.getenv("POSTGRES_USER") or os.getenv("POSTGRES_USERNAME") or ""
    password = os.getenv("POSTGRES_PASSWORD") or ""
    host = os.getenv("POSTGRES_HOST") or ""
    db = os.getenv("POSTGRES_DB") or ""
    port = os.getenv("POSTGRES_PORT") or "5432"
    if user and host and db:
        return f"postgresql://{user}:{password}@{host}:{port}/{db}"
    return None


def resolve_database_url() -> str:
    """Resolve the Postgres URL the policy engine should use."""
    if _configured_url:
        return _configured_url
    env_url = (os.getenv("DATABASE_URL") or "").strip()
    if env_url:
        return env_url
    built = _build_url_from_postgres_env()
    if built:
        return built
    return "postgresql://postgres:password@localhost:5432/zeroque_dev"


def configure_database_url(url: str) -> None:
    """Point the policy engine at the same DB URL the host service uses.

    Safe to call multiple times; recreates the engine when the URL changes.
    """
    global _configured_url, _engine, _SessionLocal
    url = (url or "").strip()
    if not url:
        return
    if _configured_url == url and _engine is not None:
        return
    _configured_url = url
    # Also expose for any code that still reads getenv
    os.environ["DATABASE_URL"] = url
    if _engine is not None:
        try:
            _engine.dispose()
        except Exception:
            pass
    _engine = None
    _SessionLocal = None
    logger.info("Policy engine database URL configured")


def _ensure_engine() -> sessionmaker:
    global _engine, _SessionLocal
    if _SessionLocal is not None:
        return _SessionLocal
    url = resolve_database_url()
    # Avoid logging credentials — host/db only
    try:
        host_part = url.split("@", 1)[-1]
    except Exception:
        host_part = "<unparseable>"
    logger.info(f"Policy engine connecting to Postgres at {host_part}")
    _engine = create_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_timeout=30,
        pool_recycle=3600,
    )
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    return _SessionLocal


def get_policy_db():
    """FastAPI dependency — yields a SQLAlchemy session for policy evaluation."""
    SessionLocal = _ensure_engine()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
