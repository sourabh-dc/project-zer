from __future__ import annotations

from fastapi import Depends, HTTPException
from starlette import status

from procurement_service.core.config import SETTINGS
from procurement_service.core.user_auth import UserContext, get_user_context


def require_policy(action: str):
    def dependency(ctx: UserContext = Depends(get_user_context)) -> dict:
        if SETTINGS.POLICY_MODE == "disabled":
            return {"decision": "allow", "action": action}

        # Local lightweight policy: tenant and role checks are already handled in RBAC.
        if not ctx.tenant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="policy denied: tenant missing")

        return {"decision": "allow", "action": action}

    return dependency
