"""
Derived Knowledge Layer — data models.

WHY a Derived Knowledge Layer?
  Some questions require expensive multi-table joins or graph traversals
  that are slow to run on every query: "What's our top spend category this
  quarter?" requires joining orders → order_items → categories and summing.

  Precomputing these facts means:
  - Instant answers for common analytical questions (no heavy DB query)
  - Consistent numbers across multiple queries in the same session
  - LLM reasons over summaries instead of raw rows (less hallucination risk)
  - Facts are versioned — we know exactly when they were computed

  Facts are recomputed automatically when relevant outbox events fire
  (e.g. a new purchase_request triggers recomputation of spend summaries).

Fact types (see facts.py for computation):
  top_categories_by_spend    — top 10 categories ranked by spend this quarter
  approval_policy_summary    — summary of active policies per tenant
  org_unit_budget_status     — budget utilization % per org unit
  vendor_activity_summary    — vendor order counts + last order date
  approved_product_count     — total approved products per tenant/org unit

Storage: Postgres derived_knowledge table (see store.py for schema).
Versioned: each recomputation creates a new row, old rows kept for audit.
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Canonical fact type identifiers — used as keys in the DB table
FACT_TOP_CATEGORIES_BY_SPEND = "top_categories_by_spend"
FACT_APPROVAL_POLICY_SUMMARY = "approval_policy_summary"
FACT_ORG_UNIT_BUDGET_STATUS  = "org_unit_budget_status"
FACT_VENDOR_ACTIVITY_SUMMARY = "vendor_activity_summary"
FACT_APPROVED_PRODUCT_COUNT  = "approved_product_count"

# Which outbox event prefixes trigger recomputation of which facts
# Used in handlers.py to register the right handlers
FACT_TRIGGERS: Dict[str, list] = {
    "purchase_request": [
        FACT_TOP_CATEGORIES_BY_SPEND,
        FACT_VENDOR_ACTIVITY_SUMMARY,
    ],
    "approved_range": [
        FACT_APPROVED_PRODUCT_COUNT,
        FACT_APPROVAL_POLICY_SUMMARY,
    ],
    "policy": [
        FACT_APPROVAL_POLICY_SUMMARY,
    ],
    "budget": [
        FACT_ORG_UNIT_BUDGET_STATUS,
    ],
    "org_unit": [
        FACT_ORG_UNIT_BUDGET_STATUS,
    ],
}

# Which fact types are relevant for which engine hint
# The planner uses this to select which facts to inject into the prompt
FACT_ENGINE_RELEVANCE: Dict[str, list] = {
    "sql":    [FACT_TOP_CATEGORIES_BY_SPEND, FACT_ORG_UNIT_BUDGET_STATUS, FACT_VENDOR_ACTIVITY_SUMMARY],
    "graph":  [FACT_APPROVAL_POLICY_SUMMARY, FACT_APPROVED_PRODUCT_COUNT],
    "vector": [FACT_APPROVED_PRODUCT_COUNT],
    "hybrid": [
        FACT_TOP_CATEGORIES_BY_SPEND,
        FACT_APPROVAL_POLICY_SUMMARY,
        FACT_ORG_UNIT_BUDGET_STATUS,
    ],
    "unknown": [FACT_TOP_CATEGORIES_BY_SPEND, FACT_APPROVAL_POLICY_SUMMARY],
}


@dataclass
class DerivedFact:
    """A single precomputed business fact for a tenant.

    Stored in the derived_knowledge Postgres table.
    """
    fact_type:   str            # one of the FACT_* constants above
    tenant_id:   str
    payload:     Dict[str, Any] # the actual data — see facts.py for shape
    version:     int = 1
    computed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id:          str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_context_snippet(self) -> str:
        """Format this fact as a compact text snippet for LLM injection.

        The snippet is injected into the planner prompt as business context.
        Keep it short — every token costs time and money.
        """
        import json
        return f"[{self.fact_type} as of {self.computed_at.strftime('%Y-%m-%d')}]\n{json.dumps(self.payload, default=str)}"
