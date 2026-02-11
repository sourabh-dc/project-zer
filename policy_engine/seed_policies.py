"""
Seed script for default policies in the Policy Engine.
Run this after the Policy Engine database is initialized.

Usage:
    python -m policy_engine.seed_policies
    
Or via API:
    POST /v1/policy-engine/seed
"""

import os
import sys
import json
from datetime import datetime, timezone
from uuid import uuid4

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from policy_engine.Models import Policy, PolicyVersion, PolicyRule, PolicyActionType, PolicyAssignment, Base
from policy_engine.core.config import SETTINGS as settings


# Default Action Types
ACTION_TYPES = [
    {
        "code": "order.create",
        "name": "Create Order",
        "description": "Creating a new order",
        "category": "orders"
    },
    {
        "code": "order.cancel",
        "name": "Cancel Order",
        "description": "Cancelling an existing order",
        "category": "orders"
    },
    {
        "code": "approval.respond",
        "name": "Respond to Approval",
        "description": "Responding to an approval request (approve/deny)",
        "category": "approvals"
    },
    {
        "code": "approval.cancel",
        "name": "Cancel Approval Request",
        "description": "Cancelling an approval request",
        "category": "approvals"
    },
    {
        "code": "entitlement.check",
        "name": "Check Entitlement",
        "description": "Checking if a feature/entitlement can be used",
        "category": "entitlements"
    },
    {
        "code": "entitlement.use",
        "name": "Use Entitlement",
        "description": "Recording usage of a feature/entitlement",
        "category": "entitlements"
    }
]


# Default Policies with their rules
POLICIES = [
    # ============================================
    # ORDER POLICIES
    # ============================================
    {
        "code": "order.cost_centre_assignment",
        "name": "Cost Centre Assignment Check",
        "description": "Ensures user is assigned to a cost centre before placing orders",
        "policy_type": "authorization",
        "priority": 100,
        "action_pattern": "order.create",  # Action pattern for assignment
        "rules": [
            {
                "name": "User Must Be Assigned to Cost Centre",
                "description": "Deny order if user has no cost centre assignment",
                "condition_expression": "subject.cost_centre_id == None",
                "effect": "deny",
                "rule_order": 1,
                "denial_reason": "User not assigned to any cost centre. Please contact your manager."
            }
        ]
    },
    {
        "code": "order.budget.check",
        "name": "User Budget Check",
        "description": "Validates user has sufficient budget for the order",
        "policy_type": "budget",
        "priority": 200,
        "action_pattern": "order.create",
        "rules": [
            {
                "name": "Insufficient User Budget",
                "description": "Deny order if user budget is insufficient",
                "condition_expression": "subject.budget_remaining < resource.order_total",
                "effect": "deny",
                "rule_order": 1,
                "denial_reason": "Insufficient budget. Available: {subject.budget_remaining}, Required: {resource.order_total}"
            }
        ]
    },
    {
        "code": "order.large_order_approval",
        "name": "Large Order Approval",
        "description": "Requires approval for orders exceeding user's ordering limit",
        "policy_type": "approval",
        "priority": 300,
        "action_pattern": "order.create",
        "rules": [
            {
                "name": "Order Exceeds User Limit",
                "description": "Require approval if order exceeds user's max ordering limit",
                "condition_expression": "resource.order_total > subject.max_order_limit_minor",
                "effect": "require_approval",
                "rule_order": 1,
                "denial_reason": "Order of {resource.order_total} exceeds your ordering limit of {subject.max_order_limit_minor}. Approval required."
            }
        ]
    },
    
    # ============================================
    # APPROVAL POLICIES
    # ============================================
    {
        "code": "approval.respond",
        "name": "Approval Response Rules",
        "description": "Rules governing who can respond to approval requests",
        "policy_type": "authorization",
        "priority": 100,
        "action_pattern": "approval.respond",
        "rules": [
            {
                "name": "Request Expired",
                "description": "Deny response if request has expired",
                "condition_expression": "resource.is_expired == True",
                "effect": "deny",
                "rule_order": 1,
                "denial_reason": "This approval request has expired"
            },
            {
                "name": "Approver Org Unit Mismatch",
                "description": "Deny if approver is not in same org unit as requester",
                "condition_expression": "subject.org_unit_id != resource.org_unit_id and subject.org_unit_id != None and resource.org_unit_id != None",
                "effect": "deny",
                "rule_order": 2,
                "denial_reason": "You are not in the same organizational unit as the requester"
            },
            {
                "name": "Approver Limit Exceeded",
                "description": "Deny if request amount exceeds approver's remaining limit",
                "condition_expression": "resource.request_amount > subject.approver_limit_remaining",
                "effect": "deny",
                "rule_order": 3,
                "denial_reason": "Request amount of {resource.request_amount} exceeds your remaining approval limit of {subject.approver_limit_remaining}"
            }
        ]
    },
    {
        "code": "approval.cancel",
        "name": "Approval Cancellation Rules",
        "description": "Rules governing who can cancel approval requests",
        "policy_type": "authorization",
        "priority": 100,
        "action_pattern": "approval.cancel",
        "rules": [
            {
                "name": "Only Requester or Admin Can Cancel",
                "description": "Only the original requester or tenant admin can cancel",
                "condition_expression": "resource.requested_by != subject.user_id and 'tenant_admin' not in subject.roles",
                "effect": "deny",
                "rule_order": 1,
                "denial_reason": "Only the requester or tenant admin can cancel this request"
            }
        ]
    },
    
    # ============================================
    # ENTITLEMENT POLICIES
    # ============================================
    {
        "code": "entitlement.access",
        "name": "Entitlement Access Rules",
        "description": "Rules governing access to features and entitlements",
        "policy_type": "authorization",
        "priority": 100,
        "action_pattern": "entitlement.*",  # Matches entitlement.check and entitlement.use
        "rules": [
            {
                "name": "Cross-Tenant Access Denied",
                "description": "Prevent access to other tenant's data",
                "condition_expression": "subject.tenant_id != resource.tenant_id",
                "effect": "deny",
                "rule_order": 1,
                "denial_reason": "Access denied to other tenant's data"
            },
            {
                "name": "No Active Subscription",
                "description": "Deny access if subscription is not active",
                "condition_expression": "subject.subscription_active == False",
                "effect": "deny",
                "rule_order": 2,
                "denial_reason": "No active subscription. Please renew your subscription."
            },
            {
                "name": "Feature Not in Plan",
                "description": "Deny access if feature is not in tenant's plan",
                "condition_expression": "resource.feature_in_plan == False",
                "effect": "deny",
                "rule_order": 3,
                "denial_reason": "Feature '{resource.feature_code}' is not included in your plan"
            },
            {
                "name": "Usage Limit Exceeded",
                "description": "Deny if usage would exceed limit",
                "condition_expression": "resource.would_exceed_limit == True",
                "effect": "deny",
                "rule_order": 4,
                "denial_reason": "Usage limit exceeded. Current: {resource.current_usage}/{resource.usage_limit}"
            }
        ]
    }
]


def seed_action_types(session):
    """Seed default action types"""
    print("Seeding action types...")
    created = 0
    
    for at_data in ACTION_TYPES:
        existing = session.query(PolicyActionType).filter_by(code=at_data["code"]).first()
        if existing:
            print(f"  ⏭️  Action type '{at_data['code']}' already exists")
            continue
            
        action_type = PolicyActionType(
            action_type_id=uuid4(),
            code=at_data["code"],
            name=at_data["name"],
            description=at_data["description"],
            category=at_data["category"],
            created_at=datetime.now(timezone.utc)
        )
        session.add(action_type)
        created += 1
        print(f"  ✅ Created action type: {at_data['code']}")
    
    session.commit()
    print(f"Action types: {created} created, {len(ACTION_TYPES) - created} already existed")
    return created


def seed_policies(session):
    """Seed default policies with their rules"""
    print("\nSeeding policies...")
    created = 0
    
    for policy_data in POLICIES:
        existing = session.query(Policy).filter_by(code=policy_data["code"], tenant_id=None).first()
        if existing:
            print(f"  ⏭️  Policy '{policy_data['code']}' already exists")
            continue
        
        # Create policy
        policy = Policy(
            policy_id=uuid4(),
            code=policy_data["code"],
            name=policy_data["name"],
            description=policy_data["description"],
            policy_type=policy_data["policy_type"],
            priority=policy_data["priority"],
            is_active=True,
            tenant_id=None,  # Global policies
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        session.add(policy)
        session.flush()  # Get the policy_id
        
        # Create initial version with rules
        rules_json = []
        for rule_data in policy_data["rules"]:
            rules_json.append({
                "name": rule_data["name"],
                "description": rule_data.get("description"),
                "condition_expression": rule_data["condition_expression"],
                "effect": rule_data["effect"],
                "rule_order": rule_data["rule_order"],
                "denial_reason": rule_data.get("denial_reason")
            })
        
        version = PolicyVersion(
            version_id=uuid4(),
            policy_id=policy.policy_id,
            version_number=1,
            rules_json=rules_json,
            effective_from=datetime.now(timezone.utc),
            effective_until=None,  # Current version
            created_at=datetime.now(timezone.utc),
            change_reason="Initial policy creation"
        )
        session.add(version)
        session.flush()
        
        # Create individual rule records
        for rule_data in policy_data["rules"]:
            rule = PolicyRule(
                rule_id=uuid4(),
                version_id=version.version_id,
                name=rule_data["name"],
                description=rule_data.get("description"),
                condition_expression=rule_data["condition_expression"],
                effect=rule_data["effect"],
                rule_order=rule_data["rule_order"],
                denial_reason=rule_data.get("denial_reason"),
                is_active=True,
                created_at=datetime.now(timezone.utc)
            )
            session.add(rule)
        
        # Create global assignment for this policy
        assignment = PolicyAssignment(
            assignment_id=uuid4(),
            policy_id=policy.policy_id,
            scope_type="global",
            scope_id=None,
            action_pattern=policy_data.get("action_pattern", "*"),
            is_active=True,
            created_at=datetime.now(timezone.utc)
        )
        session.add(assignment)
        
        created += 1
        print(f"  ✅ Created policy: {policy_data['code']} with {len(policy_data['rules'])} rules (action: {policy_data.get('action_pattern', '*')})")
    
    session.commit()
    print(f"Policies: {created} created, {len(POLICIES) - created} already existed")
    return created


def main():
    """Main seed function"""
    print("=" * 60)
    print("Policy Engine - Seed Script")
    print("=" * 60)
    
    # Get database URL from environment or config
    database_url = os.getenv("DATABASE_URL", settings.DATABASE_URL)
    print(f"\nConnecting to: {database_url.split('@')[-1] if '@' in database_url else database_url}")
    
    # Create engine and session
    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        # Seed action types first
        seed_action_types(session)
        
        # Seed policies with rules
        seed_policies(session)
        
        print("\n" + "=" * 60)
        print("✅ Seeding completed successfully!")
        print("=" * 60)
        
    except Exception as e:
        session.rollback()
        print(f"\n❌ Error during seeding: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
