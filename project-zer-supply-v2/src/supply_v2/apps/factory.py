from __future__ import annotations

from typing import Optional

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from supply_v2.dependencies import AppContainer
from supply_v2.observability import attach_observability
from supply_v2.persistent import PersistentPlatform
from supply_v2.platform import SupplyPlatform
from supply_v2.routes.dispute_routes import build_dispute_router
from supply_v2.routes.fulfilment_routes import build_fulfilment_router
from supply_v2.routes.invoice_routes import build_invoice_router
from supply_v2.routes.ops_routes import build_ops_router
from supply_v2.routes.order_routes import build_order_router
from supply_v2.routes.procurement_routes import build_procurement_router
from supply_v2.routes.vendor_routes import build_vendor_router


OPENAPI_TAGS = [
    {"name": "vendors", "description": "Vendor master and vendor portal reads."},
    {"name": "orders", "description": "Customer orders, receipts, and finalization."},
    {"name": "procurement", "description": "Purchase order reads, acknowledgement, reallocation, and cancellation."},
    {"name": "fulfilment", "description": "Vendor shipment creation and fulfilment updates."},
    {"name": "disputes", "description": "Vendor and customer dispute workflows."},
    {"name": "invoices", "description": "Invoice ingest and SLA visibility."},
    {"name": "ops", "description": "Dead-letter replay, RBAC admin, audit, and maintenance."},
]


def _attach_health(app: FastAPI) -> FastAPI:
    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready():
        return {"status": "ready"}

    @app.get("/metrics")
    def metrics():
        return {"service": app.title, "status": "ok"}

    return app


def _attach_openapi(app: FastAPI) -> FastAPI:
    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version="2.0.0",
            description=(
                "Supply V2 is a dropship procurement platform that splits customer orders into vendor purchase orders, "
                "tracks shipments and receipts, resolves disputes, performs invoice matching, and protects every route "
                "with authentication, RBAC, and policy decisions."
            ),
            routes=app.routes,
            tags=OPENAPI_TAGS,
        )
        schema.setdefault("components", {}).setdefault("securitySchemes", {})
        schema["components"]["securitySchemes"]["BearerAuth"] = {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
        schema["components"]["securitySchemes"]["TenantHeaderAuth"] = {
            "type": "apiKey",
            "in": "header",
            "name": "X-Tenant-Id",
        }
        schema["components"]["securitySchemes"]["InternalKeyAuth"] = {
            "type": "apiKey",
            "in": "header",
            "name": "X-Internal-Api-Key",
        }
        schema["info"]["contact"] = {"name": "Project Zer Platform Team"}
        app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = custom_openapi
    return app


def build_container(
    platform: Optional[SupplyPlatform] = None,
    persistent: Optional[PersistentPlatform] = None,
) -> AppContainer:
    return AppContainer(platform=platform, persistent=persistent)


def create_combined_app(
    platform: Optional[SupplyPlatform] = None,
    persistent: Optional[PersistentPlatform] = None,
) -> FastAPI:
    container = build_container(platform=platform, persistent=persistent)
    app = attach_observability(_attach_openapi(_attach_health(FastAPI(title="Project Zer Supply V2", openapi_tags=OPENAPI_TAGS))))
    app.state.container = container

    @app.get("/events")
    def events():
        return {"events": container.platform.store.events}

    app.include_router(build_vendor_router(container))
    app.include_router(build_order_router(container))
    app.include_router(build_procurement_router(container))
    app.include_router(build_fulfilment_router(container))
    app.include_router(build_dispute_router(container))
    app.include_router(build_invoice_router(container))
    app.include_router(build_ops_router(container))
    return app


def create_order_app(platform: Optional[SupplyPlatform] = None, persistent: Optional[PersistentPlatform] = None) -> FastAPI:
    container = build_container(platform=platform, persistent=persistent)
    app = attach_observability(_attach_openapi(_attach_health(FastAPI(title="Order Service", openapi_tags=OPENAPI_TAGS))))
    app.include_router(build_order_router(container))
    return app


def create_procurement_app(platform: Optional[SupplyPlatform] = None, persistent: Optional[PersistentPlatform] = None) -> FastAPI:
    container = build_container(platform=platform, persistent=persistent)
    app = attach_observability(_attach_openapi(_attach_health(FastAPI(title="Procurement Service", openapi_tags=OPENAPI_TAGS))))
    app.include_router(build_procurement_router(container))
    return app


def create_vendor_app(platform: Optional[SupplyPlatform] = None, persistent: Optional[PersistentPlatform] = None) -> FastAPI:
    container = build_container(platform=platform, persistent=persistent)
    app = attach_observability(_attach_openapi(_attach_health(FastAPI(title="Vendor Service", openapi_tags=OPENAPI_TAGS))))
    app.include_router(build_vendor_router(container))
    return app


def create_dispute_app(platform: Optional[SupplyPlatform] = None, persistent: Optional[PersistentPlatform] = None) -> FastAPI:
    container = build_container(platform=platform, persistent=persistent)
    app = attach_observability(_attach_openapi(_attach_health(FastAPI(title="Dispute Service", openapi_tags=OPENAPI_TAGS))))
    app.include_router(build_dispute_router(container))
    return app


def create_fulfilment_app(platform: Optional[SupplyPlatform] = None, persistent: Optional[PersistentPlatform] = None) -> FastAPI:
    container = build_container(platform=platform, persistent=persistent)
    app = attach_observability(_attach_openapi(_attach_health(FastAPI(title="Fulfilment Service", openapi_tags=OPENAPI_TAGS))))
    app.include_router(build_fulfilment_router(container))
    return app


def create_invoice_app(platform: Optional[SupplyPlatform] = None, persistent: Optional[PersistentPlatform] = None) -> FastAPI:
    container = build_container(platform=platform, persistent=persistent)
    app = attach_observability(_attach_openapi(_attach_health(FastAPI(title="Invoice Service", openapi_tags=OPENAPI_TAGS))))
    app.include_router(build_invoice_router(container))
    return app


def create_ops_app(platform: Optional[SupplyPlatform] = None, persistent: Optional[PersistentPlatform] = None) -> FastAPI:
    container = build_container(platform=platform, persistent=persistent)
    app = attach_observability(_attach_openapi(_attach_health(FastAPI(title="Ops Service", openapi_tags=OPENAPI_TAGS))))
    app.include_router(build_ops_router(container))
    return app
