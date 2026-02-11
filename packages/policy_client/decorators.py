"""
Policy Client Decorators
Decorators for enforcing policies on FastAPI endpoints.
"""
import functools
from typing import Callable, Any, Optional, Dict, List
from fastapi import HTTPException, Request

from policy_client.client import get_policy_client
from policy_client.models import (
    PolicyDecision,
    PolicyDeniedException,
    PolicyApprovalRequiredException
)


def require_policy(
    action: str,
    get_subject: Optional[Callable[[Request, Dict[str, Any]], Dict[str, Any]]] = None,
    get_resource: Optional[Callable[[Request, Dict[str, Any]], Dict[str, Any]]] = None,
    get_context: Optional[Callable[[Request, Dict[str, Any]], Dict[str, Any]]] = None,
    raise_on_denial: bool = True,
    raise_on_approval: bool = False
):
    """
    Decorator to enforce policy checks on FastAPI endpoints.
    
    Usage:
        @router.post("/orders")
        @require_policy(
            action="order.create",
            get_subject=lambda req, kwargs: {
                "user_id": kwargs["current_user"].user_id,
                "tenant_id": kwargs["current_user"].tenant_id
            },
            get_resource=lambda req, kwargs: {
                "order_total": kwargs["order_data"].total
            }
        )
        async def create_order(order_data: OrderCreate, current_user: User = Depends(get_current_user)):
            ...
    
    Args:
        action: The policy action to evaluate
        get_subject: Function to extract subject from request/kwargs
        get_resource: Function to extract resource from request/kwargs
        get_context: Function to extract context from request/kwargs
        raise_on_denial: Raise HTTPException if denied (default True)
        raise_on_approval: Raise exception if approval required (default False)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Find Request object in args/kwargs
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            if request is None:
                request = kwargs.get("request")
            
            # Build subject
            if get_subject:
                subject = get_subject(request, kwargs)
            else:
                # Try to get from current_user dependency
                current_user = kwargs.get("current_user")
                if current_user:
                    subject = {
                        "user_id": str(getattr(current_user, "user_id", current_user.get("user_id", ""))),
                        "tenant_id": str(getattr(current_user, "tenant_id", current_user.get("tenant_id", "")))
                    }
                else:
                    raise ValueError("Cannot determine subject - provide get_subject function")
            
            # Build resource
            if get_resource:
                resource = get_resource(request, kwargs)
            else:
                resource = {}
            
            # Build context
            if get_context:
                context = get_context(request, kwargs)
            else:
                context = {}
                if request:
                    context["path"] = str(request.url.path)
                    context["method"] = request.method
            
            # Evaluate policy
            client = get_policy_client()
            decision = await client.evaluate(
                action=action,
                subject=subject,
                resource=resource,
                context=context
            )
            
            # Handle decision
            if not decision.allowed:
                if decision.requires_approval:
                    if raise_on_approval:
                        raise PolicyApprovalRequiredException(decision)
                    # Store decision in request state for handler to use
                    if request:
                        request.state.policy_decision = decision
                else:
                    if raise_on_denial:
                        raise HTTPException(
                            status_code=403,
                            detail=decision.reason or "Action denied by policy"
                        )
                    if request:
                        request.state.policy_decision = decision
            else:
                if request:
                    request.state.policy_decision = decision
            
            # Call the actual endpoint
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator


def check_policy(
    action: str,
    subject: Dict[str, Any],
    resource: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None
) -> Callable:
    """
    Simple decorator for checking a specific policy.
    
    Unlike require_policy, this uses static values rather than
    extracting from the request.
    
    Usage:
        @check_policy(
            action="admin.access",
            subject={"user_id": "system", "tenant_id": "global"},
            resource={}
        )
        async def admin_endpoint():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            client = get_policy_client()
            decision = await client.evaluate(
                action=action,
                subject=subject,
                resource=resource,
                context=context
            )
            
            if not decision.allowed:
                raise HTTPException(
                    status_code=403,
                    detail=decision.reason or "Action denied by policy"
                )
            
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator


class PolicyChecker:
    """
    Helper class for checking policies in endpoint handlers.
    
    Usage:
        checker = PolicyChecker(current_user)
        
        if not await checker.can("order.create", {"order_total": 15000}):
            raise HTTPException(403, "Cannot create order")
        
        decision = await checker.check("order.create", {"order_total": 15000})
        if decision.requires_approval:
            # Create approval request
            pass
    """
    
    def __init__(self, user: Any):
        """
        Initialize with a user object.
        
        User should have user_id and tenant_id attributes.
        """
        self.user_id = str(getattr(user, "user_id", user.get("user_id", "")))
        self.tenant_id = str(getattr(user, "tenant_id", user.get("tenant_id", "")))
        self._client = get_policy_client()
    
    async def check(
        self,
        action: str,
        resource: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> PolicyDecision:
        """
        Check if an action is allowed.
        
        Returns the full PolicyDecision.
        """
        return await self._client.evaluate(
            action=action,
            subject={"user_id": self.user_id, "tenant_id": self.tenant_id},
            resource=resource,
            context=context
        )
    
    async def can(
        self,
        action: str,
        resource: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Quick check if an action is allowed.
        
        Returns True if allowed, False otherwise.
        """
        decision = await self.check(action, resource or {}, context)
        return decision.allowed
    
    async def require(
        self,
        action: str,
        resource: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> PolicyDecision:
        """
        Check if an action is allowed, raising HTTPException if not.
        
        Returns the PolicyDecision if allowed.
        """
        decision = await self.check(action, resource or {}, context)
        
        if not decision.allowed and not decision.requires_approval:
            raise HTTPException(
                status_code=403,
                detail=decision.reason or "Action denied by policy"
            )
        
        return decision
    
    async def batch_check(
        self,
        actions: List[str],
        resource: Optional[Dict[str, Any]] = None
    ) -> Dict[str, bool]:
        """
        Check multiple actions at once.
        
        Returns a dict mapping action -> allowed.
        """
        from policy_client.models import EvaluationRequest
        
        requests = [
            EvaluationRequest(
                action=action,
                subject={"user_id": self.user_id, "tenant_id": self.tenant_id},
                resource=resource or {},
                dry_run=True  # Don't log batch checks
            )
            for action in actions
        ]
        
        decisions = await self._client.batch_evaluate(requests)
        
        return {
            action: decision.allowed
            for action, decision in zip(actions, decisions)
        }
