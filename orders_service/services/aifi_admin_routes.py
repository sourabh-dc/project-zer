"""ADMIN API endpoints — thin controllers proxying to AiFi's /api/admin/v2/* endpoints.

Organised into sub-sections: customers, products, stores, orders, sessions,
tags, contests/audits, and configuration. All AiFi logic lives in the
aifi_integration package.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from orders_service.aifi_integration import (
    # customers
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
    # products
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
    # stores
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
    # tags
    create_tag,
    get_tag,
    list_tags,
    # orders
    create_order,
    get_order,
    list_orders,
    retry_order,
    update_order,
    # sessions
    create_session_checkout,
    get_session_cart,
    list_sessions,
    update_session,
    update_session_cart,
    # contests / audits / config
    create_contest,
    get_audit,
    get_config,
    get_retailer_config,
    list_audits,
    list_contests,
    update_retailer_config,
)
from orders_service.aifi_integration.exceptions import AiFiError, AiFiNotFoundError
from orders_service.aifi_integration.schemas import (
    AdminCheckoutCreate,
    BarcodeAdd,
    CardCreate,
    CardTokenUpdate,
    CartUpdate,
    ContestCreate,
    CustomerCreate,
    CustomerUpdate,
    DeviceEventCreate,
    EntryCodeCreate,
    EntryCodeVerifyAdmin,
    FrameAnnotationEvent,
    InventoryUpdate,
    OrderCreate,
    OrderUpdate,
    ProductCreate,
    ProductUpdate,
    ProductUpsert,
    ProductVariantCreate,
    ProductVariantUpdate,
    RemoteRegisterRequest,
    RetailerConfigUpdate,
    SessionUpdate,
    ShelfCreate,
    ShelfUpdate,
    ShopperEvent,
    ShopperUpdate,
    StoreCreate,
    StoreUpdate,
    TagCreate,
)

router = APIRouter(prefix="/aifi/admin", tags=["AiFi — Admin API"])


def _http(exc: AiFiError) -> HTTPException:
    return HTTPException(status_code=exc.status_code or 502, detail=str(exc))


def _404(exc: AiFiNotFoundError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


# ═════════════════════════════════════════════════════════════════════════════
# CUSTOMERS
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/customers", summary="List customers")
async def list_customers_endpoint(
    external_id: Optional[str] = Query(None),
    email: Optional[str] = Query(None),
    payment_instrument_id: Optional[str] = Query(None, alias="paymentInstrumentId"),
    min_created_at: Optional[str] = Query(None),
    max_created_at: Optional[str] = Query(None),
    count: int = Query(50, ge=1, le=200),
    sort: Optional[str] = Query(None),
    direction: str = Query("asc", pattern="^(asc|desc)$"),
):
    try:
        return await list_customers(
            external_id=external_id,
            email=email,
            payment_instrument_id=payment_instrument_id,
            min_created_at=min_created_at,
            max_created_at=max_created_at,
            count=count,
            sort=sort,
            direction=direction,
        )
    except AiFiError as exc:
        raise _http(exc)


@router.post("/customers", status_code=201, summary="Create customer")
async def create_customer_endpoint(body: CustomerCreate):
    try:
        return await create_customer(body)
    except AiFiError as exc:
        raise _http(exc)


@router.post("/customers/remote-register", status_code=201, summary="Remote register customer")
async def remote_register_customer_endpoint(body: RemoteRegisterRequest):
    try:
        return await remote_register_customer(body)
    except AiFiError as exc:
        raise _http(exc)


@router.get("/customers/{customer_id}", summary="Get customer")
async def get_customer_endpoint(customer_id: int):
    try:
        return await get_customer(customer_id)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.patch("/customers/{customer_id}", summary="Update customer")
async def update_customer_endpoint(customer_id: int, body: CustomerUpdate):
    try:
        return await update_customer(customer_id, body)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.post("/customers/{customer_id}/entry-codes", status_code=201, summary="Create entry code")
async def create_entry_code_endpoint(customer_id: int, body: EntryCodeCreate):
    try:
        return await create_entry_code(customer_id, body)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.patch("/customers/{customer_id}/card-token", summary="Update card token")
async def update_card_token_endpoint(customer_id: int, body: CardTokenUpdate):
    try:
        return await update_card_token(customer_id, body)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.post("/customers/{customer_id}/card", status_code=201, summary="Add payment card")
async def create_card_endpoint(customer_id: int, body: CardCreate):
    try:
        return await create_card(customer_id, body)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.delete("/customers/{customer_id}/card/{card_id}", summary="Delete payment card")
async def delete_card_endpoint(customer_id: int, card_id: int):
    try:
        return await delete_card(customer_id, card_id)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.patch("/customers/{customer_id}/card/{card_id}/default", summary="Set default card")
async def set_default_card_endpoint(customer_id: int, card_id: int):
    try:
        return await set_default_card(customer_id, card_id)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


# ═════════════════════════════════════════════════════════════════════════════
# PRODUCTS
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/products", summary="List products")
async def list_products_endpoint(
    name: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    sku: Optional[str] = Query(None),
    barcode: Optional[str] = Query(None),
    external_id: Optional[str] = Query(None, alias="externalId"),
    count: int = Query(50, ge=1, le=200),
    sort: Optional[str] = Query(None),
    direction: str = Query("asc", pattern="^(asc|desc)$"),
):
    try:
        return await list_products(
            name=name, category=category, sku=sku, barcode=barcode,
            external_id=external_id, count=count, sort=sort, direction=direction,
        )
    except AiFiError as exc:
        raise _http(exc)


@router.post("/products", status_code=201, summary="Create product")
async def create_product_endpoint(body: ProductCreate):
    try:
        return await create_product(body)
    except AiFiError as exc:
        raise _http(exc)


@router.put("/products", summary="Upsert product by externalId")
async def upsert_product_endpoint(body: ProductUpsert):
    try:
        return await upsert_product(body)
    except AiFiError as exc:
        raise _http(exc)


@router.get("/products/categories", summary="List product categories")
async def list_categories_endpoint():
    try:
        return await list_categories()
    except AiFiError as exc:
        raise _http(exc)


@router.get("/products/snapshots", summary="Get product snapshots")
async def get_snapshots_endpoint():
    try:
        return await get_product_snapshots()
    except AiFiError as exc:
        raise _http(exc)


@router.get("/products/taxrates", summary="Get tax rates")
async def get_tax_rates_endpoint():
    try:
        return await get_tax_rates()
    except AiFiError as exc:
        raise _http(exc)


@router.get("/products/variants", summary="List all variants")
async def list_variants_endpoint():
    try:
        return await list_variants()
    except AiFiError as exc:
        raise _http(exc)


@router.get("/products/variants/{variant_id}", summary="Get variant")
async def get_variant_endpoint(variant_id: int):
    try:
        return await get_variant(variant_id)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.patch("/products/variants/{variant_id}", summary="Update variant")
async def update_variant_endpoint(variant_id: int, body: ProductVariantUpdate):
    try:
        return await update_variant(variant_id, body)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.delete("/products/variants/{variant_id}", summary="Delete variant")
async def delete_variant_endpoint(variant_id: int):
    try:
        return await delete_variant(variant_id)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.post("/products/variants/{variant_id}/barcodes", status_code=201, summary="Add barcode to variant")
async def add_barcode_endpoint(variant_id: int, body: BarcodeAdd):
    try:
        return await add_barcode(variant_id, body.barcode)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.delete("/products/variants/{variant_id}/barcodes/{barcode}", summary="Remove barcode from variant")
async def delete_barcode_endpoint(variant_id: int, barcode: str):
    try:
        return await delete_barcode(variant_id, barcode)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.get("/products/{product_id}", summary="Get product")
async def get_product_endpoint(product_id: int):
    try:
        return await get_product(product_id)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.put("/products/{product_id}", summary="Update product")
async def update_product_endpoint(product_id: int, body: ProductUpdate):
    try:
        return await update_product(product_id, body)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.delete("/products/{product_id}", summary="Delete product")
async def delete_product_endpoint(product_id: int):
    try:
        return await delete_product(product_id)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.get("/products/{product_id}/planogram", summary="Get product planogram")
async def get_product_planogram_endpoint(product_id: int):
    try:
        return await get_product_planogram(product_id)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.get("/products/{product_id}/variants", summary="List variants for product")
async def list_product_variants_endpoint(product_id: int):
    try:
        return await list_variants(product_id=product_id)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.post("/products/{product_id}/variants", status_code=201, summary="Create variant for product")
async def create_variant_endpoint(product_id: int, body: ProductVariantCreate):
    try:
        return await create_variant(product_id, body)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.get("/products/{product_id}/variants/default", summary="Get default variant")
async def get_default_variant_endpoint(product_id: int):
    try:
        return await get_default_variant(product_id)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


# ═════════════════════════════════════════════════════════════════════════════
# STORES
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/stores", summary="List stores")
async def list_stores_endpoint():
    try:
        return await list_stores()
    except AiFiError as exc:
        raise _http(exc)


@router.post("/stores", status_code=201, summary="Create store")
async def create_store_endpoint(body: StoreCreate):
    try:
        return await create_store(body)
    except AiFiError as exc:
        raise _http(exc)


@router.get("/stores/{store_id}", summary="Get store")
async def get_store_endpoint(store_id: str):
    try:
        return await get_store(store_id)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.patch("/stores/{store_id}", summary="Update store")
async def update_store_endpoint(store_id: str, body: StoreUpdate):
    try:
        return await update_store(store_id, body)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.get("/stores/{store_id}/status", summary="Get store status")
async def get_store_status_endpoint(store_id: str):
    try:
        return await get_store_status(store_id)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.get("/stores/{store_id}/health", summary="Get store health")
async def get_store_health_endpoint(store_id: str):
    try:
        return await get_store_health(store_id)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.get("/stores/{store_id}/planogram", summary="Get store planogram")
async def get_store_planogram_endpoint(store_id: str):
    try:
        return await get_store_planogram(store_id)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.get("/stores/{store_id}/planogram/{gondola_id}", summary="Get gondola planogram")
async def get_gondola_planogram_endpoint(store_id: str, gondola_id: str):
    try:
        return await get_gondola_planogram(store_id, gondola_id)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


# ── Gondolas ──────────────────────────────────────────────────────────────────

@router.get("/stores/{store_id}/gondolas", summary="List gondolas")
async def list_gondolas_endpoint(store_id: str):
    try:
        return await list_gondolas(store_id)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.get("/stores/{store_id}/gondolas/{gondola_id}", summary="Get gondola")
async def get_gondola_endpoint(store_id: str, gondola_id: str):
    try:
        return await get_gondola(store_id, gondola_id)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.get("/stores/{store_id}/gondolas/{gondola_id}/shelves", summary="List shelves in gondola")
async def list_gondola_shelves_endpoint(store_id: str, gondola_id: str):
    try:
        return await list_gondola_shelves(store_id, gondola_id)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


# ── Shelves ───────────────────────────────────────────────────────────────────

@router.post("/stores/{store_id}/shelves", status_code=201, summary="Create shelf")
async def create_shelf_endpoint(store_id: str, body: ShelfCreate):
    try:
        return await create_shelf(store_id, body)
    except AiFiError as exc:
        raise _http(exc)


@router.get("/stores/{store_id}/shelves/{shelf_id}", summary="Get shelf")
async def get_shelf_endpoint(store_id: str, shelf_id: str):
    try:
        return await get_shelf(store_id, shelf_id)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.patch("/stores/{store_id}/shelves/{shelf_id}", summary="Update shelf")
async def update_shelf_endpoint(store_id: str, shelf_id: str, body: ShelfUpdate):
    try:
        return await update_shelf(store_id, shelf_id, body)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.delete("/stores/{store_id}/shelves/{shelf_id}", summary="Delete shelf")
async def delete_shelf_endpoint(store_id: str, shelf_id: str):
    try:
        return await delete_shelf(store_id, shelf_id)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


# ── Bin inventory ─────────────────────────────────────────────────────────────

@router.get("/stores/{store_id}/shelves/{shelf_id}/bins/{bin_index}/inventory", summary="Get bin inventory")
async def get_bin_inventory_endpoint(store_id: str, shelf_id: str, bin_index: int):
    try:
        return await get_bin_inventory(store_id, shelf_id, bin_index)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.put("/stores/{store_id}/shelves/{shelf_id}/bins/{bin_index}/inventory", summary="Update bin inventory")
async def update_bin_inventory_endpoint(store_id: str, shelf_id: str, bin_index: int, body: InventoryUpdate):
    try:
        return await update_bin_inventory(store_id, shelf_id, bin_index, body)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


# ── Cameras ───────────────────────────────────────────────────────────────────

@router.get("/stores/{store_id}/cameras", summary="List cameras")
async def list_cameras_endpoint(store_id: str):
    try:
        return await list_cameras(store_id)
    except AiFiError as exc:
        raise _http(exc)


@router.get("/stores/{store_id}/cameras/{camera_id}", summary="Get camera")
async def get_camera_endpoint(store_id: str, camera_id: str):
    try:
        return await get_camera(store_id, camera_id)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


# ── Zones & shoppers ──────────────────────────────────────────────────────────

@router.get("/stores/{store_id}/zones", summary="List zones")
async def get_zones_endpoint(store_id: str):
    try:
        return await get_zones(store_id)
    except AiFiError as exc:
        raise _http(exc)


@router.get("/stores/{store_id}/zones/{zone_id}/shoppers", summary="Get shoppers in zone")
async def get_zone_shoppers_endpoint(store_id: str, zone_id: str):
    try:
        return await get_zone_shoppers(store_id, zone_id)
    except AiFiError as exc:
        raise _http(exc)


@router.get("/stores/{store_id}/shoppers/identity-matching", summary="Get identity matching status")
async def get_identity_matching_endpoint(store_id: str):
    try:
        return await get_identity_matching(store_id)
    except AiFiError as exc:
        raise _http(exc)


@router.patch("/stores/{store_id}/shoppers/{shopper_id}", summary="Update shopper")
async def update_shopper_endpoint(store_id: str, shopper_id: str, body: ShopperUpdate):
    try:
        return await update_shopper(store_id, shopper_id, body)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.post("/stores/{store_id}/shoppers/{shopper_id}", summary="Create shopper event")
async def create_shopper_event_endpoint(store_id: str, shopper_id: str, body: ShopperEvent):
    try:
        return await create_shopper_event(store_id, shopper_id, body)
    except AiFiError as exc:
        raise _http(exc)


# ── Analytics ─────────────────────────────────────────────────────────────────

@router.get("/stores/{store_id}/visitors-count", summary="Get visitor count")
async def get_visitor_count_endpoint(store_id: str):
    try:
        return await get_visitor_count(store_id)
    except AiFiError as exc:
        raise _http(exc)


@router.get("/stores/{store_id}/customers/count", summary="Get customer count")
async def get_customer_count_endpoint(store_id: str):
    try:
        return await get_customer_count(store_id)
    except AiFiError as exc:
        raise _http(exc)


@router.get("/analytics/stores/{store_id}/visitors/all", summary="All visitors analytics")
async def get_all_visitors_endpoint(
    store_id: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    try:
        return await get_all_visitors(store_id, start_date, end_date)
    except AiFiError as exc:
        raise _http(exc)


@router.get("/analytics/stores/{store_id}/visitors/all/by-day", summary="Visitors by day")
async def get_visitors_by_day_endpoint(
    store_id: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    try:
        return await get_visitors_by_day(store_id, start_date, end_date)
    except AiFiError as exc:
        raise _http(exc)


@router.get("/analytics/stores/{store_id}/visitors/new", summary="New visitors analytics")
async def get_new_visitors_endpoint(
    store_id: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    try:
        return await get_new_visitors(store_id, start_date, end_date)
    except AiFiError as exc:
        raise _http(exc)


@router.get("/analytics/stores/{store_id}/visitors/unique", summary="Unique visitors analytics")
async def get_unique_visitors_endpoint(
    store_id: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    try:
        return await get_unique_visitors(store_id, start_date, end_date)
    except AiFiError as exc:
        raise _http(exc)


@router.get("/analytics/products/sell-through", summary="Product sell-through analytics")
async def get_sell_through_endpoint(
    store_id: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    try:
        return await get_product_sell_through(store_id, start_date, end_date)
    except AiFiError as exc:
        raise _http(exc)


# ── Devices & IDAP ────────────────────────────────────────────────────────────

@router.post("/stores/{store_id}/thirdPartyDevices/{device_id}/events", status_code=201, summary="Create device event")
async def create_device_event_endpoint(store_id: str, device_id: str, body: DeviceEventCreate):
    try:
        return await create_device_event(store_id, device_id, body)
    except AiFiError as exc:
        raise _http(exc)


@router.delete("/stores/{store_id}/thirdPartyDevices/{device_id}/events/{event_id}", summary="Delete device event")
async def delete_device_event_endpoint(store_id: str, device_id: str, event_id: str):
    try:
        return await delete_device_event(store_id, device_id, event_id)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.post("/stores/{store_id}/idapDevices/{idap_device_id}/frame-annotation-event", status_code=201, summary="Create frame annotation event")
async def create_frame_annotation_endpoint(store_id: str, idap_device_id: str, body: FrameAnnotationEvent):
    try:
        return await create_frame_annotation(store_id, idap_device_id, body)
    except AiFiError as exc:
        raise _http(exc)


# ── Check-in / entry ──────────────────────────────────────────────────────────

@router.post("/stores/{store_id}/check-in/{check_in_device_id}/entry-codes/verify", summary="Verify check-in code")
async def verify_check_in_code_endpoint(store_id: str, check_in_device_id: str, body: EntryCodeVerifyAdmin):
    try:
        return await verify_check_in_code(store_id, check_in_device_id, body)
    except AiFiError as exc:
        raise _http(exc)


@router.post("/stores/{store_id}/entry/{entry_id}/entry-codes/verify", summary="Verify entry code")
async def verify_entry_code_endpoint(store_id: str, entry_id: str, body: EntryCodeVerifyAdmin):
    try:
        return await verify_entry_code(store_id, entry_id, body.code)
    except AiFiError as exc:
        raise _http(exc)


@router.post("/stores/{store_id}/check-in/{check_in_device_id}/remote-register", status_code=201, summary="Remote register at check-in")
async def remote_register_at_check_in_endpoint(store_id: str, check_in_device_id: str, body: dict):
    try:
        return await remote_register_at_check_in(store_id, check_in_device_id, body)
    except AiFiError as exc:
        raise _http(exc)


# ── RFID Tags ─────────────────────────────────────────────────────────────────

@router.get("/stores/{store_id}/tags", summary="List RFID tags")
async def list_tags_endpoint(store_id: str):
    try:
        return await list_tags(store_id)
    except AiFiError as exc:
        raise _http(exc)


@router.post("/stores/{store_id}/tags", status_code=201, summary="Create RFID tag")
async def create_tag_endpoint(store_id: str, body: TagCreate):
    try:
        return await create_tag(store_id, body)
    except AiFiError as exc:
        raise _http(exc)


@router.get("/stores/{store_id}/tags/{tag_id}", summary="Get RFID tag")
async def get_tag_endpoint(store_id: str, tag_id: str):
    try:
        return await get_tag(store_id, tag_id)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


# ═════════════════════════════════════════════════════════════════════════════
# ORDERS
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/orders", summary="List orders")
async def list_orders_endpoint(
    count: int = Query(50, ge=1, le=200),
    sort: Optional[str] = Query(None),
    direction: str = Query("asc", pattern="^(asc|desc)$"),
):
    try:
        return await list_orders(count=count, sort=sort, direction=direction)
    except AiFiError as exc:
        raise _http(exc)


@router.post("/orders", status_code=201, summary="Create order")
async def create_order_endpoint(body: OrderCreate):
    try:
        return await create_order(body)
    except AiFiError as exc:
        raise _http(exc)


@router.get("/orders/{order_id}", summary="Get order")
async def get_order_endpoint(order_id: int):
    try:
        return await get_order(order_id)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.patch("/orders/{order_id}", summary="Update order")
async def update_order_endpoint(order_id: int, body: OrderUpdate):
    try:
        return await update_order(order_id, body)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.post("/orders/{order_id}/retry", summary="Retry failed order")
async def retry_order_endpoint(order_id: int):
    try:
        return await retry_order(order_id)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


# ═════════════════════════════════════════════════════════════════════════════
# SESSIONS
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/sessions", summary="List sessions")
async def list_sessions_endpoint(count: int = Query(50, ge=1, le=200)):
    try:
        return await list_sessions(count=count)
    except AiFiError as exc:
        raise _http(exc)


@router.get("/sessions/{session_id}/cart", summary="Get session cart")
async def get_session_cart_endpoint(session_id: str):
    try:
        return await get_session_cart(session_id)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.post("/sessions/{session_id}/cart", summary="Update session cart")
async def update_session_cart_endpoint(session_id: str, body: CartUpdate):
    try:
        return await update_session_cart(session_id, body)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.patch("/sessions/{session_id}", summary="Update session")
async def update_session_endpoint(session_id: str, body: SessionUpdate):
    try:
        return await update_session(session_id, body)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.post("/sessions/{session_id}/checkout", status_code=201, summary="Checkout session")
async def create_session_checkout_endpoint(session_id: str, body: AdminCheckoutCreate):
    try:
        return await create_session_checkout(session_id, body)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


# ═════════════════════════════════════════════════════════════════════════════
# CONTESTS / AUDITS / CONFIG
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/contests", summary="List contests")
async def list_contests_endpoint():
    try:
        return await list_contests()
    except AiFiError as exc:
        raise _http(exc)


@router.post("/contests", status_code=201, summary="Create contest")
async def create_contest_endpoint(body: ContestCreate):
    try:
        return await create_contest(body)
    except AiFiError as exc:
        raise _http(exc)


@router.get("/audits", summary="List audits")
async def list_audits_endpoint():
    try:
        return await list_audits()
    except AiFiError as exc:
        raise _http(exc)


@router.get("/audits/{audit_id}", summary="Get audit")
async def get_audit_endpoint(audit_id: str):
    try:
        return await get_audit(audit_id)
    except AiFiNotFoundError as exc:
        raise _404(exc)
    except AiFiError as exc:
        raise _http(exc)


@router.get("/config", summary="Get AiFi config")
async def get_config_endpoint():
    try:
        return await get_config()
    except AiFiError as exc:
        raise _http(exc)


@router.get("/retailer/config", summary="Get retailer config")
async def get_retailer_config_endpoint():
    try:
        return await get_retailer_config()
    except AiFiError as exc:
        raise _http(exc)


@router.patch("/retailer/config", summary="Update retailer config")
async def update_retailer_config_endpoint(body: RetailerConfigUpdate):
    try:
        return await update_retailer_config(body)
    except AiFiError as exc:
        raise _http(exc)
