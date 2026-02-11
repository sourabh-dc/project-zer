"""
Policy Engine Client Library

Shared client for other services to call the Policy Engine.

Usage:
    from policy_client import PolicyClient, PolicyDecision
    
    client = PolicyClient()
    
    decision = await client.evaluate(
        action="order.create",
        subject={"user_id": "...", "tenant_id": "..."},
        resource={"order_total": 15000}
    )
    
    if not decision.allowed:
        if decision.requires_approval:
            # Create approval request
            pass
        else:
            raise HTTPException(403, decision.reason)
"""

from policy_client.client import PolicyClient
from policy_client.models import (
    PolicyDecision,
    EvaluationRequest,
    PolicyClientError,
    PolicyDeniedException,
    PolicyApprovalRequiredException
)
from policy_client.decorators import require_policy, check_policy

__all__ = [
    "PolicyClient",
    "PolicyDecision",
    "EvaluationRequest",
    "PolicyClientError",
    "PolicyDeniedException",
    "PolicyApprovalRequiredException",
    "require_policy",
    "check_policy"
]
