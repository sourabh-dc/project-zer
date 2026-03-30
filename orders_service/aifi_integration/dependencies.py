"""FastAPI dependency helpers for AiFi endpoint controllers.

Usage in route handlers:
    @router.get("/...")
    async def my_endpoint(token: str = Depends(require_customer_token)):
        result = await some_aifi_function(token=token)
        ...
"""
from __future__ import annotations

from fastapi import Header, HTTPException
from typing import Optional


async def require_customer_token(
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> str:
    """Extract and validate a Bearer token from the Authorization header.

    Used by Customer App API endpoints where the end-user's own AiFi token
    must be forwarded to AiFi on their behalf.

    Raises 401 if the header is absent or malformed.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header is required")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=401,
            detail="Authorization header must be in the form 'Bearer <token>'",
        )
    return token.strip()
