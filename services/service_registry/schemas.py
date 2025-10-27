# Pydantic models
from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel


class ServiceInfo(BaseModel):
    name: str
    port: int
    status: str
    version: str
    last_check: datetime
    response_time_ms: Optional[float] = None
    error: Optional[str] = None

class ServiceRegistryResponse(BaseModel):
    services: List[ServiceInfo]
    total_services: int
    healthy_services: int
    unhealthy_services: int
    last_updated: datetime