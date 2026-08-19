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
from typing import List, Tuple, Dict, Any

from provisioning_service.Models import SubscriptionPlan, PlanPrice, Feature, PlanFeature
from provisioning_service.core.db_config import SessionLocal

# ═══════════════════════════════════════════════════════════════════
# Plans.
#
# yearly = 10 x monthly  → "two months free" annual anchor (Phase D1).
# implementation_fee_minor — one-time fee guardrail (Phase D3).
# seat_block_price_minor — per-block monthly price for extra users;
#   block size is 5 seats (Phase D2, pending final block-pricing decision).
# is_public — listed on the website vs sales-only (Phase D4):
#   Starter/Growth/Business public; Enterprise/Distributor sales-only.
# ═══════════════════════════════════════════════════════════════════
PLANS: List[Dict[str, Any]] = [
    {
        "code": "starter",
        "name": "Starter Plan",
        "description": "Simple controlled procurement — up to 5 active users",
        "monthly": 14900,                      # £149/mo
        "is_public": True,
        "implementation_fee_minor": 0,
        "seat_block_price_minor": 3900,        # £39/mo per 5 extra seats
    },
    {
        "code": "growth",
        "name": "Growth Plan",
        "description": "Governed procurement for SMEs — up to 15 active users",
        "monthly": 39900,                      # £399/mo
        "is_public": True,
        "implementation_fee_minor": 0,
        "seat_block_price_minor": 7500,        # £75/mo per 5 extra seats
    },
    {
        "code": "business",
        "name": "Business Plan",
        "description": "Multi-site control and supplier orchestration — up to 40 active users",
        "monthly": 95000,                      # from £950/mo
        "is_public": True,
        "implementation_fee_minor": 150000,    # £1,500 one-time
        "seat_block_price_minor": 9900,        # £99/mo per 5 extra seats
    },
    {
        "code": "enterprise",
        "name": "Enterprise Plan",
        "description": "Full control-plane deployment — up to 100 active users",
        "monthly": 275000,                     # from £2,750/mo
        "is_public": False,                    # sales-only
        "implementation_fee_minor": 500000,    # £5,000 one-time
        "seat_block_price_minor": 14900,       # £149/mo per 5 extra seats
    },
    {
        "code": "distributor",
        "name": "Distributor Platform",
        "description": "Multi-tenant platform leverage — custom by sub-tenant model",
        "monthly": 0,                          # price on application
        "is_public": False,                    # sales-only
        "implementation_fee_minor": 0,         # quoted per rollout
        "seat_block_price_minor": 0,
    },
]

# Quarterly −5%; yearly = 10 × monthly ("two months free").
for _p in PLANS:
    _p["quarterly"] = round(_p["monthly"] * 3 * 0.95)
    _p["yearly"] = _p["monthly"] * 10

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


INTEGRATION_PACKS: List[Dict[str, Any]] = [
    {
        "pack_code": "standard",
        "pack_name": "Standard Integration Pack",
        "description": "ERP connector and structured data imports.",
        "stripe_product_id": "prod_V5eQsSpkx3FSOu",
        "stripe_price_id": "price_1U5T7SLrHi1hCr87VoVT9Jz8",
        "price_monthly_minor": 15000,  # £150.00
        "currency": "GBP",
        "billing_interval": "month",
    },
    {
        "pack_code": "advanced",
        "pack_name": "Advanced Integration Pack",
        "description": "API, cXML, EDI, and marketplace integrations.",
        "stripe_product_id": "prod_V5eQVUPuzWW7x6",
        "stripe_price_id": "price_1U5T7kLrHi1hCr87jR6Y3avz",
        "price_monthly_minor": 40000,  # £400.00
        "currency": "GBP",
        "billing_interval": "month",
    },
    {
        "pack_code": "enterprise",
        "pack_name": "Enterprise Integration Pack",
        "description": "Custom middleware, advanced monitoring, and direct support.",
        "stripe_product_id": "prod_V5eQ9zP16VvSNS",
        "stripe_price_id": "price_1U5T83LrHi1hCr87TBcyzeCo",
        "price_monthly_minor": 100000,  # £1,000.00 (from £1,000)
        "currency": "GBP",
        "billing_interval": "month",
    },
]

INTEGRATION_PACK_FEATURES: List[Tuple[str, str]] = [
    # Standard Pack
    ("standard", "erp.integration"),

    # Advanced Pack
    ("advanced", "api.integration"),
    ("advanced", "cxml.edi"),
    ("advanced", "marketplace.handoff"),
]


# ═══════════════════════════════════════════════════════════════════
# Seed functions (idempotent)
# ═══════════════════════════════════════════════════════════════════

def _seed_plans(session) -> int:
    existing = {p.code: p for p in session.query(SubscriptionPlan).all()}
    added = 0
    for p in PLANS:
        row = existing.get(p["code"])
        if row is None:
            session.add(SubscriptionPlan(
                plan_id=uuid.uuid4(),
                code=p["code"],
                name=p["name"],
                description=p["description"],
                is_active=True,
                is_public=p["is_public"],
                created_by="zeroque_admin",
            ))
            added += 1
        else:
            # Refresh descriptive fields + visibility (Phase D4)
            row.name = p["name"]
            row.description = p["description"]
            row.is_public = p["is_public"]
    if added:
        session.flush()
    return added


def _seed_prices(session) -> int:
    """Upsert plan pricing so annual-anchor / fee / seat-block changes propagate."""
    existing = {p.plan_code: p for p in session.query(PlanPrice).all()}
    added = 0
    for p in PLANS:
        row = existing.get(p["code"])
        if row is None:
            session.add(PlanPrice(
                plan_code=p["code"],
                currency="GBP",
                price_monthly_minor=p["monthly"],
                quarterly_discount_pct=5,
                yearly_discount_pct=16.67,  # two months free
                price_quarterly_minor=p["quarterly"],
                price_yearly_minor=p["yearly"],
                implementation_fee_minor=p["implementation_fee_minor"],
                seat_block_size=5,
                seat_block_price_minor=p["seat_block_price_minor"],
            ))
            added += 1
        else:
            row.price_monthly_minor = p["monthly"]
            row.price_quarterly_minor = p["quarterly"]
            row.price_yearly_minor = p["yearly"]
            row.yearly_discount_pct = 16.67
            row.implementation_fee_minor = p["implementation_fee_minor"]
            row.seat_block_size = 5
            row.seat_block_price_minor = p["seat_block_price_minor"]
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


def _seed_integration_packs(session) -> int:
    """Seeds (and idempotently refreshes pricing on) the IntegrationPack table."""
    from provisioning_service.Models import IntegrationPack
    existing = {p.pack_code: p for p in session.query(IntegrationPack).all()}
    added = 0
    for pack in INTEGRATION_PACKS:
        row = existing.get(pack["pack_code"])
        if row is None:
            session.add(IntegrationPack(
                pack_code=pack["pack_code"],
                pack_name=pack["pack_name"],
                description=pack.get("description"),
                stripe_product_id=pack.get("stripe_product_id"),
                stripe_price_id=pack.get("stripe_price_id"),
                price_monthly_minor=pack.get("price_monthly_minor"),
                currency=pack.get("currency", "GBP"),
                billing_interval=pack.get("billing_interval", "month"),
                is_active=True,
            ))
            added += 1
        else:
            # Refresh pricing/config in case Stripe IDs or prices change.
            row.pack_name = pack["pack_name"]
            row.description = pack.get("description")
            row.stripe_product_id = pack.get("stripe_product_id")
            row.stripe_price_id = pack.get("stripe_price_id")
            row.price_monthly_minor = pack.get("price_monthly_minor")
            row.currency = pack.get("currency", "GBP")
            row.billing_interval = pack.get("billing_interval", "month")
    if added:
        session.flush()
    return added


def _seed_integration_pack_features(session) -> int:
    """Seeds the IntegrationPackFeature table."""
    from provisioning_service.Models import IntegrationPackFeature
    existing_pairs = {
        (pf.pack_code, pf.feature_code) for pf in session.query(IntegrationPackFeature).all()
    }
    added = 0
    for pack_code, feature_code in INTEGRATION_PACK_FEATURES:
        if (pack_code, feature_code) not in existing_pairs:
            session.add(IntegrationPackFeature(
                pack_code=pack_code,
                feature_code=feature_code,
            ))
            existing_pairs.add((pack_code, feature_code))
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
        ip = _seed_integration_packs(session)
        ipf = _seed_integration_pack_features(session)
        session.commit()
        print(f"[OK] Plans & features seeded: {p} plans, {pr} prices, {f} features, {pf} mappings, {ip} packs, {ipf} pack_features")
    except Exception as e:
        session.rollback()
        print(f"[ERROR] Error seeding plans/features: {e}")
        raise
    finally:
        session.close()
