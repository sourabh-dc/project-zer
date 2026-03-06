"""
Intelligence Service — LLM client.

Wraps Azure OpenAI chat completions with structured output parsing.
Used by agents to convert natural language into queries.
"""
import json
from typing import Optional, Dict, Any, List

from intelligence_service.core.config import SETTINGS
from intelligence_service.core.logger import logger

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


def chat(
    messages: List[Dict[str, str]],
    deployment: Optional[str] = None,
    max_completion_tokens: int = 2048,
) -> str:
    """Send a chat completion request and return the assistant message."""
    client = _get_client()
    response = client.chat.completions.create(
        model=deployment or SETTINGS.AZURE_OPENAI_LLM_DEPLOYMENT,
        messages=messages,
        max_completion_tokens=max_completion_tokens,
    )
    return response.choices[0].message.content or ""


def chat_json(
    messages: List[Dict[str, str]],
    deployment: Optional[str] = None,
) -> Dict[str, Any]:
    """Chat completion that returns parsed JSON."""
    client = _get_client()
    response = client.chat.completions.create(
        model=deployment or SETTINGS.AZURE_OPENAI_LLM_DEPLOYMENT,
        messages=messages,
        max_completion_tokens=2048,
        response_format={"type": "json_object"},
    )
    text = response.choices[0].message.content or "{}"
    logger.info(f"LLM raw JSON response: {text[:500]}")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.error(f"LLM returned invalid JSON: {text[:200]}")
        return {"error": "Invalid JSON from LLM", "raw": text}
