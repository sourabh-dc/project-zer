"""
handler_registry.py
-------------------
Single source of truth for outbox event handler registration.

Used by BOTH the API process (main.py) and the standalone worker
(consumer_standalone.py) so the two can never drift apart.

Registration order matters: graph/vector handlers run first, derived-fact
handlers run after (they recompute facts that depend on graph data).
"""
from data_intelligence_service.core.outbox_consumer import register_handler

# Graph handlers
from data_intelligence_service.graph.handlers import (
    tenant_handler, site_handler, store_handler, store_product_handler,
    user_handler, org_unit_handler, product_handler, category_handler,
    vendor_handler, role_handler, cost_centre_handler, approved_range_handler,
    policy_handler, mandate_handler,
)

# Vector handler
from data_intelligence_service.vector.handlers.product_embedding_handler import (
    handle as vector_product_handler,
)

# Derived knowledge handlers
from data_intelligence_service.intelligence.derived import handlers as derived_handlers


def register_all_handlers():
    """Register every outbox event handler (graph + vector + derived)."""
    # ── Graph handlers ────────────────────────────────────────────
    register_handler("tenant", tenant_handler.handle)
    register_handler("site", site_handler.handle)
    register_handler("store", store_handler.handle)
    register_handler("store_product", store_product_handler.handle)
    register_handler("user", user_handler.handle)
    register_handler("org_unit", org_unit_handler.handle)
    register_handler("product", product_handler.handle)
    register_handler("category", category_handler.handle)
    register_handler("vendor", vendor_handler.handle)
    register_handler("role", role_handler.handle)
    register_handler("role_permission", role_handler.handle)
    register_handler("user_role", role_handler.handle)
    register_handler("cost_centre", cost_centre_handler.handle)
    register_handler("user_cost_centre", cost_centre_handler.handle)
    register_handler("org_unit_assignment", org_unit_handler.handle)
    register_handler("approved_range", approved_range_handler.handle)
    register_handler("policy", policy_handler.handle)
    register_handler("policy_rule", policy_handler.handle)
    register_handler("policy_assignment", policy_handler.handle)
    register_handler("approval_policy", policy_handler.handle)
    register_handler("supplier", vendor_handler.handle)
    register_handler("mandate", mandate_handler.handle)

    # ── Vector handlers ───────────────────────────────────────────
    register_handler("product", vector_product_handler)

    # ── Derived knowledge handlers ────────────────────────────────
    # Run AFTER graph/vector handlers so the graph is already updated when
    # facts that depend on graph data (approved_product_count) are computed.
    register_handler("purchase_request", derived_handlers.handle_purchase_request)
    register_handler("approved_range",   derived_handlers.handle_approved_range)
    register_handler("budget",           derived_handlers.handle_budget)
    register_handler("policy",           derived_handlers.handle_policy)
    register_handler("org_unit",         derived_handlers.handle_org_unit)
    register_handler("vendor",           derived_handlers.handle_vendor)
    register_handler("product",          derived_handlers.handle_product)
