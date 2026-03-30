"""AiFi integration public API.

Import from this package rather than individual sub-modules so that internal
refactors never break endpoint code.

Example:
    from orders_service.aifi_integration import list_customers, create_order
    from orders_service.aifi_integration.exceptions import AiFiNotFoundError
    from orders_service.aifi_integration.schemas import CustomerCreate
"""

# ── Customers (Admin) ──────────────────────────────────────────────────────────
from .customers import (
    create_card,
    create_customer,
    create_entry_code,
    delete_card,
    get_customer,
    list_customers,
    remote_register_customer,
    set_default_card,
    update_card_token,
    update_customer,
)

# ── Customers (Customer App) ───────────────────────────────────────────────────
from .customers import (
    create_customer_entry_code,
    customer_login,
    customer_logout,
    customer_refresh_session,
    customer_register,
    enter_contest,
    get_customer_draft_order,
    get_customer_draft_orders,
    get_customer_order,
    get_my_profile,
    keycloak_password_reset,
    list_customer_entry_codes,
    list_customer_orders,
    list_customer_app_customers,
    process_order_payment,
    request_password_reset,
    search_customer_products,
    verify_password_reset,
)

# ── Products ───────────────────────────────────────────────────────────────────
from .products import (
    add_barcode,
    create_product,
    create_variant,
    delete_barcode,
    delete_product,
    delete_variant,
    get_default_variant,
    get_product,
    get_product_planogram,
    get_product_snapshots,
    get_tax_rates,
    list_categories,
    list_products,
    list_variants,
    get_variant,
    update_product,
    update_variant,
    upsert_product,
)

# ── Stores ─────────────────────────────────────────────────────────────────────
from .stores import (
    create_device_event,
    create_frame_annotation,
    create_shelf,
    create_shopper_event,
    create_store,
    delete_device_event,
    delete_shelf,
    get_all_visitors,
    get_bin_inventory,
    get_camera,
    get_customer_count,
    get_gondola,
    get_gondola_planogram,
    get_identity_matching,
    get_new_visitors,
    get_product_sell_through,
    get_shelf,
    get_store,
    get_store_health,
    get_store_planogram,
    get_store_status,
    get_unique_visitors,
    get_visitor_count,
    get_visitors_by_day,
    get_zone_shoppers,
    get_zones,
    list_cameras,
    list_gondola_shelves,
    list_gondolas,
    list_stores,
    remote_register_at_check_in,
    update_bin_inventory,
    update_shelf,
    update_shopper,
    update_store,
    verify_check_in_code,
    verify_entry_code,
)

# ── RFID Tags ──────────────────────────────────────────────────────────────────
from .tags import create_tag, get_tag, list_tags

# ── Payments ───────────────────────────────────────────────────────────────────
from .payments import initialize_payment_methods

# ── Store API (/api/aifi/*) ───────────────────────────────────────────────────
from .service import (
    checkout_zone_entered,
    checkout_zone_left,
    create_checkout,
    customer_entered,
    customer_walked_out,
    forward_restricted_product_interaction,
    forward_tracking_association,
    get_aifi_store_status,
    get_product_inventory,
    register_customer_with_token,
    store_verify_entry_code,
)

# ── Admin Orders ───────────────────────────────────────────────────────────────
from .service import (
    create_order,
    get_order,
    list_orders,
    retry_order,
    update_order,
)

# ── Admin Sessions ─────────────────────────────────────────────────────────────
from .service import (
    create_session_checkout,
    get_session_cart,
    list_sessions,
    update_session,
    update_session_cart,
)

# ── Contests / Audits / Config ────────────────────────────────────────────────
from .service import (
    create_contest,
    get_audit,
    get_config,
    get_retailer_config,
    list_audits,
    list_contests,
    update_retailer_config,
)

# ── Push webhook handlers ─────────────────────────────────────────────────────
from .shopify import (
    handle_push_cart_mutator,
    handle_push_checkout,
    handle_push_customer,
    handle_push_entry_code,
    handle_push_evaluate_order_price,
    handle_push_health,
    handle_push_identity_matching,
    handle_push_restricted_products,
    handle_push_tracking,
    handle_push_transition,
)

__all__ = [
    # Admin customers
    "create_card", "create_customer", "create_entry_code", "delete_card",
    "get_customer", "list_customers", "remote_register_customer",
    "set_default_card", "update_card_token", "update_customer",
    # Customer app
    "create_customer_entry_code", "customer_login", "customer_logout",
    "customer_refresh_session", "customer_register", "enter_contest",
    "get_customer_draft_order", "get_customer_draft_orders", "get_customer_order",
    "get_my_profile", "keycloak_password_reset", "list_customer_entry_codes",
    "list_customer_orders", "list_customer_app_customers", "process_order_payment",
    "request_password_reset", "search_customer_products", "verify_password_reset",
    # Products
    "add_barcode", "create_product", "create_variant", "delete_barcode",
    "delete_product", "delete_variant", "get_default_variant", "get_product",
    "get_product_planogram", "get_product_snapshots", "get_tax_rates",
    "list_categories", "list_products", "list_variants", "get_variant",
    "update_product", "update_variant", "upsert_product",
    # Stores
    "create_device_event", "create_frame_annotation", "create_shelf",
    "create_shopper_event", "create_store", "delete_device_event", "delete_shelf",
    "get_all_visitors", "get_bin_inventory", "get_camera", "get_customer_count",
    "get_gondola", "get_gondola_planogram", "get_identity_matching",
    "get_new_visitors", "get_product_sell_through", "get_shelf", "get_store",
    "get_store_health", "get_store_planogram", "get_store_status",
    "get_unique_visitors", "get_visitor_count", "get_visitors_by_day",
    "get_zone_shoppers", "get_zones", "list_cameras", "list_gondola_shelves",
    "list_gondolas", "list_stores", "remote_register_at_check_in",
    "update_bin_inventory", "update_shelf", "update_shopper", "update_store",
    "verify_check_in_code", "verify_entry_code",
    # Tags
    "create_tag", "get_tag", "list_tags",
    # Payments
    "initialize_payment_methods",
    # Store API
    "checkout_zone_entered", "checkout_zone_left", "create_checkout",
    "customer_entered", "customer_walked_out", "forward_restricted_product_interaction",
    "forward_tracking_association", "get_aifi_store_status", "get_product_inventory",
    "register_customer_with_token", "store_verify_entry_code",
    # Admin orders
    "create_order", "get_order", "list_orders", "retry_order", "update_order",
    # Admin sessions
    "create_session_checkout", "get_session_cart", "list_sessions",
    "update_session", "update_session_cart",
    # Contests / audits / config
    "create_contest", "get_audit", "get_config", "get_retailer_config",
    "list_audits", "list_contests", "update_retailer_config",
    # Push handlers
    "handle_push_cart_mutator", "handle_push_checkout", "handle_push_customer",
    "handle_push_entry_code", "handle_push_evaluate_order_price", "handle_push_health",
    "handle_push_identity_matching", "handle_push_restricted_products",
    "handle_push_tracking", "handle_push_transition",
]
