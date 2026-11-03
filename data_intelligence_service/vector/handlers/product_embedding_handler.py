"""
Handler: Product events → Vector embeddings.

When a product is created or updated, we generate an embedding
from its searchable text (display_name + description + SKU + category)
and store it in pgvector.

When deleted, we remove the embeddings.
"""
from sqlalchemy import text

from data_intelligence_service.vector.embeddings import embed_text
from data_intelligence_service.vector.pg_vector import upsert_product_embedding, delete_product_embeddings
from data_intelligence_service.core.db import _get_session
from data_intelligence_service.core.logger import logger


async def handle(event: dict):
    etype = event["event_type"]
    action = etype.split(".")[-1]
    payload = event["payload"]
    product_id = str(event["aggregate_id"])
    tenant_id = str(event["tenant_id"])

    if action in ("created", "updated"):
        await _embed_product(tenant_id, product_id, payload)
    elif action == "bulk_created":
        await _embed_bulk(tenant_id, payload)
    elif action == "deleted":
        delete_product_embeddings(product_id)
        logger.info(f"Vector: Embeddings removed for product {product_id}")


async def _embed_bulk(tenant_id: str, payload: dict):
    """Embed products imported in bulk.

    The bulk event only carries product IDs — fetch the searchable fields
    from Postgres and embed each product individually.
    """
    product_ids = payload.get("product_ids") or []
    if not product_ids:
        logger.warning(f"Vector: product.bulk_created with no product_ids (tenant {tenant_id})")
        return

    rows = []
    try:
        with _get_session() as session:
            rows = session.execute(
                text(
                    """
                    SELECT p.product_id, p.display_name, p.sales_description,
                           p.sku, p.category_id, p.restricted, c.name AS category_name
                    FROM products p
                    LEFT JOIN categories c ON c.category_id = p.category_id
                    WHERE p.tenant_id = :tid AND p.product_id = ANY(:ids)
                    """
                ),
                {"tid": tenant_id, "ids": product_ids},
            ).mappings().all()
    except Exception as exc:
        logger.error(f"Vector: bulk product fetch failed (tenant {tenant_id}): {exc}")
        return

    embedded = 0
    for row in rows:
        try:
            await _embed_product(tenant_id, str(row["product_id"]), dict(row))
            embedded += 1
        except Exception as exc:
            logger.warning(f"Vector: bulk embed failed for product {row['product_id']}: {exc}")
    logger.info(f"Vector: bulk_created embedded {embedded}/{len(product_ids)} products (tenant {tenant_id})")


async def _embed_product(tenant_id: str, product_id: str, payload: dict):
    """Build a searchable text chunk and embed it."""
    parts = []
    for field in ("display_name", "sales_description", "sku", "item_code", "category_name"):
        val = payload.get(field)
        if val:
            parts.append(str(val))

    chunk_text = " | ".join(parts) if parts else f"product {product_id}"

    embedding = embed_text(chunk_text)

    metadata = {
        "sku": payload.get("sku", ""),
        "item_code": payload.get("item_code", ""),
        "category_id": payload.get("category_id", ""),
        "restricted": payload.get("restricted", False),
    }

    upsert_product_embedding(
        tenant_id=tenant_id,
        product_id=product_id,
        chunk_text=chunk_text,
        embedding=embedding,
        chunk_index=0,
        metadata=metadata,
    )
    logger.info(f"Vector: Product {product_id} embedded ({len(chunk_text)} chars)")
