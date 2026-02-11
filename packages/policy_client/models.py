"""
Policy Client Models
Data classes and exceptions for the policy client.
"""
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional


@dataclass
class MatchedRule:
    """Information about a rule that matched during evaluation"""
    policy_id: str
    policy_code: str
    rule_id: str
    rule_name: Optional[str]
    effect: str


@dataclass
class PolicyDecision:
    """
    Result of a policy evaluation.
    
    Attributes:
        allowed: Whether the action is permitted
        decision: Decision type ('allowed', 'denied', 'approval_required')
        reason: Human-readable explanation
        matched_rules: Rules that contributed to the decision
        approval_chain_id: If approval required, which chain to use
        actions: Additional actions to trigger
        decision_id: ID of the logged decision
        evaluation_duration_ms: Time taken to evaluate
    """
    allowed: bool
    decision: str
    reason: Optional[str] = None
    matched_rules: List[MatchedRule] = field(default_factory=list)
    approval_chain_id: Optional[str] = None
    actions: List[Dict[str, Any]] = field(default_factory=list)
    decision_id: Optional[str] = None
    evaluation_duration_ms: int = 0
    
    @property
    def requires_approval(self) -> bool:
        """Check if the action requires approval"""
        return self.decision == "approval_required"
    
    @property
    def is_denied(self) -> bool:
        """Check if the action was denied"""
        return self.decision == "denied"
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PolicyDecision":
        """Create from API response dict"""
        matched_rules = [
            MatchedRule(
                policy_id=r.get("policy_id", ""),
                policy_code=r.get("policy_code", ""),
                rule_id=r.get("rule_id", ""),
                rule_name=r.get("rule_name"),
                effect=r.get("effect", "")
            )
            for r in data.get("matched_rules", [])
        ]
        
        return cls(
            allowed=data.get("allowed", False),
            decision=data.get("decision", "denied"),
            reason=data.get("reason"),
            matched_rules=matched_rules,
            approval_chain_id=data.get("approval_chain_id"),
            actions=data.get("actions", []),
            decision_id=data.get("decision_id"),
            evaluation_duration_ms=data.get("evaluation_duration_ms", 0)
        )
    
    @classmethod
    def denied(cls, reason: str) -> "PolicyDecision":
        """Create a denied decision (for error cases)"""
        return cls(
            allowed=False,
            decision="denied",
            reason=reason
        )
    
    @classmethod
    def allowed_default(cls) -> "PolicyDecision":
        """Create an allowed decision (for when policy engine is unavailable and fail-open is enabled)"""
        return cls(
            allowed=True,
            decision="allowed",
            reason="Policy engine unavailable - default allow"
        )


@dataclass
class EvaluationRequest:
    """Request to evaluate an action against policies"""
    action: str
    subject: Dict[str, Any]
    resource: Dict[str, Any]
    context: Optional[Dict[str, Any]] = None
    dry_run: bool = False
    correlation_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to API request dict"""
        return {
            "action": self.action,
            "subject": self.subject,
            "resource": self.resource,
            "context": self.context or {},
            "dry_run": self.dry_run,
            "correlation_id": self.correlation_id
        }


class PolicyClientError(Exception):
    """Base exception for policy client errors"""
    def __init__(self, message: str, status_code: Optional[int] = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class PolicyDeniedException(PolicyClientError):
    """Raised when a policy denies an action"""
    def __init__(self, decision: PolicyDecision):
        self.decision = decision
        super().__init__(
            message=decision.reason or "Action denied by policy",
            status_code=403
        )


class PolicyApprovalRequiredException(PolicyClientError):
    """Raised when an action requires approval"""
    def __init__(self, decision: PolicyDecision):
        self.decision = decision
        self.approval_chain_id = decision.approval_chain_id
        super().__init__(
            message=decision.reason or "Action requires approval",
            status_code=202
        )
