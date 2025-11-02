from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import json
from datetime import datetime
import os

EVENT_RETENTION_DAYS = int(os.getenv("EVENT_RETENTION_DAYS", "30"))
MAX_EVENTS_PER_REQUEST = int(os.getenv("MAX_EVENTS_PER_REQUEST", "100"))
# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class EventPublishRequest(BaseModel):
    tenant_id: str
    event_type: str
    event_data: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class EventRetryRequest(BaseModel):
    tenant_id: str
    max_events: int = Field(default=10, le=100)
    event_types: Optional[List[str]] = None

class EventHistoryRequest(BaseModel):
    tenant_id: str
    event_type: Optional[str] = None
    status: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    limit: int = Field(default=50, le=MAX_EVENTS_PER_REQUEST)
    offset: int = Field(default=0, ge=0)

class EventStatsRequest(BaseModel):
    tenant_id: str
    event_type: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None

class EventSubscriptionRequest(BaseModel):
    tenant_id: str
    service_name: str
    event_type: str
    queue_name: str

class EventPublishResponse(BaseModel):
    event_id: str
    status: str
    message: str

class EventHistoryResponse(BaseModel):
    events: List[Dict[str, Any]]
    total_count: int
    has_more: bool

class EventStatsResponse(BaseModel):
    stats: Dict[str, Any]
    period: str