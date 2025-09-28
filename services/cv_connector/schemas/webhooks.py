from pydantic import BaseModel
from typing import Optional

class EntryWebhookDecision(BaseModel):
    status: str                   # 'OK' or 'FAILED'
    reason: Optional[str] = None
    sessionId: Optional[str] = None
    customerId: Optional[int] = None
    role: Optional[str] = None    # 'employee' | 'customer'

class SimpleOK(BaseModel):
    ok: bool = True