"""
shared/policy_engine
---------------------
In-process policy evaluation engine.

All policy logic lives as Rego files in shared/opa_policies/.
Services import require_policy from their own policy_client.py
(which wires auth + DB) and delegate evaluation to this module.

Public surface:
  evaluate(db, action, subject, resource, tenant_id, ...) -> dict
  get_policy_db()  — FastAPI dependency for the shared policy DB session
  configure_database_url(url) — point enrichment at the host service DB
"""
from .evaluator import evaluate  # noqa: F401
from .db import get_policy_db, configure_database_url  # noqa: F401
