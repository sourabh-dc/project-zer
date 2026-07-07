# vector/

pgvector layer — semantic product search using text embeddings.

---

## Why vector search?

Exact SQL queries fail for fuzzy/descriptive questions:
- "Find gloves for cold storage" — no product is literally named "cold storage gloves"
- "Eco-friendly cleaning products" — "eco-friendly" may not appear in product names
- "Something to protect my hands" — intent-based, not keyword-based

Vector search converts both the question and the product descriptions into mathematical
vectors (embeddings) and finds products whose meaning is closest to the question.

---

## How it works

1. **At index time** (on `product.created` outbox event):  
   `handlers/product_embedding_handler.py` calls `embeddings.embed_text(product_description)` and stores the 1536-dimensional vector in the `product_embeddings` table (pgvector column).

2. **At query time** (from the intelligence agent):  
   The agent calls `pg_vector.similarity_search(tenant_id, query_embedding, approved_product_ids)`.  
   pgvector performs approximate nearest-neighbour search using cosine similarity.  
   Results below `SETTINGS.VECTOR_SIMILARITY_THRESHOLD` (default 0.30) are filtered out.

---

## Files

### `embeddings.py`
Wraps the Azure OpenAI embedding API.  
`embed_text(text)` → `List[float]` (1536 dimensions for text-embedding-3-small).

### `pg_vector.py`
`similarity_search(tenant_id, query_embedding, approved_product_ids, top_k)` →  
List of `{product_id, name, similarity, ...}` dicts.

The `approved_product_ids` filter is applied at SQL level — users only see products  
their org unit is approved to purchase.

### `handlers/product_embedding_handler.py`
Triggered by `product.created` outbox events.  
Embeds the product description and upserts into `product_embeddings`.

---

## Governance

Product results are always filtered by `approved_product_ids` from the graph  
(`graph/queries/approved_universe.py`). A user can never see products outside  
their approved range, even via semantic search.
