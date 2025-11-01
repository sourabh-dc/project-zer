from typing import Optional, Dict, Any
from pydantic import BaseModel
from datetime import datetime
# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class MetricRequest(BaseModel):
    metric_name: str
    metric_type: str
    value: float
    labels: Optional[Dict[str, str]] = None
    tenant_id: Optional[str] = None
    service_name: Optional[str] = None

class MonitorRequest(BaseModel):
    monitor_name: str
    monitor_type: str
    target_service: str
    target_endpoint: str
    check_interval_seconds: int = 60
    timeout_seconds: int = 30
    threshold_value: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None

class SystemMetrics(BaseModel):
    cpu_usage_percent: float
    memory_usage_percent: float
    disk_usage_percent: float
    network_bytes_sent: int
    network_bytes_received: int
    timestamp: datetime