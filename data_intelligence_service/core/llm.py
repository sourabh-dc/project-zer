"""
Intelligence Service — LLM client.

Wraps Azure OpenAI chat completions with structured output parsing,
automatic retries with exponential backoff, and per-call latency logging.
"""
import json
import time
from typing import Optional, Dict, Any, List, Tuple

from data_intelligence_service.core.config import SETTINGS
from data_intelligence_service.core.logger import logger

_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import AzureOpenAI
        _client = AzureOpenAI(
            api_key=SETTINGS.AZURE_OPENAI_API_KEY,
            azure_endpoint=SETTINGS.AZURE_OPENAI_ENDPOINT,
            api_version=SETTINGS.AZURE_OPENAI_API_VERSION,
        )
    return _client


def _with_retry(fn, label: str) -> Tuple[Any, float]:
    """Run fn() with exponential backoff retries. Returns (result, elapsed_ms)."""
    max_retries = SETTINGS.LLM_MAX_RETRIES
    base_delay = SETTINGS.LLM_RETRY_DELAY_SECONDS
    last_exc = None
    t0 = time.monotonic()

    for attempt in range(max_retries):
        try:
            result = fn()
            elapsed = (time.monotonic() - t0) * 1000
            if attempt > 0:
                logger.info(f"[LLM] {label} succeeded on attempt {attempt + 1} ({elapsed:.0f}ms)")
            return result, elapsed
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"[LLM] {label} attempt {attempt + 1} failed: {exc} — retrying in {delay:.1f}s")
                time.sleep(delay)
            else:
                logger.error(f"[LLM] {label} failed after {max_retries} attempts: {exc}")

    raise last_exc


def chat(
    messages: List[Dict[str, str]],
    deployment: Optional[str] = None,
    max_completion_tokens: int = 2048,
) -> Tuple[str, float]:
    """Send a chat completion and return (content, latency_ms)."""
    client = _get_client()

    def _call():
        response = client.chat.completions.create(
            model=deployment or SETTINGS.AZURE_OPENAI_LLM_DEPLOYMENT,
            messages=messages,
            max_completion_tokens=max_completion_tokens,
        )
        return response.choices[0].message.content or ""

    return _with_retry(_call, "chat")


def chat_json(
    messages: List[Dict[str, str]],
    deployment: Optional[str] = None,
) -> Tuple[Dict[str, Any], float]:
    """Chat completion that returns (parsed_json, latency_ms)."""
    client = _get_client()

    def _call():
        response = client.chat.completions.create(
            model=deployment or SETTINGS.AZURE_OPENAI_LLM_DEPLOYMENT,
            messages=messages,
            max_completion_tokens=2048,
            response_format={"type": "json_object"},
        )
        text = response.choices[0].message.content or "{}"
        logger.debug(f"[LLM] raw JSON response: {text[:300]}")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.error(f"[LLM] invalid JSON from model: {text[:200]}")
            return {"error": "Invalid JSON from LLM", "raw": text}

    return _with_retry(_call, "chat_json")
