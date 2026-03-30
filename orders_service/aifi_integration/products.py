"""Product management — Admin API integration functions.

Covers all of /api/admin/v2/products/* including variants, barcodes, categories,
tax rates, planograms, and snapshots.
"""
from __future__ import annotations

import logging
from typing import Any

from .http_client import admin_delete, admin_get, admin_patch, admin_post, admin_put
from .schemas import (
    BarcodeAdd,
    ProductCreate,
    ProductUpdate,
    ProductUpsert,
    ProductVariantCreate,
    ProductVariantUpdate,
)

logger = logging.getLogger("orders-service.aifi.products")


# ─────────────────────────────────────────────────────────────────────────────
# Products — CRUD
# ─────────────────────────────────────────────────────────────────────────────

async def list_products(
    name: str | None = None,
    category: str | None = None,
    sku: str | None = None,
    barcode: str | None = None,
    external_id: str | None = None,
    location: str | None = None,
    count: int = 50,
    sort: str | None = None,
    direction: str = "asc",
) -> dict[str, Any]:
    """List products with optional filters. GET /api/admin/v2/products"""
    params = {k: v for k, v in {
        "name": name,
        "category": category,
        "sku": sku,
        "barcode": barcode,
        "externalId": external_id,
        "location": location,
        "count": count,
        "sort": sort,
        "direction": direction,
    }.items() if v is not None}
    return await admin_get("/api/admin/v2/products", params=params)


async def get_product(product_id: int) -> dict[str, Any]:
    """Fetch a single product by ID. GET /api/admin/v2/products/{productId}"""
    return await admin_get(f"/api/admin/v2/products/{product_id}")


async def create_product(data: ProductCreate) -> dict[str, Any]:
    """Create a new product. POST /api/admin/v2/products"""
    logger.info("Creating AiFi product name=%s", data.name)
    return await admin_post(
        "/api/admin/v2/products",
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


async def update_product(product_id: int, data: ProductUpdate) -> dict[str, Any]:
    """Fully replace a product record. PUT /api/admin/v2/products/{productId}"""
    return await admin_put(
        f"/api/admin/v2/products/{product_id}",
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


async def upsert_product(data: ProductUpsert) -> dict[str, Any]:
    """Create or replace a product by externalId. PUT /api/admin/v2/products"""
    return await admin_put(
        "/api/admin/v2/products",
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


async def delete_product(product_id: int) -> dict[str, Any]:
    """Permanently delete a product. DELETE /api/admin/v2/products/{productId}"""
    logger.info("Deleting AiFi product id=%d", product_id)
    return await admin_delete(f"/api/admin/v2/products/{product_id}")


# ─────────────────────────────────────────────────────────────────────────────
# Products — Planogram / snapshots / tax rates
# ─────────────────────────────────────────────────────────────────────────────

async def get_product_planogram(product_id: int) -> dict[str, Any]:
    """GET /api/admin/v2/products/{productId}/planogram"""
    return await admin_get(f"/api/admin/v2/products/{product_id}/planogram")


async def get_product_snapshots() -> dict[str, Any]:
    """GET /api/admin/v2/products/snapshots"""
    return await admin_get("/api/admin/v2/products/snapshots")


async def get_tax_rates() -> dict[str, Any]:
    """GET /api/admin/v2/products/taxrates"""
    return await admin_get("/api/admin/v2/products/taxrates")


async def list_categories() -> dict[str, Any]:
    """GET /api/admin/v2/products/categories"""
    return await admin_get("/api/admin/v2/products/categories")


# ─────────────────────────────────────────────────────────────────────────────
# Variants
# ─────────────────────────────────────────────────────────────────────────────

async def list_variants(product_id: int | None = None) -> dict[str, Any]:
    """List variants globally or for a specific product.
    GET /api/admin/v2/products/variants  or  /api/admin/v2/products/{productId}/variants"""
    if product_id is not None:
        return await admin_get(f"/api/admin/v2/products/{product_id}/variants")
    return await admin_get("/api/admin/v2/products/variants")


async def get_variant(variant_id: int) -> dict[str, Any]:
    """GET /api/admin/v2/products/variants/{variantId}"""
    return await admin_get(f"/api/admin/v2/products/variants/{variant_id}")


async def get_default_variant(product_id: int) -> dict[str, Any]:
    """GET /api/admin/v2/products/{productId}/variants/default"""
    return await admin_get(f"/api/admin/v2/products/{product_id}/variants/default")


async def create_variant(product_id: int, data: ProductVariantCreate) -> dict[str, Any]:
    """POST /api/admin/v2/products/{productId}/variants"""
    return await admin_post(
        f"/api/admin/v2/products/{product_id}/variants",
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


async def update_variant(variant_id: int, data: ProductVariantUpdate) -> dict[str, Any]:
    """PATCH /api/admin/v2/products/variants/{variantId}"""
    return await admin_patch(
        f"/api/admin/v2/products/variants/{variant_id}",
        json=data.model_dump(by_alias=True, exclude_none=True),
    )


async def delete_variant(variant_id: int) -> dict[str, Any]:
    """DELETE /api/admin/v2/products/variants/{variantId}"""
    return await admin_delete(f"/api/admin/v2/products/variants/{variant_id}")


# ─────────────────────────────────────────────────────────────────────────────
# Barcodes
# ─────────────────────────────────────────────────────────────────────────────

async def add_barcode(variant_id: int, barcode: str) -> dict[str, Any]:
    """Attach a barcode to a variant. POST /api/admin/v2/products/variants/{variantId}/barcodes"""
    return await admin_post(
        f"/api/admin/v2/products/variants/{variant_id}/barcodes",
        json={"barcode": barcode},
    )


async def delete_barcode(variant_id: int, barcode: str) -> dict[str, Any]:
    """Remove a barcode from a variant.
    DELETE /api/admin/v2/products/variants/{variantId}/barcodes/{barcode}"""
    return await admin_delete(f"/api/admin/v2/products/variants/{variant_id}/barcodes/{barcode}")
