from pydantic import BaseModel
from typing import Optional
from datetime import datetime
# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class IssueCodeRequest(BaseModel):
    tenant_id: str
    user_id: str
    ttl_minutes: int = 60
    provider: str = "internal"

class ValidateCodeRequest(BaseModel):
    code: str
    provider: str = "internal"

class EntryCodeResponse(BaseModel):
    code: str
    code_id: str
    tenant_id: str
    user_id: str
    expires_at: datetime
    ttl_minutes: int

class ValidationResponse(BaseModel):
    valid: bool
    reason: Optional[str] = None
    code: str
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None