# packages/zeroque_common/zeroque_common/observability/insights.py
"""
Application Insights and monitoring for ZeroQue services
"""
import time
import json
import asyncio
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
import logging
import psutil
import os

from .metrics import get_metrics, MetricPoint
from .logging import ZeroQueLogger

log = logging.getLogger("insights")

@dataclass
class HealthCheck:
    """Health check result"""
    name: str
    status: str  # "healthy", "unhealthy", "degraded"
    message: str
    timestamp: datetime
    details: Dict[str, Any] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details or {}
        }

@dataclass
class ServiceInsight:
    """Service insight data"""
    service_name: str
    timestamp: datetime
    health_status: str
    performance_metrics: Dict[str, float]
    business_metrics: Dict[str, float]
    error_rate: float
    uptime_seconds: float
    version: str
    environment: str

class ApplicationInsights:
    """Application insights collector for ZeroQue services"""
    
    def __init__(self, service_name: str, version: str = "1.0.0"):
        self.service_name = service_name
        self.version = version
        self.environment = os.getenv("ENVIRONMENT", "development")
        self.start_time = time.time()
        self.logger = ZeroQueLogger(f"insights.{service_name}", service_name, version)
        
        # Health checks
        self.health_checks: List[HealthCheck] = []
        
        # Performance tracking
        self.performance_data = {
            "request_count": 0,
            "error_count": 0,
            "avg_response_time": 0.0,
            "p95_response_time": 0.0,
            "p99_response_time": 0.0
        }
        
        # Business metrics
        self.business_metrics = {
            "orders_created": 0,
            "orders_completed": 0,
            "users_active": 0,
            "revenue_total": 0.0,
            "inventory_items": 0
        }
        
        # Error tracking
        self.error_counts = {}
        self.recent_errors = []
        
        # Start background collection
        self._start_background_collection()
    
    def _start_background_collection(self):
        """Start background data collection"""
        # Don't start background collection immediately - wait for event loop
        pass
    
    def start_background_collection_async(self):
        """Start background collection when event loop is available"""
        async def collect_insights():
            while True:
                try:
                    await self._collect_performance_data()
                    await self._collect_business_metrics()
                    await self._run_health_checks()
                    await asyncio.sleep(60)  # Collect every minute
                except Exception as e:
                    self.logger.error("Error in background insights collection: %s", str(e))
                    await asyncio.sleep(60)
        
        return asyncio.create_task(collect_insights())
    
    async def _collect_performance_data(self):
        """Collect performance metrics"""
        try:
            metrics = get_metrics()
            all_metrics = metrics.get_all_metrics()
            
            # Extract performance metrics
            for metric in all_metrics:
                if "http_request_duration" in metric.name:
                    self.performance_data["avg_response_time"] = metric.value
                elif "http_requests_total" in metric.name:
                    self.performance_data["request_count"] = int(metric.value)
                elif "system_cpu_percent" in metric.name:
                    self.performance_data["cpu_usage"] = metric.value
                elif "system_memory_percent" in metric.name:
                    self.performance_data["memory_usage"] = metric.value
        except Exception as e:
            self.logger.error("Error collecting performance data: %s", str(e))
    
    async def _collect_business_metrics(self):
        """Collect business metrics from events and database"""
        try:
            # This would typically query the database or event stream
            # For now, we'll use placeholder data
            pass
        except Exception as e:
            self.logger.error("Error collecting business metrics: %s", str(e))
    
    async def _run_health_checks(self):
        """Run health checks"""
        self.health_checks = []
        
        # Database health check
        await self._check_database_health()
        
        # Redis health check
        await self._check_redis_health()
        
        # External service health checks
        await self._check_external_services()
        
        # System resource health checks
        await self._check_system_resources()
    
    async def _check_database_health(self):
        """Check database connectivity"""
        try:
            from zeroque_common.db.session import SessionLocal
            with SessionLocal() as db:
                db.execute("SELECT 1")
            
            self.health_checks.append(HealthCheck(
                name="database",
                status="healthy",
                message="Database connection successful",
                timestamp=datetime.now(timezone.utc)
            ))
        except Exception as e:
            self.health_checks.append(HealthCheck(
                name="database",
                status="unhealthy",
                message=f"Database connection failed: {str(e)}",
                timestamp=datetime.now(timezone.utc),
                details={"error": str(e)}
            ))
    
    async def _check_redis_health(self):
        """Check Redis connectivity"""
        try:
            import redis
            redis_url = os.getenv("REDIS_URL", "redis://localhost:4000/0")
            client = redis.from_url(redis_url)
            client.ping()
            
            self.health_checks.append(HealthCheck(
                name="redis",
                status="healthy",
                message="Redis connection successful",
                timestamp=datetime.now(timezone.utc)
            ))
        except Exception as e:
            self.health_checks.append(HealthCheck(
                name="redis",
                status="unhealthy",
                message=f"Redis connection failed: {str(e)}",
                timestamp=datetime.now(timezone.utc),
                details={"error": str(e)}
            ))
    
    async def _check_external_services(self):
        """Check external service dependencies"""
        # This would check services like Stripe, external APIs, etc.
        pass
    
    async def _check_system_resources(self):
        """Check system resource usage"""
        try:
            cpu_percent = psutil.cpu_percent()
            memory_percent = psutil.virtual_memory().percent
            disk_percent = psutil.disk_usage('/').percent
            
            # Determine health based on thresholds
            if cpu_percent > 90 or memory_percent > 90 or disk_percent > 90:
                status = "unhealthy"
                message = "High resource usage detected"
            elif cpu_percent > 70 or memory_percent > 70 or disk_percent > 70:
                status = "degraded"
                message = "Elevated resource usage"
            else:
                status = "healthy"
                message = "Resource usage normal"
            
            self.health_checks.append(HealthCheck(
                name="system_resources",
                status=status,
                message=message,
                timestamp=datetime.now(timezone.utc),
                details={
                    "cpu_percent": cpu_percent,
                    "memory_percent": memory_percent,
                    "disk_percent": disk_percent
                }
            ))
        except Exception as e:
            self.health_checks.append(HealthCheck(
                name="system_resources",
                status="unhealthy",
                message=f"System resource check failed: {str(e)}",
                timestamp=datetime.now(timezone.utc),
                details={"error": str(e)}
            ))
    
    def record_business_event(self, event_type: str, value: float = 1.0, **kwargs):
        """Record a business event"""
        if event_type in self.business_metrics:
            self.business_metrics[event_type] += value
        
        self.logger.business_event(event_type, f"Business event recorded: {event_type}", 
                                 value=value, **kwargs)
    
    def record_error(self, error_type: str, error_message: str, **kwargs):
        """Record an error occurrence"""
        if error_type not in self.error_counts:
            self.error_counts[error_type] = 0
        self.error_counts[error_type] += 1
        
        # Track recent errors (keep last 100)
        self.recent_errors.append({
            "type": error_type,
            "message": error_message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "context": kwargs
        })
        
        if len(self.recent_errors) > 100:
            self.recent_errors = self.recent_errors[-100:]
        
        self.logger.error(f"Error recorded: {error_type}", 
                        error_type=error_type, error_message=error_message, **kwargs)
    
    def get_insights(self) -> ServiceInsight:
        """Get current service insights"""
        uptime = time.time() - self.start_time
        
        # Calculate error rate
        total_requests = self.performance_data.get("request_count", 0)
        total_errors = sum(self.error_counts.values())
        error_rate = (total_errors / total_requests * 100) if total_requests > 0 else 0
        
        # Determine overall health status
        unhealthy_checks = [h for h in self.health_checks if h.status == "unhealthy"]
        degraded_checks = [h for h in self.health_checks if h.status == "degraded"]
        
        if unhealthy_checks:
            health_status = "unhealthy"
        elif degraded_checks:
            health_status = "degraded"
        else:
            health_status = "healthy"
        
        return ServiceInsight(
            service_name=self.service_name,
            timestamp=datetime.now(timezone.utc),
            health_status=health_status,
            performance_metrics=self.performance_data.copy(),
            business_metrics=self.business_metrics.copy(),
            error_rate=error_rate,
            uptime_seconds=uptime,
            version=self.version,
            environment=self.environment
        )
    
    def get_health_summary(self) -> Dict[str, Any]:
        """Get health check summary"""
        return {
            "service": self.service_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "overall_status": self.get_insights().health_status,
            "checks": [check.to_dict() for check in self.health_checks],
            "error_counts": self.error_counts,
            "recent_errors": self.recent_errors[-10:]  # Last 10 errors
        }
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Get performance summary"""
        insights = self.get_insights()
        
        return {
            "service": self.service_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "uptime_seconds": insights.uptime_seconds,
            "performance_metrics": insights.performance_metrics,
            "business_metrics": insights.business_metrics,
            "error_rate_percent": insights.error_rate
        }

# Global insights instance
_insights: Optional[ApplicationInsights] = None

def init_insights(service_name: str, version: str = "1.0.0") -> ApplicationInsights:
    """Initialize application insights"""
    global _insights
    _insights = ApplicationInsights(service_name, version)
    return _insights

def get_insights() -> ApplicationInsights:
    """Get the global insights instance"""
    if _insights is None:
        raise RuntimeError("Insights not initialized. Call init_insights() first.")
    return _insights
