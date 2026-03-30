"""RFID Tag management — Admin API integration functions.

Covers /api/admin/v2/stores/{storeId}/tags/*.
"""
from __future__ import annotations

import logging
from typing import Any

from .http_client import admin_get, admin_post
from .schemas import TagCreate

logger = logging.getLogger("orders-service.aifi.tags")


async def create_tag(store_id: str, data: TagCreate) -> dict[str, Any]:
    """Create an RFID tag record in a store. POST /api/admin/v2/stores/{storeId}/tags"""
    logger.info("Creating RFID tag tagId=%s storeId=%s", data.tag_id, store_id)
    return await admin_post(
        f"/api/admin/v2/stores/{store_id}/tags",
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


async def list_tags(store_id: str) -> dict[str, Any]:
    """List all RFID tags for a store. GET /api/admin/v2/stores/{storeId}/tags"""
    return await admin_get(f"/api/admin/v2/stores/{store_id}/tags")


async def get_tag(store_id: str, tag_id: str) -> dict[str, Any]:
    """Fetch a single RFID tag by ID. GET /api/admin/v2/stores/{storeId}/tags/{id}"""
    return await admin_get(f"/api/admin/v2/stores/{store_id}/tags/{tag_id}")
