"""
Policy Loader - Automatically loads policies from CSV during startup
"""
import csv
import json
import uuid
import os
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy import func

from policy_engine.Models import (
    Policy, PolicyVersion, PolicyRule, PolicyAssignment, PolicyActionType
)

logger = logging.getLogger(__name__)

# Default CSV path
DEFAULT_CSV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "policies.csv")


def _parse_bool(val: str) -> bool:
    """Parse string to boolean"""
    if val is None:
        return False
    return str(val).strip().lower() in ("1", "true", "yes", "y")


def _parse_optional_uuid(val: str) -> Optional[uuid.UUID]:
    """Parse string to UUID or return None"""
    if val is None or str(val).strip() == "":
        return None
    try:
        return uuid.UUID(str(val).strip())
    except Exception:
        return None


def _parse_optional_int(val: str) -> Optional[int]:
    """Parse string to int or return None"""
    if val is None or str(val).strip() == "":
        return None
    try:
        return int(val)
    except ValueError:
        return None


def _parse_json(val: str) -> Optional[Dict[str, Any]]:
    """Parse JSON string or return None"""
    if val is None or str(val).strip() == "":
        return None
    try:
        return json.loads(val)
    except json.JSONDecodeError:
        return None


def _parse_datetime(val: str) -> Optional[datetime]:
    """Parse datetime string or return None"""
    if val is None or str(val).strip() == "":
        return None
    try:
        return datetime.fromisoformat(val.strip())
    except Exception:
        return None


def load_policies(session: Session, csv_path: str = None):
    """
    Load policies from CSV file into the database.

    CSV Columns:
    - Policy: policy_code, policy_name, policy_description, policy_type, priority, is_active
    - Version: version_number, effective_from, effective_until
    - Rule: rule_order, rule_name, rule_description, condition_expression, effect,
            denial_reason, approval_chain_id, actions_json, rule_is_active
    - Assignment: assignment_scope_type, assignment_scope_id, action_pattern,
                  assignment_priority_override, assignment_is_active
    - ActionType: action_type_code, action_type_name, action_type_description,
                  action_type_category, subject_schema_json, resource_schema_json, context_schema_json

    Args:
        session: SQLAlchemy database session
        csv_path: Path to the policies CSV file (defaults to policy_engine/policies.csv)
    """
    if csv_path is None:
        csv_path = DEFAULT_CSV_PATH

    if not os.path.exists(csv_path):
        logger.warning(f"Policies CSV not found at {csv_path}. Skipping policy loading.")
        return

    logger.info(f"Loading policies from {csv_path}")

    # Caches to avoid duplicate lookups
    policy_cache: Dict[str, Policy] = {}
    version_cache: Dict[str, PolicyVersion] = {}
    action_type_cache: Dict[str, PolicyActionType] = {}

    policies_loaded = 0
    versions_loaded = 0
    rules_loaded = 0
    assignments_loaded = 0
    action_types_loaded = 0

    try:
        with open(csv_path, newline="", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)

            for row_num, row in enumerate(reader, start=2):  # Start at 2 to account for header
                try:
                    # --- POLICY ---
                    policy_code = (row.get("policy_code") or "").strip()
                    if not policy_code:
                        logger.warning(f"Row {row_num}: Skipping row with empty policy_code")
                        continue

                    policy = policy_cache.get(policy_code)
                    if policy is None:
                        # Check if policy already exists in DB (global policy: tenant_id=NULL)
                        policy = session.query(Policy).filter(
                            Policy.code == policy_code,
                            Policy.tenant_id.is_(None)
                        ).first()

                        if policy is None:
                            # Create new policy
                            policy = Policy(
                                code=policy_code,
                                name=(row.get("policy_name") or policy_code).strip(),
                                description=(row.get("policy_description") or "").strip() or None,
                                policy_type=(row.get("policy_type") or "access").strip(),
                                priority=_parse_optional_int(row.get("priority")) or 100,
                                is_active=_parse_bool(row.get("is_active"))
                            )
                            session.add(policy)
                            session.flush()
                            policies_loaded += 1
                            logger.debug(f"Created policy: {policy_code}")

                        policy_cache[policy_code] = policy

                    # --- POLICY VERSION ---
                    version_number = _parse_optional_int(row.get("version_number")) or 1
                    version_key = f"{policy.policy_id}:{version_number}"

                    version = version_cache.get(version_key)
                    if version is None:
                        # Check if version exists
                        version = session.query(PolicyVersion).filter(
                            PolicyVersion.policy_id == policy.policy_id,
                            PolicyVersion.version_number == version_number
                        ).first()

                        if version is None:
                            # Create new version
                            version = PolicyVersion(
                                policy_id=policy.policy_id,
                                version_number=version_number,
                                rules_json={},  # Rules stored in PolicyRule table
                                effective_from=_parse_datetime(row.get("effective_from")) or datetime.utcnow(),
                                effective_until=_parse_datetime(row.get("effective_until"))
                            )
                            session.add(version)
                            session.flush()
                            versions_loaded += 1
                            logger.debug(f"Created version {version_number} for policy: {policy_code}")

                        version_cache[version_key] = version

                    # --- POLICY RULE ---
                    rule_order = _parse_optional_int(row.get("rule_order")) or 0
                    condition_expression = (row.get("condition_expression") or "").strip()

                    if condition_expression:
                        # Check if rule already exists
                        existing_rule = session.query(PolicyRule).filter(
                            PolicyRule.version_id == version.version_id,
                            PolicyRule.rule_order == rule_order
                        ).first()

                        if existing_rule is None:
                            # Create new rule
                            rule = PolicyRule(
                                version_id=version.version_id,
                                rule_order=rule_order,
                                name=(row.get("rule_name") or "").strip() or None,
                                description=(row.get("rule_description") or "").strip() or None,
                                condition_expression=condition_expression,
                                effect=(row.get("effect") or "deny").strip(),
                                denial_reason=(row.get("denial_reason") or "").strip() or None,
                                approval_chain_id=_parse_optional_uuid(row.get("approval_chain_id")),
                                actions=_parse_json(row.get("actions_json")),
                                is_active=_parse_bool(row.get("rule_is_active"))
                            )
                            session.add(rule)
                            rules_loaded += 1
                            logger.debug(f"Created rule '{rule.name}' for policy: {policy_code}")

                    # --- POLICY ASSIGNMENT ---
                    action_pattern = (row.get("action_pattern") or "").strip()
                    if action_pattern:
                        scope_type = (row.get("assignment_scope_type") or "global").strip()
                        scope_id = _parse_optional_uuid(row.get("assignment_scope_id"))

                        # Check if assignment already exists
                        existing_assignment = session.query(PolicyAssignment).filter(
                            PolicyAssignment.policy_id == policy.policy_id,
                            PolicyAssignment.scope_type == scope_type,
                            PolicyAssignment.scope_id == scope_id,
                            PolicyAssignment.action_pattern == action_pattern
                        ).first()

                        if existing_assignment is None:
                            # Create new assignment
                            assignment = PolicyAssignment(
                                policy_id=policy.policy_id,
                                scope_type=scope_type,
                                scope_id=scope_id,
                                action_pattern=action_pattern,
                                priority_override=_parse_optional_int(row.get("assignment_priority_override")),
                                is_active=_parse_bool(row.get("assignment_is_active"))
                            )
                            session.add(assignment)
                            assignments_loaded += 1
                            logger.debug(f"Created assignment for policy: {policy_code}, action: {action_pattern}")

                    # --- POLICY ACTION TYPE ---
                    action_type_code = (row.get("action_type_code") or "").strip()
                    if action_type_code and action_type_code not in action_type_cache:
                        # Check if action type exists
                        action_type = session.query(PolicyActionType).filter(
                            PolicyActionType.code == action_type_code
                        ).first()

                        if action_type is None:
                            # Create new action type
                            action_type = PolicyActionType(
                                code=action_type_code,
                                name=(row.get("action_type_name") or action_type_code).strip(),
                                description=(row.get("action_type_description") or "").strip() or None,
                                category=(row.get("action_type_category") or "").strip() or None,
                                subject_schema=_parse_json(row.get("subject_schema_json")),
                                resource_schema=_parse_json(row.get("resource_schema_json")),
                                context_schema=_parse_json(row.get("context_schema_json")),
                                is_active=True
                            )
                            session.add(action_type)
                            action_types_loaded += 1
                            logger.debug(f"Created action type: {action_type_code}")

                        action_type_cache[action_type_code] = action_type

                except Exception as row_error:
                    logger.error(f"Row {row_num}: Error processing row - {row_error}")
                    continue

        # Commit all changes
        session.commit()

        logger.info(
            f"Policy loading complete. "
            f"Policies: {policies_loaded}, Versions: {versions_loaded}, "
            f"Rules: {rules_loaded}, Assignments: {assignments_loaded}, "
            f"Action Types: {action_types_loaded}"
        )

    except FileNotFoundError:
        logger.error(f"Policies CSV file not found: {csv_path}")
        raise
    except Exception as e:
        logger.error(f"Error loading policies: {e}")
        session.rollback()
        raise


def reload_policies(session: Session, csv_path: str = None):
    """
    Reload policies from CSV, updating existing records.
    This will update existing policies rather than skipping them.

    Args:
        session: SQLAlchemy database session
        csv_path: Path to the policies CSV file
    """
    if csv_path is None:
        csv_path = DEFAULT_CSV_PATH

    if not os.path.exists(csv_path):
        logger.warning(f"Policies CSV not found at {csv_path}. Skipping policy reload.")
        return

    logger.info(f"Reloading policies from {csv_path}")

    try:
        with open(csv_path, newline="", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)

            for row_num, row in enumerate(reader, start=2):
                try:
                    policy_code = (row.get("policy_code") or "").strip()
                    if not policy_code:
                        continue

                    # Find or create policy
                    policy = session.query(Policy).filter(
                        Policy.code == policy_code,
                        Policy.tenant_id.is_(None)
                    ).first()

                    if policy:
                        # Update existing policy
                        policy.name = (row.get("policy_name") or policy_code).strip()
                        policy.description = (row.get("policy_description") or "").strip() or None
                        policy.policy_type = (row.get("policy_type") or "access").strip()
                        policy.priority = _parse_optional_int(row.get("priority")) or 100
                        policy.is_active = _parse_bool(row.get("is_active"))
                        logger.debug(f"Updated policy: {policy_code}")
                    else:
                        # Create new policy
                        policy = Policy(
                            code=policy_code,
                            name=(row.get("policy_name") or policy_code).strip(),
                            description=(row.get("policy_description") or "").strip() or None,
                            policy_type=(row.get("policy_type") or "access").strip(),
                            priority=_parse_optional_int(row.get("priority")) or 100,
                            is_active=_parse_bool(row.get("is_active"))
                        )
                        session.add(policy)
                        session.flush()
                        logger.debug(f"Created policy: {policy_code}")

                except Exception as row_error:
                    logger.error(f"Row {row_num}: Error processing row - {row_error}")
                    continue

        session.commit()
        logger.info("Policy reload complete")

    except Exception as e:
        logger.error(f"Error reloading policies: {e}")
        session.rollback()
        raise


# Example usage for startup:
# from policy_engine.core.db_config import SessionLocal
# from policy_engine.core.helpers.load_policies import load_policies
#
# def init_policies():
#     with SessionLocal() as session:
#         load_policies(session)

