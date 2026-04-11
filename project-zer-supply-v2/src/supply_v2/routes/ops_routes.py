from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from supply_v2.auth import AuthContext, require_internal_service
from supply_v2.db import BrokerMessageRow, DeadLetterRow, EventRow
from supply_v2.dependencies import AppContainer
from supply_v2.policy import require_policy
from supply_v2.rbac import PermissionRow, RoleRow, UserRoleRow, require_permission
from supply_v2.workers.outbox_worker import NotificationWorker
from supply_v2.workers.maintenance_worker import MaintenanceWorker


def build_ops_router(container: AppContainer) -> APIRouter:
    router = APIRouter(tags=["ops"])

    @router.post("/ops/run-notifications")
    def run_notifications(
        auth: AuthContext = Depends(require_permission(container, "ops.manage")),
        _policy: AuthContext = Depends(require_policy(container, "run", "ops")),
    ):
        if not container.persistent:
            raise HTTPException(400, "persistent backend required")
        worker = NotificationWorker(container.persistent.engine)
        processed = worker.process_pending_notifications()
        return {"processed": processed}

    @router.post("/ops/run-slas")
    def run_slas(
        auth: AuthContext = Depends(require_permission(container, "ops.manage")),
        _policy: AuthContext = Depends(require_policy(container, "run", "ops")),
    ):
        if not container.persistent:
            raise HTTPException(400, "persistent backend required")
        container.reload()
        processed = len(container.platform.evaluate_slas())
        container.commit()
        return {"processed": processed}

    @router.get("/ops/dead-letters")
    def list_dead_letters(
        auth: AuthContext = Depends(require_permission(container, "ops.manage")),
        _policy: AuthContext = Depends(require_policy(container, "read", "ops")),
    ):
        if not container.persistent:
            raise HTTPException(400, "persistent backend required")
        session = container.persistent.session_factory()
        try:
            rows = session.query(DeadLetterRow).order_by(DeadLetterRow.created_at.desc()).all()
            return {
                "items": [
                    {
                        "dead_letter_id": row.dead_letter_id,
                        "message_id": row.message_id,
                        "topic": row.topic,
                        "payload": json.loads(row.payload),
                        "reason": row.reason,
                        "created_at": row.created_at.isoformat(),
                    }
                    for row in rows
                ]
            }
        finally:
            session.close()

    @router.post("/ops/dead-letters/{dead_letter_id}/replay")
    def replay_dead_letter(
        dead_letter_id: str,
        auth: AuthContext = Depends(require_permission(container, "ops.manage")),
        _policy: AuthContext = Depends(require_policy(container, "replay", "ops")),
    ):
        if not container.persistent:
            raise HTTPException(400, "persistent backend required")
        session = container.persistent.session_factory()
        try:
            row = session.query(DeadLetterRow).filter(DeadLetterRow.dead_letter_id == dead_letter_id).first()
            if not row:
                raise HTTPException(404, "dead letter not found")
            session.add(
                BrokerMessageRow(
                    message_id=f"broker_{uuid4().hex}",
                    topic=row.topic,
                    payload=row.payload,
                    status="queued",
                    available_at=datetime.now(timezone.utc),
                    attempts=0,
                    created_at=datetime.now(timezone.utc),
                )
            )
            session.delete(row)
            session.commit()
            return {"status": "replayed"}
        finally:
            session.close()

    @router.get("/ops/audit-events")
    def list_audit_events(
        auth: AuthContext = Depends(require_permission(container, "ops.manage")),
        _policy: AuthContext = Depends(require_policy(container, "read", "ops")),
    ):
        if not container.persistent:
            raise HTTPException(400, "persistent backend required")
        session = container.persistent.session_factory()
        try:
            rows = session.query(EventRow).order_by(EventRow.id.desc()).limit(100).all()
            return {"items": [{"event_type": row.event_type, "entity_id": row.entity_id} for row in rows]}
        finally:
            session.close()

    @router.get("/ops/rbac/roles")
    def list_roles(
        auth: AuthContext = Depends(require_permission(container, "ops.manage")),
        _policy: AuthContext = Depends(require_policy(container, "read", "ops")),
    ):
        if not container.persistent:
            raise HTTPException(400, "persistent backend required")
        session = container.persistent.session_factory()
        try:
            rows = session.query(RoleRow).order_by(RoleRow.code).all()
            return {"items": [{"code": row.code, "description": row.description} for row in rows]}
        finally:
            session.close()

    @router.get("/ops/rbac/permissions")
    def list_permissions(
        auth: AuthContext = Depends(require_permission(container, "ops.manage")),
        _policy: AuthContext = Depends(require_policy(container, "read", "ops")),
    ):
        if not container.persistent:
            raise HTTPException(400, "persistent backend required")
        session = container.persistent.session_factory()
        try:
            rows = session.query(PermissionRow).order_by(PermissionRow.code).all()
            return {"items": [{"code": row.code, "description": row.description} for row in rows]}
        finally:
            session.close()

    @router.post("/ops/rbac/assign-role")
    def assign_role(
        payload: dict,
        auth: AuthContext = Depends(require_permission(container, "ops.manage")),
        _policy: AuthContext = Depends(require_policy(container, "update", "ops")),
    ):
        if not container.persistent:
            raise HTTPException(400, "persistent backend required")
        session = container.persistent.session_factory()
        try:
            role = session.query(RoleRow).filter(RoleRow.code == payload["role_code"]).first()
            if not role:
                raise HTTPException(404, "role not found")
            item = UserRoleRow(
                id=f"user_role_{datetime.now(timezone.utc).timestamp()}",
                tenant_id=payload["tenant_id"],
                user_id=payload["user_id"],
                role_code=payload["role_code"],
            )
            session.add(item)
            session.commit()
            return {"status": "assigned"}
        finally:
            session.close()

    @router.post("/internal/maintenance/run")
    def run_maintenance_internal(internal_ok: bool = Depends(require_internal_service)):
        if not internal_ok or not container.persistent:
            raise HTTPException(400, "persistent backend required")
        notification_worker = NotificationWorker(container.persistent.engine)
        notifications = notification_worker.process_pending_notifications()
        container.reload()
        slas = len(container.platform.evaluate_slas())
        container.commit()
        return {"notifications": notifications, "slas": slas}

    return router
