"""
Policy Engine HTTP Client
Async client for calling the Policy Engine service.
"""
import os
import asyncio
from typing import Dict, Any, Optional, List
import httpx

from policy_client.models import (
    PolicyDecision,
    EvaluationRequest,
    PolicyClientError
)


class PolicyClient:
    """
    HTTP client for the Policy Engine service.
    
    Provides async methods for evaluating policies and managing policy data.
    
    Usage:
        client = PolicyClient()
        
        decision = await client.evaluate(
            action="order.create",
            subject={"user_id": "...", "tenant_id": "..."},
            resource={"order_total": 15000}
        )
        
        if not decision.allowed:
            # Handle denial or approval requirement
            pass
    
    Configuration (via environment variables):
        POLICY_ENGINE_URL: Base URL of the policy engine (default: http://localhost:8004)
        POLICY_ENGINE_TIMEOUT: Request timeout in seconds (default: 5)
        POLICY_ENGINE_FAIL_OPEN: If true, allow actions when policy engine is unavailable (default: false)
    """
    
    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        fail_open: Optional[bool] = None
    ):
        """
        Initialize the policy client.
        
        Args:
            base_url: Policy engine URL (default from POLICY_ENGINE_URL env var)
            timeout: Request timeout in seconds (default from POLICY_ENGINE_TIMEOUT)
            fail_open: Allow actions when policy engine unavailable (default from POLICY_ENGINE_FAIL_OPEN)
        """
        self.base_url = base_url or os.getenv("POLICY_ENGINE_URL", "http://localhost:8004")
        self.timeout = timeout or float(os.getenv("POLICY_ENGINE_TIMEOUT", "5"))
        self.fail_open = fail_open if fail_open is not None else os.getenv("POLICY_ENGINE_FAIL_OPEN", "false").lower() == "true"
        
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"}
            )
        return self._client
    
    async def close(self):
        """Close the HTTP client"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
    
    async def evaluate(
        self,
        action: str,
        subject: Dict[str, Any],
        resource: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
        correlation_id: Optional[str] = None
    ) -> PolicyDecision:
        """
        Evaluate an action against policies.
        
        Args:
            action: The action to evaluate (e.g., 'order.create')
            subject: Who is performing the action (must include user_id, tenant_id)
            resource: What they are acting on
            context: Additional context (channel, store_id, etc.)
            dry_run: If True, don't log the decision
            correlation_id: Optional ID for request tracing
            
        Returns:
            PolicyDecision with allowed status and details
            
        Raises:
            PolicyClientError: If the request fails and fail_open is False
        """
        request = EvaluationRequest(
            action=action,
            subject=subject,
            resource=resource,
            context=context,
            dry_run=dry_run,
            correlation_id=correlation_id
        )
        
        try:
            client = await self._get_client()
            response = await client.post(
                "/v1/policy-engine/evaluate",
                json=request.to_dict()
            )
            
            if response.status_code == 200:
                return PolicyDecision.from_dict(response.json())
            else:
                error_detail = response.json().get("detail", "Unknown error")
                raise PolicyClientError(
                    f"Policy evaluation failed: {error_detail}",
                    status_code=response.status_code
                )
                
        except httpx.RequestError as e:
            if self.fail_open:
                return PolicyDecision.allowed_default()
            raise PolicyClientError(f"Policy engine unavailable: {str(e)}")
        except httpx.HTTPStatusError as e:
            if self.fail_open:
                return PolicyDecision.allowed_default()
            raise PolicyClientError(
                f"Policy engine error: {str(e)}",
                status_code=e.response.status_code
            )
    
    async def batch_evaluate(
        self,
        requests: List[EvaluationRequest]
    ) -> List[PolicyDecision]:
        """
        Evaluate multiple actions in a single request.
        
        Args:
            requests: List of EvaluationRequest objects
            
        Returns:
            List of PolicyDecision objects in the same order
        """
        try:
            client = await self._get_client()
            response = await client.post(
                "/v1/policy-engine/batch-evaluate",
                json=[r.to_dict() for r in requests]
            )
            
            if response.status_code == 200:
                return [PolicyDecision.from_dict(d) for d in response.json()]
            else:
                error_detail = response.json().get("detail", "Unknown error")
                raise PolicyClientError(
                    f"Batch evaluation failed: {error_detail}",
                    status_code=response.status_code
                )
                
        except httpx.RequestError as e:
            if self.fail_open:
                return [PolicyDecision.allowed_default() for _ in requests]
            raise PolicyClientError(f"Policy engine unavailable: {str(e)}")
    
    async def quick_check(
        self,
        action: str,
        tenant_id: str,
        user_id: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None
    ) -> bool:
        """
        Quick permission check with minimal payload.
        
        Args:
            action: The action to check
            tenant_id: Tenant ID
            user_id: User ID
            resource_type: Optional resource type
            resource_id: Optional resource ID
            
        Returns:
            True if allowed, False otherwise
        """
        try:
            client = await self._get_client()
            params = {
                "action": action,
                "tenant_id": tenant_id,
                "user_id": user_id
            }
            if resource_type:
                params["resource_type"] = resource_type
            if resource_id:
                params["resource_id"] = resource_id
            
            response = await client.post("/v1/policy-engine/check", params=params)
            
            if response.status_code == 200:
                return response.json().get("allowed", False)
            return False
            
        except Exception:
            return self.fail_open
    
    async def health_check(self) -> bool:
        """
        Check if the policy engine is healthy.
        
        Returns:
            True if healthy, False otherwise
        """
        try:
            client = await self._get_client()
            response = await client.get("/health")
            return response.status_code == 200
        except Exception:
            return False


# Global client instance (optional convenience)
_default_client: Optional[PolicyClient] = None


def get_policy_client() -> PolicyClient:
    """
    Get the default policy client instance.
    
    Creates a new client if one doesn't exist.
    """
    global _default_client
    if _default_client is None:
        _default_client = PolicyClient()
    return _default_client


async def evaluate(
    action: str,
    subject: Dict[str, Any],
    resource: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
    **kwargs
) -> PolicyDecision:
    """
    Convenience function to evaluate a policy using the default client.
    
    Usage:
        from policy_client import evaluate
        
        decision = await evaluate(
            action="order.create",
            subject={"user_id": "...", "tenant_id": "..."},
            resource={"order_total": 15000}
        )
    """
    client = get_policy_client()
    return await client.evaluate(action, subject, resource, context, **kwargs)
