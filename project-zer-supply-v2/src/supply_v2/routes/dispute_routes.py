from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from supply_v2.auth import AuthContext
from supply_v2.dependencies import AppContainer
from supply_v2.policy import require_policy
from supply_v2.rbac import require_permission
from supply_v2.schemas import DisputeResolveIn
from supply_v2.serializers import dispute_dict


def build_dispute_router(container: AppContainer) -> APIRouter:
    router = APIRouter(tags=["disputes"])

    @router.get("/disputes/{dispute_id}")
    def get_dispute(
        dispute_id: str,
        auth: AuthContext = Depends(require_permission(container, "disputes.view")),
        _policy: AuthContext = Depends(require_policy(container, "read", "dispute")),
    ):
        container.reload()
        dispute = container.platform.store.disputes.get(dispute_id)
        if not dispute or dispute.tenant_id != auth.tenant_id:
            raise HTTPException(404, "dispute not found")
        return dispute_dict(dispute)

    @router.post("/disputes/{dispute_id}/resolve")
    def resolve_dispute(
        dispute_id: str,
        payload: DisputeResolveIn,
        auth: AuthContext = Depends(require_permission(container, "disputes.resolve")),
        _policy: AuthContext = Depends(require_policy(container, "resolve", "dispute")),
    ):
        with container.lock:
            container.reload()
            dispute = container.platform.store.disputes.get(dispute_id)
            if not dispute or dispute.tenant_id != auth.tenant_id:
                raise HTTPException(404, "dispute not found")
            if dispute.source == "vendor":
                result = container.platform.resolve_vendor_dispute(dispute_id, payload.resolution)
            else:
                result = container.platform.resolve_customer_dispute(dispute_id, payload.resolution)
            container.commit()
            return dispute_dict(result)

    return router
