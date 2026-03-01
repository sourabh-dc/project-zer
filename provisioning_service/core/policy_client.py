"""
Policy Engine HTTP Client — used by provisioning_service to call the
standalone policy engine's /evaluate endpoint over HTTP.

Includes:
  - PolicyClient: async httpx client (singleton) with circuit breaker
  - require_policy(): FastAPI dependency factory usable with Depends()

Circuit breaker states:
  CLOSED  → normal operation, requests go through
  OPEN    → policy engine is down, fail-closed (deny all) per governance-first principle
  HALF_OPEN → after cooldown, allow one probe request to test recovery
"""
import time
from enum import Enum
from typing import Any, Dict, Optional

import httpx
from fastapi import HTTPException, Request, Security
from starlette import status

from provisioning_service.core.config import SETTINGS
from provisioning_service.core.user_auth import decode_jwt_with_settings
from provisioning_service.utils.logger import logger

POLICY_ENGINE_URL = getattr(SETTINGS, "POLICY_ENGINE_URL", "http://localhost:8004")
POLICY_EVALUATE_TIMEOUT = float(getattr(SETTINGS, "POLICY_EVALUATE_TIMEOUT", 5.0))

CIRCUIT_FAILURE_THRESHOLD = 5
CIRCUIT_COOLDOWN_SECONDS = 30


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class PolicyClient:
    """Async HTTP client with circuit breaker for the Policy Engine."""

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0
        self._consecutive_successes = 0

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=POLICY_ENGINE_URL,
                timeout=POLICY_EVALUATE_TIMEOUT,
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _record_success(self):
        self._failure_count = 0
        self._consecutive_successes += 1
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.CLOSED
            logger.info("Circuit breaker CLOSED — policy engine recovered")

    def _record_failure(self):
        self._failure_count += 1
        self._consecutive_successes = 0
        self._last_failure_time = time.monotonic()
        if self._failure_count >= CIRCUIT_FAILURE_THRESHOLD and self._state == CircuitState.CLOSED:
            self._state = CircuitState.OPEN
            logger.error(f"Circuit breaker OPEN — policy engine failed {self._failure_count} consecutive times")

    def _should_attempt(self) -> bool:
        if self._state == CircuitState.CLOSED:
            return True
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= CIRCUIT_COOLDOWN_SECONDS:
                self._state = CircuitState.HALF_OPEN
                logger.info("Circuit breaker HALF_OPEN — probing policy engine")
                return True
            return False
        return True  # HALF_OPEN

    async def evaluate(
        self,
        action: str,
        subject: Dict[str, Any],
        resource: Dict[str, Any],
        tenant_id: str,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Call POST /evaluate with circuit breaker protection.

        When the circuit is OPEN (policy engine down), returns a deny decision
        per the governance-first / fail-closed principle from the engineering doc.
        """
        if not self._should_attempt():
            logger.warning(f"Circuit OPEN — denying action={action} (fail-closed)")
            return {
                "decision": "deny",
                "allowed": False,
                "reason": "Policy engine temporarily unavailable — action denied (fail-closed)",
                "matched_policies": [],
                "evaluation_ms": 0,
                "correlation_id": correlation_id,
                "circuit_breaker": True,
            }

        payload = {
            "action": action,
            "subject": subject,
            "resource": resource,
            "tenant_id": tenant_id,
            "correlation_id": correlation_id,
        }

        try:
            start = time.perf_counter()
            resp = await self.client.post("/evaluate", json=payload)
            elapsed_ms = int((time.perf_counter() - start) * 1000)

            if resp.status_code != 200:
                logger.error(f"Policy engine returned {resp.status_code}: {resp.text}")
                self._record_failure()
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Policy engine error: {resp.status_code}",
                )

            result = resp.json()
            self._record_success()
            logger.debug(f"Policy evaluate [{action}] → {result.get('decision')} ({elapsed_ms}ms)")
            return result

        except httpx.TimeoutException:
            logger.error(f"Policy engine timeout for action={action}")
            self._record_failure()
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Policy engine timed out",
            )
        except HTTPException:
            raise
        except Exception as exc:
            logger.error(f"Policy engine call failed: {exc}", exc_info=True)
            self._record_failure()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Policy engine unreachable: {str(exc)}",
            )


policy_client = PolicyClient()


def require_policy(
    action: str,
    *,
    resource_from: str = "body",
    resource_fields: Optional[list] = None,
):
    """Dependency factory for Gate 2 (Policy Engine).

    Usage:
        policy = Depends(require_policy("order.create"))
        policy = Depends(require_policy("order.create", resource_fields=["order_total", "quantity"]))
    """

    async def dependency(
        request: Request,
        claims: Dict[str, Any] = Security(decode_jwt_with_settings),
    ) -> Dict[str, Any]:
        subject = {
            "user_id": claims.get("sub"),
            "tenant_id": claims.get("tenant_id"),
            "roles": claims.get("roles", []),
            "permissions": claims.get("permissions", []),
            "email": claims.get("email"),
        }

        tenant_id = claims.get("tenant_id", "")

        resource: Dict[str, Any] = {}
        if resource_from == "body":
            try:
                body = await request.json()
                if isinstance(body, dict):
                    if resource_fields:
                        resource = {k: body.get(k) for k in resource_fields if k in body}
                    else:
                        resource = body
            except Exception:
                pass

        if "tenant_id" not in resource and tenant_id:
            resource["tenant_id"] = tenant_id

        result = await policy_client.evaluate(
            action=action,
            subject=subject,
            resource=resource,
            tenant_id=tenant_id,
            correlation_id=request.headers.get("x-correlation-id"),
        )

        decision = result.get("decision", "deny")

        if decision == "deny":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "policy_decision": "deny",
                    "reason": result.get("reason", "Denied by policy"),
                    "matched_policies": result.get("matched_policies", []),
                },
            )

        if decision == "require_approval":
            raise HTTPException(
                status_code=202,
                detail={
                    "policy_decision": "require_approval",
                    "reason": result.get("reason", "Approval required"),
                    "matched_policies": result.get("matched_policies", []),
                    "approval_required": True,
                },
            )

        return result

    return dependency
