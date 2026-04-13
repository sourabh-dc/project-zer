"""
shared/opa_client/client.py
----------------------------
Centralised OPA (Open Policy Agent) HTTP client.

Any microservice imports this module to enforce Rego policies on mutating
endpoints without any user interaction.  OPA runs as a sidecar (localhost:8181)
loaded with the shared bundle from ``shared/opa_policies/``.

Usage in a FastAPI service:
    from shared.opa_client import require_opa_policy

    @router.post("/sites")
    async def create_site(
        req: SiteCreate,
        ctx  = Depends(check_user_authorization("sites.manage")),   # Gate 1 RBAC
        gate = Depends(require_opa_policy("site.create")),          # Gate 2 OPA
    ):
        ...

The OPA client enriches the input document by calling the policy_service
/evaluate endpoint for subject context (budget, roles, subscription, etc.)
and then sends it to OPA for a deterministic Rego decision.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import HTTPException, Request, Security
from starlette import status

logger = logging.getLogger("opa_client")

# ---------------------------------------------------------------------------
# Defaults (overridden per-service via environment or settings)
# ---------------------------------------------------------------------------
_DEFAULT_OPA_URL = "http://localhost:8181"
_DEFAULT_TIMEOUT = 3.0  # seconds


class OPAClient:
    """HTTP client for an OPA sidecar running alongside the service."""

    def __init__(
        self,
        opa_url: str = _DEFAULT_OPA_URL,
        timeout: float = _DEFAULT_TIMEOUT,
        policy_service_url: Optional[str] = None,
    ):
        self.opa_url = opa_url.rstrip("/")
        self.timeout = timeout
        self.policy_service_url = policy_service_url  # optional enrichment
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Subject enrichment (optional — calls policy_service for context)
    # ------------------------------------------------------------------
    async def _enrich_subject(
        self, user_id: str, tenant_id: str
    ) -> Dict[str, Any]:
        """Fetch enriched user context from policy_service."""
        if not self.policy_service_url:
            return {}
        try:
            resp = await self.client.get(
                f"{self.policy_service_url}/policies",
                params={"tenant_id": tenant_id},
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as exc:
            logger.warning(f"Subject enrichment failed: {exc}")
        return {}

    # ------------------------------------------------------------------
    # Core evaluation
    # ------------------------------------------------------------------
    async def evaluate(
        self,
        package_path: str,
        subject: Dict[str, Any],
        resource: Dict[str, Any],
        action: str,
        *,
        enrich: bool = True,
    ) -> Dict[str, Any]:
        """Evaluate a Rego policy and return the decision document.

        Args:
            package_path: Rego package path, e.g. "zeroque/provisioning".
                          Translates to POST /v1/data/zeroque/provisioning
            subject:      Caller identity (user_id, tenant_id, roles, etc.).
            resource:     Resource context (the request body / entity data).
            action:       Action code, e.g. "site.create".
            enrich:       If True and policy_service_url is set, fetch extra
                          context (budget, subscription, approved products).

        Returns:
            OPA result document containing ``allow``, ``decision``, ``reason``.

        Raises:
            HTTPException 403 on deny, 502 on OPA error.
        """
        opa_input: Dict[str, Any] = {
            "subject": subject,
            "resource": resource,
            "action": action,
            "current_time": datetime.now(timezone.utc).isoformat(),
        }

        # Optional enrichment from policy service
        if enrich and self.policy_service_url:
            extra = await self._enrich_subject(
                subject.get("user_id", ""),
                subject.get("tenant_id", ""),
            )
            if extra:
                for k, v in extra.items():
                    if k not in opa_input["subject"]:
                        opa_input["subject"][k] = v

        url = f"{self.opa_url}/v1/data/{package_path}"
        payload = {"input": opa_input}

        try:
            start = time.perf_counter()
            resp = await self.client.post(url, json=payload)
            elapsed_ms = int((time.perf_counter() - start) * 1000)

            if resp.status_code != 200:
                logger.error(f"OPA returned {resp.status_code}: {resp.text}")
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"OPA evaluation error: {resp.status_code}",
                )

            result = resp.json().get("result", {})
            result["evaluation_ms"] = elapsed_ms
            logger.debug(
                f"OPA [{package_path}] action={action} "
                f"decision={result.get('decision')} ({elapsed_ms}ms)"
            )
            return result

        except httpx.TimeoutException:
            logger.error(f"OPA timeout for action={action}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="OPA policy evaluation timed out",
            )
        except HTTPException:
            raise
        except Exception as exc:
            logger.error(f"OPA call failed: {exc}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"OPA unreachable: {str(exc)}",
            )


# ---------------------------------------------------------------------------
# Singleton — services set these at import time via their config
# ---------------------------------------------------------------------------
_opa_client: Optional[OPAClient] = None


def init_opa_client(
    opa_url: str = _DEFAULT_OPA_URL,
    timeout: float = _DEFAULT_TIMEOUT,
    policy_service_url: Optional[str] = None,
) -> OPAClient:
    """Initialise (or reinitialise) the module-level OPA client singleton."""
    global _opa_client
    _opa_client = OPAClient(
        opa_url=opa_url,
        timeout=timeout,
        policy_service_url=policy_service_url,
    )
    return _opa_client


def get_opa_client() -> OPAClient:
    global _opa_client
    if _opa_client is None:
        _opa_client = OPAClient()
    return _opa_client


# ---------------------------------------------------------------------------
# FastAPI dependency factory — drop-in replacement for require_policy()
# ---------------------------------------------------------------------------

def require_opa_policy(
    action: str,
    *,
    package_path: str = "zeroque/provisioning",
    resource_from: str = "body",
    resource_fields: Optional[List[str]] = None,
):
    """FastAPI dependency that enforces an OPA Rego policy.

    Usage:
        @router.post("/sites")
        async def create_site(
            req: SiteCreate,
            ctx  = Depends(check_user_authorization("sites.manage")),
            gate = Depends(require_opa_policy("site.create")),
        ):
            ...

    The dependency:
      1. Extracts subject from the JWT token on the request.
      2. Extracts resource from the request body (or empty dict).
      3. POSTs to OPA sidecar at /v1/data/{package_path}.
      4. On ``deny``  -> raises 403 Forbidden.
      5. On ``require_approval`` -> raises 202 with approval info.
      6. On ``allow`` -> returns the OPA result dict.
    """

    async def dependency(request: Request) -> Dict[str, Any]:
        # Locate the JWT-decoding function for the calling service.
        # Convention: each service exposes decode_jwt_with_settings in core.user_auth
        # but we also read from request.state if already decoded upstream.
        claims: Dict[str, Any] = {}
        if hasattr(request.state, "jwt_claims"):
            claims = request.state.jwt_claims
        else:
            # Extract Bearer token manually as a fallback
            auth_header = request.headers.get("authorization", "")
            if auth_header.startswith("Bearer "):
                import jwt as pyjwt

                token = auth_header.split(" ", 1)[1]
                try:
                    claims = pyjwt.decode(
                        token,
                        options={"verify_signature": False},
                    )
                except Exception:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid token",
                    )

        subject = {
            "user_id": claims.get("sub", ""),
            "tenant_id": claims.get("tenant_id", ""),
            "roles": claims.get("roles", []),
            "permissions": claims.get("permissions", []),
            "email": claims.get("email", ""),
        }

        tenant_id = claims.get("tenant_id", "")

        # Build resource from request body
        resource: Dict[str, Any] = {}
        if resource_from == "body":
            try:
                body = await request.json()
                if isinstance(body, dict):
                    if resource_fields:
                        resource = {
                            k: body.get(k) for k in resource_fields if k in body
                        }
                    else:
                        resource = body
            except Exception:
                pass

        if "tenant_id" not in resource and tenant_id:
            resource["tenant_id"] = tenant_id

        # Call OPA
        opa = get_opa_client()
        result = await opa.evaluate(
            package_path=package_path,
            subject=subject,
            resource=resource,
            action=action,
        )

        decision = result.get("decision", "deny")

        if decision == "deny":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "policy_decision": "deny",
                    "reason": result.get("reason", "Denied by policy"),
                    "evaluation_ms": result.get("evaluation_ms"),
                },
            )

        if decision == "require_approval":
            raise HTTPException(
                status_code=202,
                detail={
                    "policy_decision": "require_approval",
                    "reason": result.get("reason", "Approval required"),
                    "approval_required": True,
                    "evaluation_ms": result.get("evaluation_ms"),
                },
            )

        return result

    return dependency
