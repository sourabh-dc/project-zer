"""
Derived Knowledge Layer — data models.

WHY a Derived Knowledge Layer?
  Some questions require expensive multi-table joins or graph traversals
  that are slow to run on every query. Precomputing these facts means:
  - Instant answers for common analytical questions
  - Consistent numbers across multiple queries in the same session
  - LLM reasons over summaries instead of raw rows (less hallucination risk)
  - Facts are versioned — we know exactly when they were computed

Governance metadata (per spec §5):
  Each DerivedFact carries provenance: owner, definition, computation method,
  source lineage, confidence score, and completeness flag. This makes every
  fact explainable — a user or auditor can see exactly how it was produced.

Fact types (see facts.py for computation):
  top_categories_by_spend    — top 10 categories ranked by spend this quarter
  approval_policy_summary    — summary of active policies per tenant
  org_unit_budget_status     — budget utilization % per org unit
  vendor_activity_summary    — vendor order counts + last order date
  approved_product_count     — total approved products per tenant/org unit
  supplier_performance       — on-time rate, lead time, defect rate per vendor
  supplier_risk              — risk score per vendor (lateness + defects + concentration)
  spend_by_department        — spend totals broken down by department
  product_substitution_map   — alternative products by category

Storage: Postgres derived_knowledge table (see store.py for schema).
Versioned: each recomputation creates a new row, old rows kept for audit.
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Canonical fact type identifiers
# ---------------------------------------------------------------------------

FACT_TOP_CATEGORIES_BY_SPEND = "top_categories_by_spend"
FACT_APPROVAL_POLICY_SUMMARY = "approval_policy_summary"
FACT_ORG_UNIT_BUDGET_STATUS  = "org_unit_budget_status"
FACT_VENDOR_ACTIVITY_SUMMARY = "vendor_activity_summary"
FACT_APPROVED_PRODUCT_COUNT  = "approved_product_count"

# New Phase-1 required facts (spec §21)
FACT_SUPPLIER_PERFORMANCE    = "supplier_performance"
FACT_SUPPLIER_RISK           = "supplier_risk"
FACT_SPEND_BY_DEPARTMENT     = "spend_by_department"
FACT_PRODUCT_SUBSTITUTION    = "product_substitution_map"


# ---------------------------------------------------------------------------
# Governance registry — metadata for every fact type (spec §5)
# ---------------------------------------------------------------------------

#: Each entry: owner, definition, computation_method, source_lineage
FACT_REGISTRY: Dict[str, Dict[str, Any]] = {
    FACT_TOP_CATEGORIES_BY_SPEND: {
        "owner":              "procurement-analytics",
        "definition":         "Top 10 product categories ranked by total spend in the current quarter",
        "computation_method": "SUM(order_items.unit_price * quantity) GROUP BY category, WHERE orders.created_at >= quarter_start",
        "source_lineage":     ["orders", "order_items", "products", "categories"],
    },
    FACT_APPROVAL_POLICY_SUMMARY: {
        "owner":              "governance",
        "definition":         "Summary of active approval policies for a tenant",
        "computation_method": "SELECT policies WHERE status=active ORDER BY threshold",
        "source_lineage":     ["policies"],
    },
    FACT_ORG_UNIT_BUDGET_STATUS: {
        "owner":              "finance",
        "definition":         "Budget allocation and utilization percentage per org unit for current period",
        "computation_method": "SELECT budgets JOIN org_units WHERE period covers NOW()",
        "source_lineage":     ["budgets", "org_units"],
    },
    FACT_VENDOR_ACTIVITY_SUMMARY: {
        "owner":              "procurement-analytics",
        "definition":         "Vendor order counts and last activity date over the past 90 days",
        "computation_method": "COUNT(DISTINCT orders) GROUP BY vendor, WHERE created_at >= NOW()-90d",
        "source_lineage":     ["orders", "vendors"],
    },
    FACT_APPROVED_PRODUCT_COUNT: {
        "owner":              "governance",
        "definition":         "Count of approved products per approved range, from the governance graph",
        "computation_method": "Neo4j: MATCH (Tenant)-[:HAS_APPROVED_RANGE]->(ApprovedRange)-[:INCLUDES*]->(Product)",
        "source_lineage":     ["neo4j:ApprovedRange", "neo4j:Product", "neo4j:Tenant"],
    },
    FACT_SUPPLIER_PERFORMANCE: {
        "owner":              "procurement-analytics",
        "definition":         "Supplier performance metrics: on-time delivery rate, average lead time, defect rate",
        "computation_method": "Aggregation over orders.actual_delivery_date vs expected, plus quality incidents",
        "source_lineage":     ["orders", "vendors"],
    },
    FACT_SUPPLIER_RISK: {
        "owner":              "risk",
        "definition":         "Composite supplier risk score (0-100) based on lateness, defects, and concentration",
        "computation_method": "Weighted score: late_rate*40 + defect_rate*40 + concentration*20",
        "source_lineage":     ["orders", "order_items", "vendors"],
    },
    FACT_SPEND_BY_DEPARTMENT: {
        "owner":              "finance",
        "definition":         "Total spend broken down by department (top-level org units) for the current quarter",
        "computation_method": "SUM(purchase_requests.total_amount) GROUP BY org_unit.department",
        "source_lineage":     ["purchase_requests", "users", "org_units"],
    },
    FACT_PRODUCT_SUBSTITUTION: {
        "owner":              "procurement-analytics",
        "definition":         "For each category, a ranked list of products that can substitute for each other",
        "computation_method": "Products within same category, sorted by similarity of attributes and historical co-purchase",
        "source_lineage":     ["products", "categories", "order_items"],
    },
}


# ---------------------------------------------------------------------------
# Outbox trigger map — which events recompute which facts
# ---------------------------------------------------------------------------

FACT_TRIGGERS: Dict[str, list] = {
    "purchase_request": [
        FACT_TOP_CATEGORIES_BY_SPEND,
        FACT_VENDOR_ACTIVITY_SUMMARY,
        FACT_SPEND_BY_DEPARTMENT,
        FACT_SUPPLIER_PERFORMANCE,
        FACT_SUPPLIER_RISK,
    ],
    "approved_range": [
        FACT_APPROVED_PRODUCT_COUNT,
        FACT_APPROVAL_POLICY_SUMMARY,
        FACT_PRODUCT_SUBSTITUTION,
    ],
    "policy": [
        FACT_APPROVAL_POLICY_SUMMARY,
    ],
    "budget": [
        FACT_ORG_UNIT_BUDGET_STATUS,
        FACT_SPEND_BY_DEPARTMENT,
    ],
    "org_unit": [
        FACT_ORG_UNIT_BUDGET_STATUS,
        FACT_SPEND_BY_DEPARTMENT,
    ],
    "vendor": [
        FACT_SUPPLIER_PERFORMANCE,
        FACT_SUPPLIER_RISK,
        FACT_VENDOR_ACTIVITY_SUMMARY,
    ],
    "product": [
        FACT_PRODUCT_SUBSTITUTION,
    ],
}


# ---------------------------------------------------------------------------
# Engine relevance — which facts to inject per engine hint
# ---------------------------------------------------------------------------

FACT_ENGINE_RELEVANCE: Dict[str, list] = {
    "sql": [
        FACT_TOP_CATEGORIES_BY_SPEND,
        FACT_ORG_UNIT_BUDGET_STATUS,
        FACT_VENDOR_ACTIVITY_SUMMARY,
        FACT_SUPPLIER_PERFORMANCE,
        FACT_SUPPLIER_RISK,
        FACT_SPEND_BY_DEPARTMENT,
    ],
    "graph": [
        FACT_APPROVAL_POLICY_SUMMARY,
        FACT_APPROVED_PRODUCT_COUNT,
    ],
    "vector": [
        FACT_APPROVED_PRODUCT_COUNT,
        FACT_PRODUCT_SUBSTITUTION,
    ],
    "hybrid": [
        FACT_TOP_CATEGORIES_BY_SPEND,
        FACT_APPROVAL_POLICY_SUMMARY,
        FACT_ORG_UNIT_BUDGET_STATUS,
        FACT_SUPPLIER_PERFORMANCE,
        FACT_SUPPLIER_RISK,
        FACT_SPEND_BY_DEPARTMENT,
    ],
    "unknown": [
        FACT_TOP_CATEGORIES_BY_SPEND,
        FACT_APPROVAL_POLICY_SUMMARY,
        FACT_SUPPLIER_PERFORMANCE,
    ],
}


# ---------------------------------------------------------------------------
# DerivedFact dataclass — with full governance metadata (spec §5)
# ---------------------------------------------------------------------------

@dataclass
class DerivedFact:
    """A single precomputed business fact for a tenant.

    Governance fields (spec §5) make every fact traceable and explainable:
      owner              — team responsible for this fact's definition
      definition         — human-readable description of what this fact represents
      computation_method — how it was computed (SQL/Cypher/formula description)
      source_lineage     — which tables/nodes were used as source data
      confidence_score   — [0.0, 1.0] — 1.0 = fully confident, < 1.0 = partial data
      is_complete        — False if source data was missing or query returned no rows
    """
    fact_type:          str
    tenant_id:          str
    payload:            Dict[str, Any]
    version:            int = 1
    computed_at:        datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id:                 str = field(default_factory=lambda: str(uuid.uuid4()))

    # Governance metadata — populated from FACT_REGISTRY at construction time
    owner:              str = "system"
    definition:         str = ""
    computation_method: str = ""
    source_lineage:     List[str] = field(default_factory=list)
    confidence_score:   float = 1.0    # 1.0 = full data; <1.0 = partial; 0.0 = no data
    is_complete:        bool = True

    def __post_init__(self):
        """Populate governance metadata from registry if not explicitly set."""
        if self.fact_type in FACT_REGISTRY and self.definition == "":
            reg = FACT_REGISTRY[self.fact_type]
            self.owner              = reg.get("owner", self.owner)
            self.definition         = reg.get("definition", "")
            self.computation_method = reg.get("computation_method", "")
            self.source_lineage     = reg.get("source_lineage", [])

    def to_context_snippet(self) -> str:
        """Compact text for LLM prompt injection."""
        import json
        confidence_note = f" [confidence: {self.confidence_score:.0%}]" if self.confidence_score < 1.0 else ""
        freshness = self.computed_at.strftime('%Y-%m-%d %H:%M UTC')
        return (
            f"[{self.fact_type} | as of {freshness}{confidence_note}]\n"
            f"{json.dumps(self.payload, default=str)}"
        )

    def to_governance_dict(self) -> Dict[str, Any]:
        """Full governance metadata for audit / API response."""
        return {
            "fact_type":          self.fact_type,
            "owner":              self.owner,
            "definition":         self.definition,
            "computation_method": self.computation_method,
            "source_lineage":     self.source_lineage,
            "confidence_score":   self.confidence_score,
            "is_complete":        self.is_complete,
            "computed_at":        self.computed_at.isoformat(),
            "version":            self.version,
        }
