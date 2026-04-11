from fastapi import APIRouter, Depends, HTTPException

from procurement_service.Models import BrokerMessage
from procurement_service.core.notification_dispatcher import dispatch_queued_notifications
from procurement_service.core.policy_client import require_policy
from procurement_service.core.runtime import get_container
from procurement_service.core.user_auth import (
    assign_user_role,
    check_user_authorization,
    list_permissions as list_known_permissions,
    list_roles as list_known_roles,
    require_internal_service,
)


router = APIRouter(tags=["ops"])


@router.post("/ops/run-notifications")
async def run_notifications(
    ctx=Depends(check_user_authorization("ops.manage")),
    policy=Depends(require_policy("ops.run")),
):
    container = get_container()
    with container.lock:
        processed = dispatch_queued_notifications(container)
    return {"processed": processed}


@router.post("/ops/run-slas")
async def run_slas(
    ctx=Depends(check_user_authorization("ops.manage")),
    policy=Depends(require_policy("ops.run")),
):
    container = get_container()
    processed = len(container.platform.evaluate_slas())
    return {"processed": processed}


@router.get("/ops/dead-letters")
async def list_dead_letters(
    ctx=Depends(check_user_authorization("ops.manage")),
    policy=Depends(require_policy("ops.read")),
):
    container = get_container()
    with container.lock:
        items = [
            {
                "dead_letter_id": item.dead_letter_id,
                "message_id": item.message_id,
                "topic": item.topic,
                "payload": item.payload,
                "reason": item.reason,
                "created_at": item.created_at.isoformat(),
            }
            for item in sorted(container.platform.store.dead_letters.values(), key=lambda x: x.created_at, reverse=True)
        ]
    return {"items": items}


@router.post("/ops/dead-letters/{dead_letter_id}/replay")
async def replay_dead_letter(
    dead_letter_id: str,
    ctx=Depends(check_user_authorization("ops.manage")),
    policy=Depends(require_policy("ops.replay")),
):
    container = get_container()
    with container.lock:
        dead_letter = container.platform.store.dead_letters.get(dead_letter_id)
        if not dead_letter:
            raise HTTPException(404, "dead letter not found")

        message = BrokerMessage(
            message_id=container.platform.id_gen("broker"),
            topic=dead_letter.topic,
            payload=dead_letter.payload,
            status="queued",
        )
        container.platform.store.broker_messages[message.message_id] = message

        notification_id = dead_letter.payload.get("notification_id") if isinstance(dead_letter.payload, dict) else None
        if notification_id and notification_id in container.platform.store.notifications:
            container.platform.store.notifications[notification_id].status = "queued"

        del container.platform.store.dead_letters[dead_letter_id]
        container.platform.store.emit("dead_letter.replayed", dead_letter_id)

    return {"status": "replayed", "dead_letter_id": dead_letter_id}


@router.get("/ops/audit-events")
async def list_audit_events(
    ctx=Depends(check_user_authorization("ops.manage")),
    policy=Depends(require_policy("ops.read")),
):
    container = get_container()
    return {"items": container.platform.store.events[-100:]}


@router.get("/ops/audit/three-way-match/{invoice_id}")
async def three_way_match_invoice(
    invoice_id: str,
    ctx=Depends(check_user_authorization("ops.manage")),
    policy=Depends(require_policy("audit.read")),
):
    container = get_container()
    invoice = container.platform.store.invoices.get(invoice_id)
    if not invoice or invoice.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "invoice not found")
    return container.platform.three_way_match_report(invoice_id)


@router.get("/ops/audit/three-way-match")
async def list_three_way_matches(
    status: str | None = None,
    ctx=Depends(check_user_authorization("ops.manage")),
    policy=Depends(require_policy("audit.read")),
):
    container = get_container()
    items = []
    for invoice in container.platform.store.invoices.values():
        if invoice.tenant_id != ctx.tenant_id:
            continue
        report = container.platform.three_way_match_report(invoice.invoice_id)
        if status and report["overall_status"] != status:
            continue
        items.append(report)
    return {"items": items}


@router.get("/ops/rbac/roles")
async def list_roles(
    ctx=Depends(check_user_authorization("ops.manage")),
    policy=Depends(require_policy("ops.read")),
):
    return {"items": list_known_roles()}


@router.get("/ops/rbac/permissions")
async def list_permissions(
    ctx=Depends(check_user_authorization("ops.manage")),
    policy=Depends(require_policy("ops.read")),
):
    return {"items": list_known_permissions()}


@router.post("/ops/rbac/assign-role")
async def assign_role(
    payload: dict,
    ctx=Depends(check_user_authorization("ops.manage")),
    policy=Depends(require_policy("ops.update")),
):
    tenant_id = payload.get("tenant_id")
    user_id = payload.get("user_id")
    role_code = payload.get("role_code")
    if not tenant_id or not user_id or not role_code:
        raise HTTPException(400, "tenant_id, user_id, and role_code are required")
    try:
        assign_user_role(tenant_id=tenant_id, user_id=user_id, role_code=role_code)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"status": "assigned", "tenant_id": tenant_id, "user_id": user_id, "role_code": role_code}


@router.post("/internal/maintenance/run")
async def run_maintenance_internal(internal_ok: bool = Depends(require_internal_service)):
    if not internal_ok:
        raise HTTPException(401, "unauthorized")
    container = get_container()
    with container.lock:
        notifications = dispatch_queued_notifications(container)
    slas = len(container.platform.evaluate_slas())
    return {"notifications": notifications, "slas": slas}
