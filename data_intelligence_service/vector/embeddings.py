"""
Vector Service — Embedding generation.

Uses Azure OpenAI text-embedding-3-small.
Falls back to a deterministic stub when credentials are not set
(useful for local dev/testing without billing).
"""
from typing import List
import hashlib

from data_intelligence_service.core.config import SETTINGS
from data_intelligence_service.core.logger import logger

_client = None


def _get_client():
    global _client
    if _client is None:
        api_key = SETTINGS.AZURE_OPENAI_API_KEY
        endpoint = SETTINGS.AZURE_OPENAI_ENDPOINT
        if not api_key or not endpoint:
            logger.warning("Azure OpenAI credentials not set — embeddings will be stubs")
            return None
        try:
            from openai import AzureOpenAI
            _client = AzureOpenAI(
                api_key=api_key,
                azure_endpoint=endpoint,
                api_version=SETTINGS.AZURE_OPENAI_API_VERSION,
            )
        except ImportError:
            logger.error("openai package not installed")
            return None
    return _client


def embed_text(text: str) -> List[float]:
    """Generate an embedding vector for a single text string."""
    client = _get_client()
    if client is None:
        return _stub_embedding(text)

    response = client.embeddings.create(
        input=[text],
        model=SETTINGS.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
    )
    return response.data[0].embedding


def embed_batch(texts: List[str]) -> List[List[float]]:
    """Generate embeddings for a batch of texts."""
    client = _get_client()
    if client is None:
        return [_stub_embedding(t) for t in texts]

    response = client.embeddings.create(
        input=texts,
        model=SETTINGS.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
    )
    return [item.embedding for item in response.data]


def _stub_embedding(text: str) -> List[float]:
    """Deterministic stub for dev/test — hash-based pseudo-vector."""
    h = hashlib.sha256(text.encode()).digest()
    dim = SETTINGS.EMBEDDING_DIMENSIONS
    vec = []
    for i in range(dim):
        byte_val = h[i % len(h)]
        vec.append((byte_val / 255.0) * 2 - 1)
    return vec
