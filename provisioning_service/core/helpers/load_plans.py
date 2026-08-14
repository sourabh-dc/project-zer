"""
Plan & Feature seeding — Pricing Architecture v1.2

Seeds the 5 subscription plans (Starter, Growth, Business, Enterprise,
Distributor Platform), their prices, and the capability features mapped
to each tier at startup.

Aligned to ZeroQue Pricing Architecture v1.2:
  Starter    £149/mo   up to 5 users    Simple controlled procurement
  Growth     £399/mo   up to 15 users   Governed procurement for SMEs
  Business   from £950/mo  up to 40     Multi-site + supplier orchestration
  Enterprise from £2,750/mo  up to 100  Full control-plane deployment
  Distributor POA / custom              Multi-tenant platform leverage
"""
import uuid
from typing import List, Tuple

from provisioning_service.Models import SubscriptionPlan, PlanPrice, Feature, PlanFeature
from provisioning_service.core.db_config import SessionLocal

# ═══════════════════════════════════════════════════════════════════
# Plans: (code, name, description, monthly_minor, quarterly_minor, yearly_minor)
# ═══════════════════════════════════════════════════════════════════
PLANS: List[Tuple[str, str, str, int, int, int]] = [
    (
        "starter",
        "Starter Plan",
        "Simple controlled procurement — up to 5 active users",
        14900, 42465, 160920,   # £149/mo, quarterly -5%, yearly -10%
    ),
    (
        "growth",
        "Growth Plan",
        "Governed procurement for SMEs — up to 15 active users",
        39900, 113715, 430920,  # £399/mo
    ),
    (
        "business",
        "Business Plan",
        "Multi-site control and supplier orchestration — up to 40 active users",
        95000, 270750, 1026000,  # from £950/mo
    ),
    (
        "enterprise",
        "Enterprise Plan",
        "Full control-plane deployment — up to 100 active users",
        275000, 783750, 2970000,  # from £2,750/mo
    ),
    (
        "distributor",
        "Distributor Platform",
        "Multi-tenant platform leverage — custom by sub-tenant model",
        0, 0, 0,  # price on application
    ),
]

# ═══════════════════════════════════════════════════════════════════
# Features: (code, name, description, cluster)
# ═══════════════════════════════════════════════════════════════════
FEATURES: List[Tuple[str, str, str, str]] = [
    # ── 1. Core Procurement Control ─────────────────────────────
    ("request.capture", "Purchase Requests", "Create and capture purchase requests", "core"),
    ("approvals.workflow", "Approval Workflow", "Basic approval routing and workflow", "core"),
    ("orders.orchestration", "Order Orchestration", "Orders and purchase order orchestration", "core"),
    ("supplier.records", "Supplier Records", "Maintain supplier records", "core"),
    ("product.records", "Product & Service Records", "Maintain product and service records", "core"),
    ("evidence.trail", "Evidence Trail", "Evidence capture and retention", "core"),
    ("audit.trail", "Audit Trail", "Append-only audit history", "core"),
    ("org.memory", "Organisational Memory", "Persistent organisational knowledge", "core"),
    # ── 2. Governance & Control ────────────────────────────────
    ("cost.centres", "Cost Centres", "Cost centre management", "governance"),
    ("budget.control", "Budget Control", "Budget allocation and enforcement", "governance"),
    ("approved.ranges", "Approved Ranges", "Curated approved product ranges", "governance"),
    ("approval.policies", "Approval Policies", "Configurable approval policies", "governance"),
    ("commercial.lock", "Commercial Lock", "Commercial approval lock", "governance"),
    ("role.permissions", "Role-Based Permissions", "Scoped role-based access", "governance"),
    ("exception.management", "Exception Management", "Approval exception handling", "governance"),
    ("policy.enforcement", "Policy Enforcement", "Deterministic policy enforcement", "governance"),
    ("risk.rules", "Risk Rules & Thresholds", "Risk rules and spend thresholds", "governance"),
    # ── 3. Supplier Orchestration ──────────────────────────────
    ("email.supplier", "Email Supplier Workflows", "Email-based supplier communication", "supplier"),
    ("supplier.acknowledgements", "Supplier Acknowledgements", "Supplier order acknowledgements", "supplier"),
    ("fulfilment.tracking", "Fulfilment Tracking", "Delivery and fulfilment tracking", "supplier"),
    ("api.integration", "API Integration", "Programmatic API integrations", "supplier"),
    ("cxml.edi", "cXML / EDI", "cXML and EDI supplier connectivity", "supplier"),
    ("marketplace.handoff", "Marketplace Handoff", "Marketplace handoff flows", "supplier"),
    # ── 4. Intelligence Layer ──────────────────────────────────
    ("contextual.intelligence", "Contextual Intelligence", "In-context decision support", "intelligence"),
    ("product.comparisons", "Product Comparisons", "Intelligent product comparison", "intelligence"),
    ("alternative.suggestions", "Alternative Suggestions", "Alternative product suggestions", "intelligence"),
    ("supplier.risk", "Supplier Risk Insights", "Supplier risk intelligence", "intelligence"),
    ("derived.knowledge", "Derived Knowledge Layer", "Derived organisational knowledge", "intelligence"),
    ("graph.visibility", "Graph Relationship Visibility", "Graph-based relationship insight", "intelligence"),
    ("advanced.reasoning", "Advanced Reasoning", "Guided actions and reasoning", "intelligence"),
    # ── 5. Operating Scale ─────────────────────────────────────
    ("multi.location", "Multi-Location Support", "Multiple location operation", "scale"),
    ("multi.site", "Multi-Site Operations", "Multiple site operation", "scale"),
    ("erp.integration", "ERP / Finance Integration", "ERP and finance system integration", "scale"),
    ("sso.security", "SSO & Advanced Security", "Single sign-on and advanced security", "scale"),
    ("high.availability", "High Availability", "High availability deployment", "scale"),
    ("custom.workflow", "Custom Workflow Support", "Custom workflow configuration", "scale"),
    ("priority.support", "Priority Support / SLA", "Enhanced support and SLAs", "scale"),
    # ── 6. Distributor Platform ────────────────────────────────
    ("tenant.subtenant.model", "Tenant / Sub-Tenant Model", "Sub-tenant management", "distributor"),
    ("multi.tenant.management", "Multi-Tenant Management", "Manage multiple tenant workspaces", "distributor"),
    ("customer.environment.management", "Customer Environment Management", "Manage customer environments", "distributor"),
    ("shared.integration.hub", "Shared Integration Hub", "Shared integration infrastructure", "distributor"),
    ("cross.tenant.analytics", "Cross-Tenant Analytics", "Analytics across tenants", "distributor"),
    ("white.label", "White-Label Experience", "Branded white-label experience", "distributor"),
    # ── Usage allowance ────────────────────────────────────────
    ("active.users", "Active Users", "Included active user allowance", "core"),
]

# ═══════════════════════════════════════════════════════════════════
# Plan → Feature mapping.
#
# Each entry: (plan_code, feature_code, enabled, limits_dict_or_None)
# A feature ABSENT from a plan's mapping = not available at that tier.
# limits may hold user counts or per-feature caps.
# ═══════════════════════════════════════════════════════════════════
_PLAN_FEATURE_MAP: List[Tuple[str, str, bool, dict]] = [
    # ── STARTER (5 users) ────────────────────────────────────────
    ("starter", "request.capture", True, None),
    ("starter", "approvals.workflow", True, None),
    ("starter", "orders.orchestration", True, None),
    ("starter", "product.records", True, None),
    ("starter", "evidence.trail", True, None),
    ("starter", "audit.trail", True, None),
    ("starter", "org.memory", True, None),
    ("starter", "supplier.records", True, {"max_value": 10}),
    ("starter", "cost.centres", True, {"max_value": 2}),
    ("starter", "active.users", True, {"max_value": 5}),
    # ── GROWTH (15 users) ────────────────────────────────────────
    ("growth", "request.capture", True, None),
    ("growth", "approvals.workflow", True, None),
    ("growth", "orders.orchestration", True, None),
    ("growth", "product.records", True, None),
    ("growth", "evidence.trail", True, None),
    ("growth", "audit.trail", True, None),
    ("growth", "org.memory", True, None),
    ("growth", "supplier.records", True, {"max_value": 25}),
    ("growth", "cost.centres", True, {"max_value": 10}),
    ("growth", "budget.control", True, None),
    ("growth", "approved.ranges", True, None),
    ("growth", "approval.policies", True, None),
    ("growth", "commercial.lock", True, None),
    ("growth", "role.permissions", True, None),
    ("growth", "supplier.acknowledgements", True, None),
    ("growth", "fulfilment.tracking", True, None),
    ("growth", "active.users", True, {"max_value": 15}),
    # ── BUSINESS (40 users) ──────────────────────────────────────
    ("business", "request.capture", True, None),
    ("business", "approvals.workflow", True, None),
    ("business", "orders.orchestration", True, None),
    ("business", "product.records", True, None),
    ("business", "evidence.trail", True, None),
    ("business", "audit.trail", True, None),
    ("business", "org.memory", True, None),
    ("business", "supplier.records", True, {"max_value": 100}),
    ("business", "cost.centres", True, {"max_value": 50}),
    ("business", "budget.control", True, None),
    ("business", "approved.ranges", True, None),
    ("business", "approval.policies", True, None),
    ("business", "commercial.lock", True, None),
    ("business", "role.permissions", True, None),
    ("business", "exception.management", True, None),
    ("business", "policy.enforcement", True, None),
    ("business", "email.supplier", True, None),
    ("business", "supplier.acknowledgements", True, None),
    ("business", "fulfilment.tracking", True, None),
    ("business", "multi.location", True, None),
    ("business", "multi.site", True, None),
    ("business", "custom.workflow", True, None),
    ("business", "tenant.subtenant.model", True, None),
    ("business", "active.users", True, {"max_value": 40}),
    # ── ENTERPRISE (100 users) ──────────────────────────────────
    ("enterprise", "request.capture", True, None),
    ("enterprise", "approvals.workflow", True, None),
    ("enterprise", "orders.orchestration", True, None),
    ("enterprise", "product.records", True, None),
    ("enterprise", "evidence.trail", True, None),
    ("enterprise", "audit.trail", True, None),
    ("enterprise", "org.memory", True, None),
    ("enterprise", "supplier.records", True, {"max_value": 500}),
    ("enterprise", "cost.centres", True, {"max_value": 200}),
    ("enterprise", "budget.control", True, None),
    ("enterprise", "approved.ranges", True, None),
    ("enterprise", "approval.policies", True, None),
    ("enterprise", "commercial.lock", True, None),
    ("enterprise", "role.permissions", True, None),
    ("enterprise", "exception.management", True, None),
    ("enterprise", "policy.enforcement", True, None),
    ("enterprise", "risk.rules", True, None),
    ("enterprise", "email.supplier", True, None),
    ("enterprise", "supplier.acknowledgements", True, None),
    ("enterprise", "fulfilment.tracking", True, None),
    ("enterprise", "api.integration", True, None),
    ("enterprise", "cxml.edi", True, None),
    ("enterprise", "marketplace.handoff", True, None),
    ("enterprise", "contextual.intelligence", True, None),
    ("enterprise", "product.comparisons", True, None),
    ("enterprise", "alternative.suggestions", True, None),
    ("enterprise", "supplier.risk", True, None),
    ("enterprise", "derived.knowledge", True, None),
    ("enterprise", "graph.visibility", True, None),
    ("enterprise", "advanced.reasoning", True, None),
    ("enterprise", "multi.location", True, None),
    ("enterprise", "multi.site", True, None),
    ("enterprise", "erp.integration", True, None),
    ("enterprise", "sso.security", True, None),
    ("enterprise", "high.availability", True, None),
    ("enterprise", "custom.workflow", True, None),
    ("enterprise", "priority.support", True, None),
    ("enterprise", "tenant.subtenant.model", True, None),
    ("enterprise", "active.users", True, {"max_value": 100}),
    # ── DISTRIBUTOR PLATFORM (custom) ────────────────────────────
    ("distributor", "request.capture", True, None),
    ("distributor", "approvals.workflow", True, None),
    ("distributor", "orders.orchestration", True, None),
    ("distributor", "product.records", True, None),
    ("distributor", "audit.trail", True, None),
    ("distributor", "budget.control", True, None),
    ("distributor", "approval.policies", True, None),
    ("distributor", "role.permissions", True, None),
    ("distributor", "policy.enforcement", True, None),
    ("distributor", "risk.rules", True, None),
    ("distributor", "supplier.acknowledgements", True, None),
    ("distributor", "api.integration", True, None),
    ("distributor", "cxml.edi", True, None),
    ("distributor", "graph.visibility", True, None),
    ("distributor", "sso.security", True, None),
    ("distributor", "high.availability", True, None),
    ("distributor", "priority.support", True, None),
    ("distributor", "tenant.subtenant.model", True, None),
    ("distributor", "multi.tenant.management", True, None),
    ("distributor", "customer.environment.management", True, None),
    ("distributor", "shared.integration.hub", True, None),
    ("distributor", "cross.tenant.analytics", True, None),
    ("distributor", "white.label", True, None),
]


# ═══════════════════════════════════════════════════════════════════
# Seed functions (idempotent)
# ═══════════════════════════════════════════════════════════════════

def _seed_plans(session) -> int:
    existing = {p.code for p in session.query(SubscriptionPlan).all()}
    added = 0
    for code, name, desc, monthly, quarterly, yearly in PLANS:
        if code not in existing:
            session.add(SubscriptionPlan(
                plan_id=uuid.uuid4(),
                code=code,
                name=name,
                description=desc,
                is_active=True,
                created_by="zeroque_admin",
            ))
            existing.add(code)
            added += 1
    if added:
        session.flush()
    return added


def _seed_prices(session) -> int:
    existing = {p.plan_code for p in session.query(PlanPrice).all()}
    added = 0
    for code, name, desc, monthly, quarterly, yearly in PLANS:
        if code not in existing:
            session.add(PlanPrice(
                plan_code=code,
                currency="GBP",
                price_monthly_minor=monthly,
                quarterly_discount_pct=5,
                yearly_discount_pct=10,
                price_quarterly_minor=quarterly,
                price_yearly_minor=yearly,
            ))
            existing.add(code)
            added += 1
    if added:
        session.flush()
    return added


def _seed_features(session) -> int:
    existing = {f.code for f in session.query(Feature).all()}
    added = 0
    for code, name, desc, cluster in FEATURES:
        if code not in existing:
            session.add(Feature(
                id=uuid.uuid4(),
                code=code,
                name=name,
                description=desc,
                cluster=cluster,
                usage_type="boolean",
                max_unit=None,
                reset_period="never",
                active=True,
            ))
            existing.add(code)
            added += 1
    if added:
        session.flush()
    return added


def _seed_plan_features(session) -> int:
    existing_pairs = {
        (pf.plan_code, pf.feature_code) for pf in session.query(PlanFeature).all()
    }
    added = 0
    for plan_code, feature_code, enabled, limits in _PLAN_FEATURE_MAP:
        if (plan_code, feature_code) not in existing_pairs:
            session.add(PlanFeature(
                id=uuid.uuid4(),
                plan_code=plan_code,
                feature_code=feature_code,
                enabled=enabled,
                limits=limits or {},
            ))
            existing_pairs.add((plan_code, feature_code))
            added += 1
    if added:
        session.flush()
    return added


def seed_plans_and_features():
    """Master seed: plans → prices → features → plan_features. Idempotent."""
    session = SessionLocal()
    try:
        p = _seed_plans(session)
        pr = _seed_prices(session)
        f = _seed_features(session)
        pf = _seed_plan_features(session)
        session.commit()
        print(f"[OK] Plans & features seeded: {p} plans, {pr} prices, {f} features, {pf} mappings")
    except Exception as e:
        session.rollback()
        print(f"[ERROR] Error seeding plans/features: {e}")
        raise
    finally:
        session.close()
