"""Shared async HTTP client for all AiFi API tiers.

Provides:
- Per-tier helper functions (admin_*, store_*, customer_*)
- Automatic Bearer-token injection
- Retry with exponential back-off on transient errors (5xx, timeout, network)
- Structured logging for every request / response
- Consistent exception mapping to AiFiError subclasses
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from .config import AIFI_SETTINGS
from .exceptions import (
    AiFiAuthError,
    AiFiConnectionError,
    AiFiError,
    AiFiNotFoundError,
    AiFiServerError,
    AiFiTimeoutError,
    AiFiValidationError,
)

logger = logging.getLogger("orders-service.aifi")

# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _url(path: str) -> str:
    return f"{AIFI_SETTINGS.AIFI_BASE_URL.rstrip('/')}{path}"


def _raise_for_status(response: httpx.Response) -> None:
    """Map AiFi HTTP status codes to typed exceptions."""
    if response.status_code < 400:
        return
    try:
        detail = response.json()
    except Exception:
        detail = {"raw": response.text[:500]}

    code = response.status_code
    if code in (401, 403):
        raise AiFiAuthError(f"AiFi auth error ({code})", code, detail)
    if code == 404:
        raise AiFiNotFoundError("AiFi resource not found", code, detail)
    if code == 422:
        raise AiFiValidationError("AiFi validation error", code, detail)
    if code >= 500:
        raise AiFiServerError(f"AiFi server error ({code})", code, detail)
    raise AiFiError(f"AiFi HTTP {code}", code, detail)


async def _request(
    method: str,
    path: str,
    token: str,
    *,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute one HTTP request against AiFi with retry logic."""
    url = _url(path)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    last_exc: Exception | None = None

    for attempt in range(AIFI_SETTINGS.AIFI_MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=AIFI_SETTINGS.AIFI_TIMEOUT_SECONDS) as client:
                logger.debug("AiFi → %s %s (attempt %d)", method, url, attempt + 1)
                response = await client.request(
                    method, url, headers=headers, params=params, json=json
                )
                logger.debug("AiFi ← %s %s %d", method, url, response.status_code)
                _raise_for_status(response)
                return response.json() if response.content else {}

        except (AiFiServerError, AiFiTimeoutError) as exc:
            last_exc = exc
        except httpx.TimeoutException as exc:
            last_exc = AiFiTimeoutError(f"AiFi request timed out: {exc}")
        except httpx.NetworkError as exc:
            last_exc = AiFiConnectionError(f"AiFi network error: {exc}")
        except AiFiError:
            raise  # Auth / 404 / 422 are non-retryable

        if attempt < AIFI_SETTINGS.AIFI_MAX_RETRIES - 1:
            backoff = AIFI_SETTINGS.AIFI_RETRY_BACKOFF * (2**attempt)
            logger.warning(
                "AiFi %s %s failed (attempt %d/%d), retrying in %.1fs: %s",
                method, url, attempt + 1, AIFI_SETTINGS.AIFI_MAX_RETRIES, backoff, last_exc,
            )
            await asyncio.sleep(backoff)

    logger.error("AiFi %s %s exhausted %d retries", method, url, AIFI_SETTINGS.AIFI_MAX_RETRIES)
    raise last_exc or AiFiError("AiFi request failed after all retries")


# ─────────────────────────────────────────────────────────────────────────────
# Admin API helpers (fixed token from config)
# ─────────────────────────────────────────────────────────────────────────────

async def admin_get(path: str, params: dict | None = None) -> dict:
    return await _request("GET", path, AIFI_SETTINGS.AIFI_ADMIN_TOKEN, params=params)


async def admin_post(path: str, json: dict | None = None) -> dict:
    return await _request("POST", path, AIFI_SETTINGS.AIFI_ADMIN_TOKEN, json=json)


async def admin_patch(path: str, json: dict | None = None) -> dict:
    return await _request("PATCH", path, AIFI_SETTINGS.AIFI_ADMIN_TOKEN, json=json)


async def admin_put(path: str, json: dict | None = None) -> dict:
    return await _request("PUT", path, AIFI_SETTINGS.AIFI_ADMIN_TOKEN, json=json)


async def admin_delete(path: str) -> dict:
    return await _request("DELETE", path, AIFI_SETTINGS.AIFI_ADMIN_TOKEN)


# ─────────────────────────────────────────────────────────────────────────────
# Store API helpers (on-premise store token from config)
# ─────────────────────────────────────────────────────────────────────────────

async def store_get(path: str, params: dict | None = None) -> dict:
    return await _request("GET", path, AIFI_SETTINGS.AIFI_STORE_TOKEN, params=params)


async def store_post(path: str, json: dict | None = None) -> dict:
    return await _request("POST", path, AIFI_SETTINGS.AIFI_STORE_TOKEN, json=json)


async def store_put(path: str, json: dict | None = None) -> dict:
    return await _request("PUT", path, AIFI_SETTINGS.AIFI_STORE_TOKEN, json=json)


# ─────────────────────────────────────────────────────────────────────────────
# Customer API helpers (per-request token supplied by the caller)
# ─────────────────────────────────────────────────────────────────────────────

async def customer_get(path: str, token: str, params: dict | None = None) -> dict:
    return await _request("GET", path, token, params=params)


async def customer_post(path: str, token: str, json: dict | None = None) -> dict:
    return await _request("POST", path, token, json=json)


async def customer_patch(path: str, token: str, json: dict | None = None) -> dict:
    return await _request("PATCH", path, token, json=json)


async def customer_delete(path: str, token: str) -> dict:
    return await _request("DELETE", path, token)
