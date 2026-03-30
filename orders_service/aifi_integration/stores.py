"""Store management — Admin API integration functions.

Covers stores, gondolas, shelves, bin inventory, cameras, zones, shoppers,
analytics, third-party devices, IDAP devices, and check-in endpoints.
"""
from __future__ import annotations

import logging
from typing import Any

from .http_client import admin_delete, admin_get, admin_patch, admin_post, admin_put
from .schemas import (
    DeviceEventCreate,
    EntryCodeVerifyAdmin,
    FrameAnnotationEvent,
    InventoryUpdate,
    ShelfCreate,
    ShelfUpdate,
    ShopperEvent,
    ShopperUpdate,
    StoreCreate,
    StoreUpdate,
)

logger = logging.getLogger("orders-service.aifi.stores")


# ─────────────────────────────────────────────────────────────────────────────
# Stores — CRUD
# ─────────────────────────────────────────────────────────────────────────────

async def list_stores() -> dict[str, Any]:
    """GET /api/admin/v2/stores"""
    return await admin_get("/api/admin/v2/stores")


async def create_store(data: StoreCreate) -> dict[str, Any]:
    """POST /api/admin/v2/stores"""
    logger.info("Creating AiFi store name=%s", data.name)
    return await admin_post("/api/admin/v2/stores", json=data.model_dump(by_alias=True, exclude_none=True))


async def get_store(store_id: str) -> dict[str, Any]:
    """GET /api/admin/v2/stores/{storeId}"""
    return await admin_get(f"/api/admin/v2/stores/{store_id}")


async def update_store(store_id: str, data: StoreUpdate) -> dict[str, Any]:
    """PATCH /api/admin/v2/stores/{storeId}"""
    return await admin_patch(
        f"/api/admin/v2/stores/{store_id}",
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


async def get_store_status(store_id: str) -> dict[str, Any]:
    """GET /api/admin/v2/stores/{storeId}/status"""
    return await admin_get(f"/api/admin/v2/stores/{store_id}/status")


async def get_store_health(store_id: str) -> dict[str, Any]:
    """GET /api/admin/v2/stores/{storeId}/health"""
    return await admin_get(f"/api/admin/v2/stores/{store_id}/health")


# ─────────────────────────────────────────────────────────────────────────────
# Planogram
# ─────────────────────────────────────────────────────────────────────────────

async def get_store_planogram(store_id: str) -> dict[str, Any]:
    """GET /api/admin/v2/stores/{storeId}/planogram"""
    return await admin_get(f"/api/admin/v2/stores/{store_id}/planogram")


async def get_gondola_planogram(store_id: str, gondola_id: str) -> dict[str, Any]:
    """GET /api/admin/v2/stores/{storeId}/planogram/{gondolaId}"""
    return await admin_get(f"/api/admin/v2/stores/{store_id}/planogram/{gondola_id}")


# ─────────────────────────────────────────────────────────────────────────────
# Gondolas
# ─────────────────────────────────────────────────────────────────────────────

async def list_gondolas(store_id: str) -> dict[str, Any]:
    """GET /api/admin/v2/stores/{storeId}/gondolas"""
    return await admin_get(f"/api/admin/v2/stores/{store_id}/gondolas")


async def get_gondola(store_id: str, gondola_id: str) -> dict[str, Any]:
    """GET /api/admin/v2/stores/{storeId}/gondolas/{gondolaId}"""
    return await admin_get(f"/api/admin/v2/stores/{store_id}/gondolas/{gondola_id}")


async def list_gondola_shelves(store_id: str, gondola_id: str) -> dict[str, Any]:
    """GET /api/admin/v2/stores/{storeId}/gondolas/{gondolaId}/shelves"""
    return await admin_get(f"/api/admin/v2/stores/{store_id}/gondolas/{gondola_id}/shelves")


# ─────────────────────────────────────────────────────────────────────────────
# Shelves
# ─────────────────────────────────────────────────────────────────────────────

async def create_shelf(store_id: str, data: ShelfCreate) -> dict[str, Any]:
    """POST /api/admin/v2/stores/{storeId}/shelves"""
    return await admin_post(
        f"/api/admin/v2/stores/{store_id}/shelves",
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


async def get_shelf(store_id: str, shelf_id: str) -> dict[str, Any]:
    """GET /api/admin/v2/stores/{storeId}/shelves/{shelfId}"""
    return await admin_get(f"/api/admin/v2/stores/{store_id}/shelves/{shelf_id}")


async def update_shelf(store_id: str, shelf_id: str, data: ShelfUpdate) -> dict[str, Any]:
    """PATCH /api/admin/v2/stores/{storeId}/shelves/{shelfId}"""
    return await admin_patch(
        f"/api/admin/v2/stores/{store_id}/shelves/{shelf_id}",
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


async def delete_shelf(store_id: str, shelf_id: str) -> dict[str, Any]:
    """DELETE /api/admin/v2/stores/{storeId}/shelves/{shelfId}"""
    return await admin_delete(f"/api/admin/v2/stores/{store_id}/shelves/{shelf_id}")


# ─────────────────────────────────────────────────────────────────────────────
# Bin inventory
# ─────────────────────────────────────────────────────────────────────────────

async def get_bin_inventory(store_id: str, shelf_id: str, bin_index: int) -> dict[str, Any]:
    """GET /api/admin/v2/stores/{storeId}/shelves/{shelfId}/bins/{binIndex}/inventory"""
    return await admin_get(
        f"/api/admin/v2/stores/{store_id}/shelves/{shelf_id}/bins/{bin_index}/inventory"
    )


async def update_bin_inventory(
    store_id: str, shelf_id: str, bin_index: int, data: InventoryUpdate
) -> dict[str, Any]:
    """PUT /api/admin/v2/stores/{storeId}/shelves/{shelfId}/bins/{binIndex}/inventory"""
    return await admin_put(
        f"/api/admin/v2/stores/{store_id}/shelves/{shelf_id}/bins/{bin_index}/inventory",
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Cameras
# ─────────────────────────────────────────────────────────────────────────────

async def list_cameras(store_id: str) -> dict[str, Any]:
    """GET /api/admin/v2/stores/{storeId}/cameras"""
    return await admin_get(f"/api/admin/v2/stores/{store_id}/cameras")


async def get_camera(store_id: str, camera_id: str) -> dict[str, Any]:
    """GET /api/admin/v2/stores/{storeId}/cameras/{cameraId}"""
    return await admin_get(f"/api/admin/v2/stores/{store_id}/cameras/{camera_id}")


# ─────────────────────────────────────────────────────────────────────────────
# Zones & Shoppers
# ─────────────────────────────────────────────────────────────────────────────

async def get_zones(store_id: str) -> dict[str, Any]:
    """GET /api/admin/v2/stores/{storeId}/zones"""
    return await admin_get(f"/api/admin/v2/stores/{store_id}/zones")


async def get_zone_shoppers(store_id: str, zone_id: str) -> dict[str, Any]:
    """GET /api/admin/v2/stores/{storeId}/zones/{zoneId}/shoppers"""
    return await admin_get(f"/api/admin/v2/stores/{store_id}/zones/{zone_id}/shoppers")


async def get_identity_matching(store_id: str) -> dict[str, Any]:
    """GET /api/admin/v2/stores/{storeId}/shoppers/identity-matching"""
    return await admin_get(f"/api/admin/v2/stores/{store_id}/shoppers/identity-matching")


async def update_shopper(store_id: str, shopper_id: str, data: ShopperUpdate) -> dict[str, Any]:
    """PATCH /api/admin/v2/stores/{storeId}/shoppers/{shopperId}"""
    return await admin_patch(
        f"/api/admin/v2/stores/{store_id}/shoppers/{shopper_id}",
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


async def create_shopper_event(store_id: str, shopper_id: str, data: ShopperEvent) -> dict[str, Any]:
    """POST /api/admin/v2/stores/{storeId}/shoppers/{shopperId}"""
    return await admin_post(
        f"/api/admin/v2/stores/{store_id}/shoppers/{shopper_id}",
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Analytics
# ─────────────────────────────────────────────────────────────────────────────

async def get_visitor_count(store_id: str) -> dict[str, Any]:
    """GET /api/admin/v2/stores/{storeId}/visitors-count"""
    return await admin_get(f"/api/admin/v2/stores/{store_id}/visitors-count")


async def get_customer_count(store_id: str) -> dict[str, Any]:
    """GET /api/admin/v2/stores/{storeId}/customers/count"""
    return await admin_get(f"/api/admin/v2/stores/{store_id}/customers/count")


async def get_all_visitors(
    store_id: str, start_date: str | None = None, end_date: str | None = None
) -> dict[str, Any]:
    """GET /api/admin/v2/analytics/stores/{storeId}/visitors/all"""
    params = {k: v for k, v in {"startDate": start_date, "endDate": end_date}.items() if v}
    return await admin_get(f"/api/admin/v2/analytics/stores/{store_id}/visitors/all", params=params)


async def get_visitors_by_day(
    store_id: str, start_date: str | None = None, end_date: str | None = None
) -> dict[str, Any]:
    """GET /api/admin/v2/analytics/stores/{storeId}/visitors/all/by-day"""
    params = {k: v for k, v in {"startDate": start_date, "endDate": end_date}.items() if v}
    return await admin_get(f"/api/admin/v2/analytics/stores/{store_id}/visitors/all/by-day", params=params)


async def get_new_visitors(
    store_id: str, start_date: str | None = None, end_date: str | None = None
) -> dict[str, Any]:
    """GET /api/admin/v2/analytics/stores/{storeId}/visitors/new"""
    params = {k: v for k, v in {"startDate": start_date, "endDate": end_date}.items() if v}
    return await admin_get(f"/api/admin/v2/analytics/stores/{store_id}/visitors/new", params=params)


async def get_unique_visitors(
    store_id: str, start_date: str | None = None, end_date: str | None = None
) -> dict[str, Any]:
    """GET /api/admin/v2/analytics/stores/{storeId}/visitors/unique"""
    params = {k: v for k, v in {"startDate": start_date, "endDate": end_date}.items() if v}
    return await admin_get(f"/api/admin/v2/analytics/stores/{store_id}/visitors/unique", params=params)


async def get_product_sell_through(
    store_id: str | None = None, start_date: str | None = None, end_date: str | None = None
) -> dict[str, Any]:
    """GET /api/admin/v2/analytics/products/sell-through"""
    params = {k: v for k, v in {
        "storeId": store_id, "startDate": start_date, "endDate": end_date
    }.items() if v}
    return await admin_get("/api/admin/v2/analytics/products/sell-through", params=params)


# ─────────────────────────────────────────────────────────────────────────────
# Third-party devices & IDAP
# ─────────────────────────────────────────────────────────────────────────────

async def create_device_event(store_id: str, device_id: str, data: DeviceEventCreate) -> dict[str, Any]:
    """POST /api/admin/v2/stores/{storeId}/thirdPartyDevices/{thirdPartyDeviceId}/events"""
    return await admin_post(
        f"/api/admin/v2/stores/{store_id}/thirdPartyDevices/{device_id}/events",
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


async def delete_device_event(store_id: str, device_id: str, event_id: str) -> dict[str, Any]:
    """DELETE /api/admin/v2/stores/{storeId}/thirdPartyDevices/{thirdPartyDeviceId}/events/{eventId}"""
    return await admin_delete(
        f"/api/admin/v2/stores/{store_id}/thirdPartyDevices/{device_id}/events/{event_id}"
    )


async def create_frame_annotation(
    store_id: str, idap_device_id: str, data: FrameAnnotationEvent
) -> dict[str, Any]:
    """POST /api/admin/v2/stores/{storeId}/idapDevices/{idapDeviceId}/frame-annotation-event"""
    return await admin_post(
        f"/api/admin/v2/stores/{store_id}/idapDevices/{idap_device_id}/frame-annotation-event",
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Check-in / entry verification
# ─────────────────────────────────────────────────────────────────────────────

async def verify_check_in_code(
    store_id: str, check_in_device_id: str, data: EntryCodeVerifyAdmin
) -> dict[str, Any]:
    """POST /api/admin/v2/stores/{storeId}/check-in/{checkInDeviceId}/entry-codes/verify"""
    return await admin_post(
        f"/api/admin/v2/stores/{store_id}/check-in/{check_in_device_id}/entry-codes/verify",
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


async def verify_entry_code(store_id: str, entry_id: str, code: str) -> dict[str, Any]:
    """POST /api/admin/v2/stores/{storeId}/entry/{entryId}/entry-codes/verify"""
    return await admin_post(
        f"/api/admin/v2/stores/{store_id}/entry/{entry_id}/entry-codes/verify",
        json={"code": code},
    )


async def remote_register_at_check_in(
    store_id: str, check_in_device_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """POST /api/admin/v2/stores/{storeId}/check-in/{checkInDeviceId}/remote-register"""
    return await admin_post(
        f"/api/admin/v2/stores/{store_id}/check-in/{check_in_device_id}/remote-register",
        json=payload,
    )
