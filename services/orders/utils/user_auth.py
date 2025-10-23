import os
from typing import Optional

from fastapi import HTTPException


def get_user_context(authorization: Optional[str] = None, x_api_key: Optional[str] = None):
    """Get user context for authentication"""
    # Demo mode for development
    if os.getenv("ALLOW_DEMO", "false").lower() == "true":
        return {
            "tenant_id": "550e8400-e29b-41d4-a716-446655440000",  # Valid UUID
            "user_id": "550e8400-e29b-41d4-a716-446655440004",  # Valid UUID
            "roles": ["admin"]
        }

    # TODO: Implement proper JWT/API key validation
    raise HTTPException(status_code=401, detail="Authentication required")