from procurement_service.services.dispute_routes import router as dispute_router
from procurement_service.services.fulfilment_routes import router as fulfilment_router
from procurement_service.services.invoice_routes import router as invoice_router
from procurement_service.services.ops_routes import router as ops_router
from procurement_service.services.order_routes import router as order_router
from procurement_service.services.procurement_routes import router as procurement_router
from procurement_service.services.vendor_routes import router as vendor_router


ALL_ROUTERS = [
    vendor_router,
    order_router,
    procurement_router,
    fulfilment_router,
    dispute_router,
    invoice_router,
    ops_router,
]
