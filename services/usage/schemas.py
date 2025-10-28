# Payloads
from typing import Optional, Dict

from pydantic import BaseModel


class UsageEventRequest(BaseModel):
    tenant_id: str
    user_id: Optional[str] = None
    meter_code: str
    quantity: int = 1
    metadata: Optional[Dict] = None