"""
Policy Evaluation API Routes
Endpoints for evaluating actions against policies.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session

from policy_engine.core.db_config import get_db
from policy_engine.core.redis_client import PolicyCache, get_cache
from policy_engine.engine.evaluator import PolicyEngine, PolicyDecision
from policy_engine.Schemas import EvaluationRequest, EvaluationResponse, MatchedRule
from policy_engine.utils.logger import logger


router = APIRouter(prefix="/v1/policy-engine", tags=["Policy Evaluation"])


@router.post("/evaluate", response_model=EvaluationResponse)
async def evaluate_policy(
    request: EvaluationRequest,
    db: Session = Depends(get_db),
    cache: PolicyCache = Depends(get_cache),
    x_correlation_id: Optional[str] = Header(None)
):
    """
    Evaluate an action against applicable policies.
    
    This is the main endpoint that other services call to check
    if an action should be allowed.
    
    Returns:
    - **allowed**: Whether the action is permitted
    - **decision**: 'allowed', 'denied', or 'approval_required'
    - **reason**: Human-readable explanation
    - **matched_rules**: List of rules that contributed to the decision
    - **approval_chain_id**: If approval required, which chain to use
    - **actions**: Additional actions to trigger (notifications, etc.)
    
    Example request:
    ```json
    {
        "action": "order.create",
        "subject": {
            "user_id": "550e8400-e29b-41d4-a716-446655440000",
            "tenant_id": "550e8400-e29b-41d4-a716-446655440001",
            "roles": ["employee"]
        },
        "resource": {
            "order_total": 15000,
            "products": [{"id": "prod-1", "restricted": false}]
        },
        "context": {
            "channel": "web",
            "store_id": "550e8400-e29b-41d4-a716-446655440002"
        }
    }
    ```
    """
    # Validate required fields in subject
    if "tenant_id" not in request.subject:
        raise HTTPException(
            status_code=400,
            detail="subject.tenant_id is required"
        )
    
    if "user_id" not in request.subject:
        raise HTTPException(
            status_code=400,
            detail="subject.user_id is required"
        )
    
    # Create engine and evaluate
    engine = PolicyEngine(db, cache)
    
    correlation_id = request.correlation_id or x_correlation_id
    
    decision: PolicyDecision = await engine.evaluate(
        action=request.action,
        subject=request.subject,
        resource=request.resource,
        context=request.context or {},
        dry_run=request.dry_run,
        correlation_id=correlation_id
    )
    
    # Convert to response
    matched_rules = [
        MatchedRule(
            policy_id=r["policy_id"],
            policy_code=r["policy_code"],
            rule_id=r["rule_id"],
            rule_name=r.get("rule_name"),
            effect=r["effect"]
        )
        for r in decision.matched_rules
    ]
    
    return EvaluationResponse(
        allowed=decision.allowed,
        decision=decision.decision,
        reason=decision.reason,
        matched_rules=matched_rules,
        approval_chain_id=decision.approval_chain_id,
        actions=decision.actions,
        decision_id=decision.decision_id,
        evaluation_duration_ms=decision.evaluation_duration_ms
    )


@router.post("/batch-evaluate")
async def batch_evaluate_policies(
    requests: list[EvaluationRequest],
    db: Session = Depends(get_db),
    cache: PolicyCache = Depends(get_cache),
    x_correlation_id: Optional[str] = Header(None)
):
    """
    Evaluate multiple actions in a single request.
    
    Useful for checking multiple permissions at once,
    e.g., when loading a UI that needs to know which actions are available.
    
    Returns a list of evaluation results in the same order as the requests.
    """
    if len(requests) > 50:
        raise HTTPException(
            status_code=400,
            detail="Maximum 50 evaluations per batch"
        )
    
    engine = PolicyEngine(db, cache)
    results = []
    
    for i, request in enumerate(requests):
        try:
            decision = await engine.evaluate(
                action=request.action,
                subject=request.subject,
                resource=request.resource,
                context=request.context or {},
                dry_run=request.dry_run,
                correlation_id=request.correlation_id or x_correlation_id
            )
            
            matched_rules = [
                MatchedRule(
                    policy_id=r["policy_id"],
                    policy_code=r["policy_code"],
                    rule_id=r["rule_id"],
                    rule_name=r.get("rule_name"),
                    effect=r["effect"]
                )
                for r in decision.matched_rules
            ]
            
            results.append(EvaluationResponse(
                allowed=decision.allowed,
                decision=decision.decision,
                reason=decision.reason,
                matched_rules=matched_rules,
                approval_chain_id=decision.approval_chain_id,
                actions=decision.actions,
                decision_id=decision.decision_id,
                evaluation_duration_ms=decision.evaluation_duration_ms
            ))
        except Exception as e:
            logger.error(f"Batch evaluation error at index {i}: {e}")
            results.append(EvaluationResponse(
                allowed=False,
                decision="denied",
                reason=f"Evaluation error: {str(e)}",
                matched_rules=[],
                evaluation_duration_ms=0
            ))
    
    return results


@router.post("/check", response_model=dict)
async def quick_check(
    action: str,
    tenant_id: str,
    user_id: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    db: Session = Depends(get_db),
    cache: PolicyCache = Depends(get_cache)
):
    """
    Quick permission check with minimal payload.
    
    Simpler endpoint for basic access checks where you just need
    a yes/no answer without full context.
    
    Returns:
    - **allowed**: boolean
    - **reason**: string (only if denied)
    """
    engine = PolicyEngine(db, cache)
    
    subject = {
        "user_id": user_id,
        "tenant_id": tenant_id
    }
    
    resource = {}
    if resource_type:
        resource["type"] = resource_type
    if resource_id:
        resource["id"] = resource_id
    
    decision = await engine.evaluate(
        action=action,
        subject=subject,
        resource=resource,
        dry_run=True  # Quick checks don't need logging
    )
    
    result = {"allowed": decision.allowed}
    if not decision.allowed:
        result["reason"] = decision.reason
    
    return result
