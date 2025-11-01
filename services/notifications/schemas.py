from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from datetime import datetime

# ---- Pydantic Models ----
class SendNotificationRequest(BaseModel):
    tenant_id: str
    user_id: Optional[str] = None
    channel: str = Field(..., description="Notification channel: email, sms, push")
    provider: Optional[str] = None  # Auto-select if not provided
    template_id: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)
    to: str = Field(..., description="Recipient address")
    subject: Optional[str] = None
    body: Optional[str] = None
    priority: str = Field(default="normal", description="Priority: low, normal, high")
    delay_until: Optional[datetime] = None

class ReplayRequest(BaseModel):
    delivery_id: str
    force: bool = Field(default=False, description="Force replay even if max retries reached")

class RailRequest(BaseModel):
    type: str = Field(default="notification")
    name: str = Field(..., description="Provider name (e.g., twilio, sendgrid)")
    config: Dict[str, Any] = Field(..., description="Provider configuration")
    active: bool = Field(default=True)

class NotificationResponse(BaseModel):
    delivery_id: str
    status: str
    provider: str
    channel: str
    created_at: datetime

class NotificationHistoryResponse(BaseModel):
    deliveries: List[Dict[str, Any]]
    count: int
    page: int
    limit: int