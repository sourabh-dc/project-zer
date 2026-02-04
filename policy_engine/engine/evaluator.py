"""
Policy Engine Core Evaluator
The main policy evaluation engine that processes requests against policies.
"""
import uuid
import fnmatch
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from policy_engine.Models import Policy, PolicyVersion, PolicyRule, PolicyAssignment
from policy_engine.core.redis_client import PolicyCache
from policy_engine.core.config import SETTINGS
from policy_engine.engine.expression_parser import evaluate_expression, ExpressionError
from policy_engine.engine.context_enricher import ContextEnricher
from policy_engine.engine.decision_logger import log_decision
from policy_engine.utils.logger import logger


@dataclass
class PolicyDecision:
    """Result of policy evaluation"""
    allowed: bool
    decision: str  # 'allowed', 'denied', 'approval_required'
    reason: Optional[str] = None
    matched_rules: List[Dict] = field(default_factory=list)
    approval_chain_id: Optional[str] = None
    actions: List[Dict] = field(default_factory=list)
    decision_id: Optional[str] = None
    evaluation_duration_ms: int = 0


class PolicyEngine:
    """
    Central policy evaluation engine.
    
    Evaluates actions against applicable policies and returns decisions.
    Supports caching, context enrichment, and decision logging.
    
    Usage:
        engine = PolicyEngine(db_session, cache)
        decision = await engine.evaluate(
            action="order.create",
            subject={"user_id": "...", "tenant_id": "..."},
            resource={"order_total": 15000, "products": [...]},
            context={"channel": "web"}
        )
        
        if not decision.allowed:
            if decision.decision == "approval_required":
                # Create approval request
                pass
            else:
                raise HTTPException(403, decision.reason)
    """
    
    def __init__(self, db: Session, cache: Optional[PolicyCache] = None):
        self.db = db
        self.cache = cache
        self.enricher = ContextEnricher(db)
    
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
        Evaluate an action against all applicable policies.
        
        Args:
            action: The action being performed (e.g., 'order.create')
            subject: Who is performing the action (must include user_id, tenant_id)
            resource: What they are acting on
            context: Additional context (channel, store_id, etc.)
            dry_run: If True, don't log the decision
            correlation_id: Optional ID for request tracing
            
        Returns:
            PolicyDecision with allowed status, reason, and matched rules
        """
        start_time = datetime.now(timezone.utc)
        context = context or {}
        
        tenant_id = subject.get("tenant_id")
        if not tenant_id:
            return PolicyDecision(
                allowed=False,
                decision="denied",
                reason="Missing tenant_id in subject"
            )
        
        try:
            # 1. Enrich subject with additional data
            enriched_subject = await self.enricher.enrich_subject(subject)
            
            # 2. Enrich resource if needed
            enriched_resource = await self.enricher.enrich_resource(resource, tenant_id)
            
            # 3. Get applicable policies
            policies = await self._get_applicable_policies(
                tenant_id=tenant_id,
                action=action,
                context=context
            )
            
            if not policies:
                # No policies = allow by default
                decision = PolicyDecision(
                    allowed=True,
                    decision="allowed",
                    reason="No applicable policies"
                )
            else:
                # 4. Evaluate policies
                decision = await self._evaluate_policies(
                    policies=policies,
                    action=action,
                    subject=enriched_subject,
                    resource=enriched_resource,
                    context=context
                )
            
            # Calculate duration
            duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            decision.evaluation_duration_ms = duration_ms
            
            # 5. Log the decision (unless dry_run)
            if not dry_run:
                decision_id = await log_decision(
                    db=self.db,
                    tenant_id=tenant_id,
                    action=action,
                    subject=enriched_subject,
                    resource=enriched_resource,
                    context=context,
                    decision=decision,
                    duration_ms=duration_ms,
                    correlation_id=correlation_id
                )
                decision.decision_id = decision_id
            
            logger.info(
                f"Policy evaluation: action={action}, tenant={tenant_id}, "
                f"decision={decision.decision}, duration={duration_ms}ms"
            )
            
            return decision
            
        except Exception as e:
            logger.error(f"Policy evaluation failed: {e}", exc_info=True)
            # On error, deny by default for safety
            return PolicyDecision(
                allowed=False,
                decision="denied",
                reason=f"Policy evaluation error: {str(e)}"
            )
    
    async def _get_applicable_policies(
        self,
        tenant_id: str,
        action: str,
        context: Dict[str, Any]
    ) -> List[Policy]:
        """
        Get all policies that apply to this action and context.
        
        Considers:
        - Global policies (tenant_id IS NULL)
        - Tenant-specific policies
        - Scope-specific policies (site, store, org_unit)
        - Action pattern matching (e.g., 'order.*' matches 'order.create')
        """
        # Try cache first
        cache_key = f"policies:{tenant_id}:{action}"
        if self.cache and self.cache.is_connected:
            cached = await self.cache.get(cache_key)
            if cached:
                # Reconstruct policy objects from cached data
                return self._policies_from_cache(cached)
        
        now = datetime.now(timezone.utc)
        
        # Try to parse tenant_id as UUID, if it fails, only match global policies
        try:
            tenant_uuid = uuid.UUID(tenant_id) if tenant_id else None
        except (ValueError, AttributeError):
            tenant_uuid = None
            logger.warning(f"Invalid tenant_id format: {tenant_id}, only matching global policies")
        
        # Build query for applicable policies
        query = self.db.query(Policy).join(PolicyAssignment).filter(
            Policy.is_active == True,
            PolicyAssignment.is_active == True,
            # Global or tenant-specific
            or_(
                Policy.tenant_id == None,
                Policy.tenant_id == tenant_uuid if tenant_uuid else False
            ),
            # Valid time range (if specified)
            or_(
                PolicyAssignment.valid_from == None,
                PolicyAssignment.valid_from <= now
            ),
            or_(
                PolicyAssignment.valid_until == None,
                PolicyAssignment.valid_until >= now
            )
        )
        
        policies = query.all()
        
        # Filter by action pattern
        applicable = []
        for policy in policies:
            for assignment in policy.assignments:
                if self._action_matches_pattern(action, assignment.action_pattern):
                    # Check scope
                    if self._scope_matches(assignment, context):
                        applicable.append(policy)
                        break
        
        # Remove duplicates while preserving order
        seen = set()
        unique_policies = []
        for p in applicable:
            if p.policy_id not in seen:
                seen.add(p.policy_id)
                unique_policies.append(p)
        
        # Cache the result
        if self.cache and self.cache.is_connected:
            cache_data = self._policies_to_cache(unique_policies)
            await self.cache.set(cache_key, cache_data, SETTINGS.POLICY_CACHE_TTL_SECONDS)
        
        return unique_policies
    
    def _action_matches_pattern(self, action: str, pattern: str) -> bool:
        """
        Check if an action matches a pattern.
        
        Supports:
        - Exact match: 'order.create' matches 'order.create'
        - Wildcard: 'order.*' matches 'order.create', 'order.update'
        - Global: '*' matches everything
        """
        if pattern == '*':
            return True
        return fnmatch.fnmatch(action, pattern)
    
    def _scope_matches(self, assignment: PolicyAssignment, context: Dict[str, Any]) -> bool:
        """
        Check if the assignment scope matches the context.
        """
        if assignment.scope_type == 'global':
            return True
        
        if assignment.scope_type == 'tenant':
            # Tenant scope always matches (already filtered by tenant_id)
            return True
        
        # For site, store, org_unit - check if context has matching ID
        scope_id = str(assignment.scope_id) if assignment.scope_id else None
        context_id = context.get(f"{assignment.scope_type}_id")
        
        if scope_id and context_id:
            return scope_id == str(context_id)
        
        # If scope requires specific ID but context doesn't have it, don't match
        if scope_id and not context_id:
            return False
        
        return True
    
    async def _evaluate_policies(
        self,
        policies: List[Policy],
        action: str,
        subject: Dict[str, Any],
        resource: Dict[str, Any],
        context: Dict[str, Any]
    ) -> PolicyDecision:
        """
        Evaluate all applicable policies and determine the final decision.
        
        Evaluation order:
        1. Policies are sorted by priority (lower = first)
        2. Rules within each policy are sorted by rule_order
        3. First 'deny' effect stops evaluation
        4. 'require_approval' accumulates but can be overridden by 'deny'
        5. If no rules match, default is 'allow'
        """
        # Build evaluation context
        eval_context = {
            "subject": subject,
            "resource": resource,
            "context": context,
            "now": datetime.now(timezone.utc),
            "action": action
        }
        
        matched_rules = []
        final_decision = "allowed"
        final_reason = None
        approval_chain_id = None
        actions = []
        
        # Sort policies by priority
        sorted_policies = sorted(policies, key=lambda p: p.priority)
        
        for policy in sorted_policies:
            # Get current version's rules
            rules = await self._get_policy_rules(policy.policy_id)
            
            for rule in sorted(rules, key=lambda r: r.rule_order):
                if not rule.is_active:
                    continue
                
                # Evaluate the condition
                try:
                    condition_met = evaluate_expression(
                        rule.condition_expression,
                        eval_context
                    )
                except ExpressionError as e:
                    logger.warning(
                        f"Rule {rule.rule_id} expression error: {e}"
                    )
                    continue
                except Exception as e:
                    logger.error(
                        f"Rule {rule.rule_id} evaluation failed: {e}"
                    )
                    continue
                
                if condition_met:
                    # Record the match
                    matched_rules.append({
                        "policy_id": str(policy.policy_id),
                        "policy_code": policy.code,
                        "rule_id": str(rule.rule_id),
                        "rule_name": rule.name,
                        "effect": rule.effect
                    })
                    
                    # Apply the effect
                    if rule.effect == "deny":
                        final_decision = "denied"
                        final_reason = self._format_reason(
                            rule.denial_reason, eval_context
                        )
                        # Deny is final - stop evaluation
                        return PolicyDecision(
                            allowed=False,
                            decision="denied",
                            reason=final_reason,
                            matched_rules=matched_rules,
                            actions=actions
                        )
                    
                    elif rule.effect == "require_approval":
                        # Require approval, but continue checking for deny
                        final_decision = "approval_required"
                        final_reason = self._format_reason(
                            rule.denial_reason, eval_context
                        )
                        if rule.approval_chain_id:
                            approval_chain_id = str(rule.approval_chain_id)
                    
                    elif rule.effect == "allow":
                        # Explicit allow (can be overridden by deny/require_approval)
                        if final_decision == "allowed":
                            final_reason = "Allowed by policy"
                    
                    # Collect any additional actions
                    if rule.actions:
                        if isinstance(rule.actions, list):
                            actions.extend(rule.actions)
                        else:
                            actions.append(rule.actions)
        
        return PolicyDecision(
            allowed=(final_decision == "allowed"),
            decision=final_decision,
            reason=final_reason,
            matched_rules=matched_rules,
            approval_chain_id=approval_chain_id,
            actions=actions
        )
    
    async def _get_policy_rules(self, policy_id: uuid.UUID) -> List[PolicyRule]:
        """
        Get the current version's rules for a policy.
        """
        # Try cache
        cache_key = f"policy_rules:{policy_id}"
        if self.cache and self.cache.is_connected:
            cached = await self.cache.get(cache_key)
            if cached:
                return self._rules_from_cache(cached)
        
        # Get current version (effective_until is NULL)
        current_version = self.db.query(PolicyVersion).filter(
            PolicyVersion.policy_id == policy_id,
            PolicyVersion.effective_until == None
        ).first()
        
        if not current_version:
            return []
        
        rules = self.db.query(PolicyRule).filter(
            PolicyRule.version_id == current_version.version_id,
            PolicyRule.is_active == True
        ).order_by(PolicyRule.rule_order).all()
        
        # Cache
        if self.cache and self.cache.is_connected:
            cache_data = self._rules_to_cache(rules)
            await self.cache.set(cache_key, cache_data, SETTINGS.POLICY_CACHE_TTL_SECONDS)
        
        return rules
    
    def _format_reason(self, template: Optional[str], context: Dict[str, Any]) -> Optional[str]:
        """
        Format a reason template with context values.
        
        Supports {variable.path} syntax using regex substitution.
        """
        if not template:
            return None
        
        try:
            import re
            flat = self._flatten_dict(context)
            
            # Use regex to replace {path.to.value} with actual values
            def replace_var(match):
                var_path = match.group(1)
                if var_path in flat:
                    return str(flat[var_path])
                return match.group(0)  # Return original if not found
            
            return re.sub(r'\{([a-zA-Z_][a-zA-Z0-9_.]*)\}', replace_var, template)
        except Exception:
            return template
    
    def _flatten_dict(self, d: Dict, parent_key: str = '', sep: str = '.') -> Dict:
        """Flatten nested dict for template formatting"""
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten_dict(v, new_key, sep).items())
            else:
                items.append((new_key, v))
        return dict(items)
    
    def _policies_to_cache(self, policies: List[Policy]) -> List[Dict]:
        """Serialize policies for caching"""
        return [
            {
                "policy_id": str(p.policy_id),
                "tenant_id": str(p.tenant_id) if p.tenant_id else None,
                "code": p.code,
                "name": p.name,
                "policy_type": p.policy_type,
                "priority": p.priority,
            }
            for p in policies
        ]
    
    def _policies_from_cache(self, cached: List[Dict]) -> List[Policy]:
        """Deserialize policies from cache - returns lightweight objects"""
        # For cached policies, we still need to fetch from DB for full objects
        # This is a simplified version - in production you might want full caching
        policy_ids = [c["policy_id"] for c in cached]
        return self.db.query(Policy).filter(
            Policy.policy_id.in_([uuid.UUID(pid) for pid in policy_ids])
        ).all()
    
    def _rules_to_cache(self, rules: List[PolicyRule]) -> List[Dict]:
        """Serialize rules for caching"""
        return [
            {
                "rule_id": str(r.rule_id),
                "version_id": str(r.version_id),
                "rule_order": r.rule_order,
                "name": r.name,
                "condition_expression": r.condition_expression,
                "effect": r.effect,
                "denial_reason": r.denial_reason,
                "approval_chain_id": str(r.approval_chain_id) if r.approval_chain_id else None,
                "actions": r.actions,
                "is_active": r.is_active,
            }
            for r in rules
        ]
    
    def _rules_from_cache(self, cached: List[Dict]) -> List[PolicyRule]:
        """Deserialize rules from cache"""
        rules = []
        for c in cached:
            rule = PolicyRule(
                rule_id=uuid.UUID(c["rule_id"]),
                version_id=uuid.UUID(c["version_id"]),
                rule_order=c["rule_order"],
                name=c["name"],
                condition_expression=c["condition_expression"],
                effect=c["effect"],
                denial_reason=c["denial_reason"],
                approval_chain_id=uuid.UUID(c["approval_chain_id"]) if c["approval_chain_id"] else None,
                actions=c["actions"],
                is_active=c["is_active"],
            )
            rules.append(rule)
        return rules
