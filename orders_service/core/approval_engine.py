from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from orders_service.Models import (
    ApprovalPolicy,
    ApprovalStage,
    ApprovalTask,
    ApprovalWorkflow,
    OrgUnit,
    PurchaseRequest,
    Role,
    UserBudgetLimit,
    UserOrgAssignment,
    UserRole,
)
from orders_service.core.budget_engine import commit_approver_limits, commit_cc_budget


def check_sox_sod(requester_id: uuid.UUID, approver_id: uuid.UUID, sox_enforced: bool = True) -> None:
    if sox_enforced and str(requester_id) == str(approver_id):
        raise ValueError(
            "SOX Segregation-of-Duties violation: the requester cannot approve their own request."
        )


def evaluate_stage_conditions(stage: ApprovalStage, request: PurchaseRequest) -> bool:
    conditions = stage.conditions
    if not conditions:
        return True

    results = []
    for cond in conditions:
        match = _eval_condition(cond, request)
        results.append((match, cond.logic))

    combined = results[0][0]
    for match, logic in results[1:]:
        combined = (combined and match) if logic == "AND" else (combined or match)
    return combined


def _eval_condition(cond, request: PurchaseRequest) -> bool:
    field = cond.field
    op = cond.operator
    value = cond.value

    if field == "amount":
        actual = request.amount_minor
        v = int(value) if not isinstance(value, (list, dict)) else value
        if op == "gte":
            return actual >= v
        if op == "lte":
            return actual <= v
        if op == "eq":
            return actual == v
    elif field == "cost_centre":
        actual = str(request.cost_centre_id) if request.cost_centre_id else None
        if op == "eq":
            return actual == str(value)
        if op == "in":
            return actual in [str(v) for v in (value if isinstance(value, list) else [value])]
    elif field == "category":
        actual = str(request.category_id) if request.category_id else None
        if op == "eq":
            return actual == str(value)
        if op == "in":
            return actual in [str(v) for v in (value if isinstance(value, list) else [value])]
    elif field == "vendor":
        actual = str(request.vendor_id) if request.vendor_id else None
        if op == "eq":
            return actual == str(value)
        if op == "in":
            return actual in [str(v) for v in (value if isinstance(value, list) else [value])]
    return False


def _resolve_approvers_for_stage(
    db: Session, stage: ApprovalStage, request: PurchaseRequest, policy: ApprovalPolicy
) -> List[uuid.UUID]:
    approver_ids: List[uuid.UUID] = []

    for spec in stage.approvers:
        if spec.approver_type == "user" and spec.approver_user_id:
            approver_ids.append(spec.approver_user_id)
        elif spec.approver_type == "org_unit_manager":
            assignment = (
                db.query(UserOrgAssignment).filter(UserOrgAssignment.user_id == request.requester_id).first()
            )
            if assignment:
                org_unit = db.query(OrgUnit).filter(OrgUnit.org_unit_id == assignment.org_unit_id).first()
                if org_unit and org_unit.manager_user_id:
                    approver_ids.append(org_unit.manager_user_id)
        elif spec.approver_type == "hierarchy_traversal":
            approver_ids.extend(_traverse_hierarchy(db, request.requester_id, request.amount_minor))
        elif spec.approver_type == "role":
            role_users = (
                db.query(UserRole.user_id)
                .join(Role, UserRole.role_id == Role.role_id)
                .filter(
                    Role.code == spec.role_code,
                    UserRole.tenant_id == request.tenant_id,
                )
                .all()
            )
            approver_ids.extend([uid for (uid,) in role_users])

    if policy.sox_sod_enforced:
        approver_ids = [aid for aid in approver_ids if str(aid) != str(request.requester_id)]

    seen = set()
    unique_ids = []
    for aid in approver_ids:
        k = str(aid)
        if k not in seen:
            seen.add(k)
            unique_ids.append(aid)

    if policy.routing_mode == "broadcast":
        unique_ids = unique_ids[: policy.broadcast_n]
    return unique_ids


def _traverse_hierarchy(db: Session, requester_id: uuid.UUID, amount_minor: int) -> List[uuid.UUID]:
    assignment = db.query(UserOrgAssignment).filter(UserOrgAssignment.user_id == requester_id).first()
    if not assignment:
        return []

    visited = set()
    org_unit = db.query(OrgUnit).filter(OrgUnit.org_unit_id == assignment.org_unit_id).first()

    results: List[uuid.UUID] = []
    while org_unit and org_unit.org_unit_id not in visited:
        visited.add(org_unit.org_unit_id)
        if org_unit.manager_user_id and str(org_unit.manager_user_id) != str(requester_id):
            if _has_sufficient_approver_limit(db, org_unit.manager_user_id, amount_minor):
                results.append(org_unit.manager_user_id)
                break
        if org_unit.parent_org_unit_id:
            org_unit = db.query(OrgUnit).filter(OrgUnit.org_unit_id == org_unit.parent_org_unit_id).first()
        else:
            break

    return results


def _has_sufficient_approver_limit(db: Session, user_id: uuid.UUID, amount_minor: int) -> bool:
    today = date.today()
    limits = (
        db.query(UserBudgetLimit)
        .filter(
            UserBudgetLimit.user_id == user_id,
            UserBudgetLimit.limit_type == "approver",
            UserBudgetLimit.is_active.is_(True),
        )
        .all()
    )
    if not limits:
        return False
    for lim in limits:
        if lim.window_start and lim.window_end and not (lim.window_start <= today <= lim.window_end):
            continue
        carry = lim.carry_forward_minor if lim.carry_forward_enabled else 0
        available = lim.limit_amount_minor + carry - lim.committed_minor - lim.spent_minor
        if available >= amount_minor:
            return True
    return False


def resolve_workflow(db: Session, request: PurchaseRequest, policy: ApprovalPolicy) -> ApprovalWorkflow:
    now = datetime.now(timezone.utc)
    workflow = ApprovalWorkflow(
        workflow_id=uuid.uuid4(),
        request_id=request.request_id,
        policy_id=policy.policy_id,
        tenant_id=request.tenant_id,
        current_stage_order=1,
        status="active",
    )
    db.add(workflow)
    db.flush()

    stage1 = (
        db.query(ApprovalStage)
        .filter(ApprovalStage.policy_id == policy.policy_id, ApprovalStage.stage_order == 1)
        .first()
    )
    if stage1 and evaluate_stage_conditions(stage1, request):
        approver_ids = _resolve_approvers_for_stage(db, stage1, request, policy)
        _create_tasks(db, workflow, stage1, approver_ids)
    else:
        workflow.status = "completed"
        request.status = "approved"
        request.approved_at = now

    db.flush()
    return workflow


def _create_tasks(db: Session, workflow: ApprovalWorkflow, stage: ApprovalStage, approver_ids: List[uuid.UUID]) -> None:
    for uid in approver_ids:
        db.add(
            ApprovalTask(
                task_id=uuid.uuid4(),
                workflow_id=workflow.workflow_id,
                stage_id=stage.stage_id,
                tenant_id=workflow.tenant_id,
                assignee_user_id=uid,
                stage_order=stage.stage_order,
                status="pending",
            )
        )


def advance_workflow(
    db: Session,
    *,
    task_id: uuid.UUID,
    decision: str,
    decided_by_id: uuid.UUID,
    note: Optional[str] = None,
) -> dict:
    now = datetime.now(timezone.utc)
    task = db.query(ApprovalTask).filter(ApprovalTask.task_id == task_id).first()
    if not task:
        raise ValueError(f"Approval task {task_id} not found")
    if task.status != "pending":
        raise ValueError(f"Task {task_id} is already in state '{task.status}'")

    workflow = db.query(ApprovalWorkflow).filter(ApprovalWorkflow.workflow_id == task.workflow_id).first()
    request = db.query(PurchaseRequest).filter(PurchaseRequest.request_id == workflow.request_id).first()
    policy = db.query(ApprovalPolicy).filter(ApprovalPolicy.policy_id == workflow.policy_id).first()

    if policy and policy.sox_sod_enforced:
        check_sox_sod(request.requester_id, decided_by_id, sox_enforced=True)

    task.status = decision if decision in ("approved", "rejected", "escalated") else "approved"
    task.decided_at = now
    task.decided_by = decided_by_id
    task.note = note

    if decision == "reject":
        task.status = "rejected"
        workflow.status = "rejected"
        request.status = "rejected"
        request.rejection_reason = note
        db.flush()
        return {"status": "rejected", "message": "Request rejected"}

    if decision == "escalate":
        new_approver_ids = _traverse_hierarchy(db, request.requester_id, request.amount_minor)
        existing_assignees = {str(t.assignee_user_id) for t in workflow.tasks if t.status not in ("escalated",)}
        new_approver_ids = [aid for aid in new_approver_ids if str(aid) not in existing_assignees]

        if not new_approver_ids:
            workflow.status = "escalated"
            request.status = "pending_approval"
            db.flush()
            return {"status": "escalated", "message": "No eligible escalation target found; workflow paused"}

        stage = db.query(ApprovalStage).filter(ApprovalStage.stage_id == task.stage_id).first()
        _create_tasks(db, workflow, stage, new_approver_ids[:1])
        db.flush()
        return {"status": "escalated", "message": f"Escalated to {new_approver_ids[0]}"}

    stage = db.query(ApprovalStage).filter(ApprovalStage.stage_id == task.stage_id).first()
    approved_count = sum(
        1 for t in workflow.tasks if str(t.stage_id) == str(task.stage_id) and t.status == "approved"
    )
    min_needed = stage.min_approvers if stage else 1
    stage_complete = approved_count >= min_needed

    if stage_complete:
        commit_approver_limits(
            db,
            approver_id=decided_by_id,
            cost_centre_id=request.cost_centre_id,
            amount_minor=request.amount_minor,
        )
        next_stage = _find_next_applicable_stage(db, workflow, policy, request)
        if next_stage:
            workflow.current_stage_order = next_stage.stage_order
            approver_ids = _resolve_approvers_for_stage(db, next_stage, request, policy)
            _create_tasks(db, workflow, next_stage, approver_ids)
            _cancel_other_pending_tasks(workflow, task.stage_id, task.task_id)
            db.flush()
            return {
                "status": "stage_advanced",
                "next_stage": next_stage.stage_order,
                "message": f"Advanced to stage {next_stage.stage_order}",
            }

        workflow.status = "completed"
        request.status = "approved"
        request.approved_by = decided_by_id
        request.approved_at = now
        _cancel_other_pending_tasks(workflow, task.stage_id, task.task_id)
        commit_cc_budget(
            db,
            cost_centre_id=request.cost_centre_id,
            year_id=request.year_id,
            period_id=request.period_id,
            amount_minor=request.amount_minor,
        )
        db.flush()
        return {"status": "approved", "message": "Request fully approved; PO ready to issue"}

    db.flush()
    return {"status": "approved", "message": f"Approval recorded ({approved_count}/{min_needed} needed)"}


def _find_next_applicable_stage(
    db: Session, workflow: ApprovalWorkflow, policy: ApprovalPolicy, request: PurchaseRequest
) -> Optional[ApprovalStage]:
    stages = (
        db.query(ApprovalStage)
        .filter(ApprovalStage.policy_id == policy.policy_id, ApprovalStage.stage_order > workflow.current_stage_order)
        .order_by(ApprovalStage.stage_order)
        .all()
    )
    for stage in stages:
        if evaluate_stage_conditions(stage, request):
            return stage
    return None


def _cancel_other_pending_tasks(workflow: ApprovalWorkflow, stage_id, approved_task_id) -> None:
    now = datetime.now(timezone.utc)
    for t in workflow.tasks:
        if str(t.stage_id) == str(stage_id) and str(t.task_id) != str(approved_task_id) and t.status == "pending":
            t.status = "cancelled"
            t.decided_at = now

