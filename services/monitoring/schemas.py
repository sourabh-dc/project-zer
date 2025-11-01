from typing import Dict, Any, Optional
from pydantic import BaseModel
from datetime import datetime
# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class HealthCheckRequest(BaseModel):
    service_name: str
    endpoint: str
    timeout_seconds: int = 30
    expected_status: int = 200

class AlertRequest(BaseModel):
    service_name: str
    alert_type: str
    severity: str
    message: str
    metadata: Optional[Dict[str, Any]] = None

class ServiceStatus(BaseModel):
    service_name: str
    status: str
    response_time_ms: Optional[int] = None
    last_check: datetime
    error_message: Optional[str] = None