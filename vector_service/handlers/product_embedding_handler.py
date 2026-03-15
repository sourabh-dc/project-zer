"""
Handler: Product events → Vector embeddings.

When a product is created or updated, we generate an embedding
from its searchable text (display_name + description + SKU + category)
and store it in pgvector.

When deleted, we remove the embeddings.
"""
from vector_service.core.embeddings import embed_text
from vector_service.core.pg_vector import upsert_product_embedding, delete_product_embeddings
from vector_service.core.logger import logger


async def handle(event: dict):
    etype = event["event_type"]
    action = etype.split(".")[-1]
    payload = event["payload"]
    product_id = str(event["aggregate_id"])
    tenant_id = str(event["tenant_id"])

    if action in ("created", "updated"):
        await _embed_product(tenant_id, product_id, payload)
    elif action == "deleted":
        delete_product_embeddings(product_id)
        logger.info(f"Vector: Embeddings removed for product {product_id}")


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
