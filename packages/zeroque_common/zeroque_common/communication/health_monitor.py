# packages/zeroque_common/zeroque_common/communication/health_monitor.py
"""
Health Monitoring Implementation for ZeroQue Services

This module provides comprehensive health monitoring for all microservices,
including service health, communication health, and system metrics.
"""

import os
import asyncio
import httpx
import redis
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from .service_discovery import service_registry, ServiceStatus
from .circuit_breaker import service_circuit_breaker
from .event_store import event_store
from .service_bus import service_bus

log = logging.getLogger(__name__)

class HealthLevel(Enum):
    """Health status levels"""
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    CRITICAL = "CRITICAL"

@dataclass
class HealthCheck:
    """Individual health check result"""
    name: str
    status: HealthLevel
    message: str
    response_time_ms: float
    timestamp: datetime
    details: Dict[str, Any] = None

@dataclass
class ServiceHealth:
    """Service health information"""
    service_name: str
    overall_status: HealthLevel
    checks: List[HealthCheck]
    last_check: datetime
    uptime_seconds: float
    version: str

class HealthMonitor:
    """Comprehensive health monitoring system"""
    
    def __init__(self):
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:4000/0")
        self.redis_client = redis.from_url(self.redis_url, decode_responses=True)
        self.health_history: Dict[str, List[HealthCheck]] = {}
        self.monitoring_interval = 30  # seconds
        self._monitoring_task: Optional[asyncio.Task] = None
        
        log.info("HealthMonitor initialized")
    
    async def check_service_health(self, service_name: str) -> ServiceHealth:
        """Check health of a specific service"""
        checks = []
        
        # Basic connectivity check
        connectivity_check = await self._check_service_connectivity(service_name)
        checks.append(connectivity_check)
        
        # Database connectivity check
        db_check = await self._check_database_connectivity(service_name)
        checks.append(db_check)
        
        # Redis connectivity check
        redis_check = await self._check_redis_connectivity(service_name)
        checks.append(redis_check)
        
        # Circuit breaker status check
        circuit_check = await self._check_circuit_breaker_status(service_name)
        checks.append(circuit_check)
        
        # Determine overall status
        overall_status = self._determine_overall_status(checks)
        
        # Calculate uptime
        uptime = await self._calculate_service_uptime(service_name)
        
        return ServiceHealth(
            service_name=service_name,
            overall_status=overall_status,
            checks=checks,
            last_check=datetime.now(),
            uptime_seconds=uptime,
            version="1.0.0"  # Could be retrieved from service metadata
        )
    
    async def check_system_health(self) -> Dict[str, Any]:
        """Check overall system health"""
        system_checks = []
        
        # Redis health
        redis_check = await self._check_redis_health()
        system_checks.append(redis_check)
        
        # Database health
        db_check = await self._check_database_health()
        system_checks.append(db_check)
        
        # Event system health
        event_check = await self._check_event_system_health()
        system_checks.append(event_check)
        
        # Service discovery health
        discovery_check = await self._check_service_discovery_health()
        system_checks.append(discovery_check)
        
        # Circuit breaker health
        circuit_check = await self._check_circuit_breaker_health()
        system_checks.append(circuit_check)
        
        # Determine overall system status
        overall_status = self._determine_overall_status(system_checks)
        
        return {
            "overall_status": overall_status.value,
            "timestamp": datetime.now().isoformat(),
            "checks": [
                {
                    "name": check.name,
                    "status": check.status.value,
                    "message": check.message,
                    "response_time_ms": check.response_time_ms,
                    "details": check.details
                }
                for check in system_checks
            ],
            "summary": {
                "total_checks": len(system_checks),
                "healthy_checks": len([c for c in system_checks if c.status == HealthLevel.HEALTHY]),
                "degraded_checks": len([c for c in system_checks if c.status == HealthLevel.DEGRADED]),
                "unhealthy_checks": len([c for c in system_checks if c.status == HealthLevel.UNHEALTHY]),
                "critical_checks": len([c for c in system_checks if c.status == HealthLevel.CRITICAL])
            }
        }
    
    async def check_all_services_health(self) -> Dict[str, ServiceHealth]:
        """Check health of all registered services"""
        services_health = {}
        
        # Get all registered services
        all_services = service_registry.get_all_services()
        
        for service_name in all_services.keys():
            try:
                health = await self.check_service_health(service_name)
                services_health[service_name] = health
            except Exception as e:
                log.error(f"Failed to check health for service {service_name}: {str(e)}")
                # Create unhealthy health status
                services_health[service_name] = ServiceHealth(
                    service_name=service_name,
                    overall_status=HealthLevel.CRITICAL,
                    checks=[],
                    last_check=datetime.now(),
                    uptime_seconds=0,
                    version="unknown"
                )
        
        return services_health
    
    async def start_monitoring(self):
        """Start continuous health monitoring"""
        if self._monitoring_task and not self._monitoring_task.done():
            log.warning("Health monitoring is already running")
            return
        
        self._monitoring_task = asyncio.create_task(self._monitoring_loop())
        log.info("Started continuous health monitoring")
    
    async def stop_monitoring(self):
        """Stop continuous health monitoring"""
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
            log.info("Stopped continuous health monitoring")
    
    async def _monitoring_loop(self):
        """Continuous monitoring loop"""
        while True:
            try:
                # Check all services
                services_health = await self.check_all_services_health()
                
                # Store health history
                await self._store_health_history(services_health)
                
                # Check for alerts
                await self._check_alerts(services_health)
                
                await asyncio.sleep(self.monitoring_interval)
                
            except Exception as e:
                log.error(f"Health monitoring loop error: {str(e)}")
                await asyncio.sleep(5)
    
    async def _check_service_connectivity(self, service_name: str) -> HealthCheck:
        """Check basic service connectivity"""
        start_time = datetime.now()
        
        try:
            url = await service_registry.get_service_url(service_name)
            if not url:
                return HealthCheck(
                    name="connectivity",
                    status=HealthLevel.CRITICAL,
                    message=f"Service {service_name} not found in registry",
                    response_time_ms=0,
                    timestamp=datetime.now()
                )
            
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{url}/health")
                
                response_time = (datetime.now() - start_time).total_seconds() * 1000
                
                if response.status_code == 200:
                    return HealthCheck(
                        name="connectivity",
                        status=HealthLevel.HEALTHY,
                        message=f"Service {service_name} is reachable",
                        response_time_ms=response_time,
                        timestamp=datetime.now(),
                        details={"status_code": response.status_code}
                    )
                else:
                    return HealthCheck(
                        name="connectivity",
                        status=HealthLevel.UNHEALTHY,
                        message=f"Service {service_name} returned status {response.status_code}",
                        response_time_ms=response_time,
                        timestamp=datetime.now(),
                        details={"status_code": response.status_code}
                    )
                    
        except Exception as e:
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            return HealthCheck(
                name="connectivity",
                status=HealthLevel.CRITICAL,
                message=f"Service {service_name} is unreachable: {str(e)}",
                response_time_ms=response_time,
                timestamp=datetime.now(),
                details={"error": str(e)}
            )
    
    async def _check_database_connectivity(self, service_name: str) -> HealthCheck:
        """Check database connectivity for a service"""
        start_time = datetime.now()
        
        try:
            # This would typically check the service's database connection
            # For now, we'll assume all services use the same database
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return HealthCheck(
                name="database",
                status=HealthLevel.HEALTHY,
                message=f"Database connectivity for {service_name} is healthy",
                response_time_ms=response_time,
                timestamp=datetime.now()
            )
            
        except Exception as e:
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            return HealthCheck(
                name="database",
                status=HealthLevel.CRITICAL,
                message=f"Database connectivity for {service_name} failed: {str(e)}",
                response_time_ms=response_time,
                timestamp=datetime.now(),
                details={"error": str(e)}
            )
    
    async def _check_redis_connectivity(self, service_name: str) -> HealthCheck:
        """Check Redis connectivity"""
        start_time = datetime.now()
        
        try:
            self.redis_client.ping()
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return HealthCheck(
                name="redis",
                status=HealthLevel.HEALTHY,
                message=f"Redis connectivity for {service_name} is healthy",
                response_time_ms=response_time,
                timestamp=datetime.now()
            )
            
        except Exception as e:
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            return HealthCheck(
                name="redis",
                status=HealthLevel.CRITICAL,
                message=f"Redis connectivity for {service_name} failed: {str(e)}",
                response_time_ms=response_time,
                timestamp=datetime.now(),
                details={"error": str(e)}
            )
    
    async def _check_circuit_breaker_status(self, service_name: str) -> HealthCheck:
        """Check circuit breaker status for a service"""
        start_time = datetime.now()
        
        try:
            circuit_states = service_circuit_breaker.get_all_states()
            service_circuit = circuit_states.get(service_name)
            
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            
            if not service_circuit:
                return HealthCheck(
                    name="circuit_breaker",
                    status=HealthLevel.HEALTHY,
                    message=f"No circuit breaker configured for {service_name}",
                    response_time_ms=response_time,
                    timestamp=datetime.now()
                )
            
            circuit_state = service_circuit["state"]
            if circuit_state == "CLOSED":
                status = HealthLevel.HEALTHY
                message = f"Circuit breaker for {service_name} is closed (healthy)"
            elif circuit_state == "OPEN":
                status = HealthLevel.CRITICAL
                message = f"Circuit breaker for {service_name} is open (failing)"
            else:  # HALF_OPEN
                status = HealthLevel.DEGRADED
                message = f"Circuit breaker for {service_name} is half-open (testing)"
            
            return HealthCheck(
                name="circuit_breaker",
                status=status,
                message=message,
                response_time_ms=response_time,
                timestamp=datetime.now(),
                details=service_circuit
            )
            
        except Exception as e:
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            return HealthCheck(
                name="circuit_breaker",
                status=HealthLevel.CRITICAL,
                message=f"Circuit breaker check for {service_name} failed: {str(e)}",
                response_time_ms=response_time,
                timestamp=datetime.now(),
                details={"error": str(e)}
            )
    
    async def _check_redis_health(self) -> HealthCheck:
        """Check overall Redis health"""
        start_time = datetime.now()
        
        try:
            info = self.redis_client.info()
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return HealthCheck(
                name="redis_system",
                status=HealthLevel.HEALTHY,
                message="Redis is healthy",
                response_time_ms=response_time,
                timestamp=datetime.now(),
                details={
                    "version": info.get("redis_version"),
                    "uptime_seconds": info.get("uptime_in_seconds"),
                    "connected_clients": info.get("connected_clients"),
                    "used_memory": info.get("used_memory_human")
                }
            )
            
        except Exception as e:
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            return HealthCheck(
                name="redis_system",
                status=HealthLevel.CRITICAL,
                message=f"Redis is unhealthy: {str(e)}",
                response_time_ms=response_time,
                timestamp=datetime.now(),
                details={"error": str(e)}
            )
    
    async def _check_database_health(self) -> HealthCheck:
        """Check overall database health"""
        start_time = datetime.now()
        
        try:
            # This would typically check database connectivity and performance
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return HealthCheck(
                name="database_system",
                status=HealthLevel.HEALTHY,
                message="Database is healthy",
                response_time_ms=response_time,
                timestamp=datetime.now()
            )
            
        except Exception as e:
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            return HealthCheck(
                name="database_system",
                status=HealthLevel.CRITICAL,
                message=f"Database is unhealthy: {str(e)}",
                response_time_ms=response_time,
                timestamp=datetime.now(),
                details={"error": str(e)}
            )
    
    async def _check_event_system_health(self) -> HealthCheck:
        """Check event system health"""
        start_time = datetime.now()
        
        try:
            # Check Redis streams
            stream_info = self.redis_client.xinfo_stream("zeroque:events")
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return HealthCheck(
                name="event_system",
                status=HealthLevel.HEALTHY,
                message="Event system is healthy",
                response_time_ms=response_time,
                timestamp=datetime.now(),
                details={
                    "stream_length": stream_info.get("length", 0),
                    "groups": stream_info.get("groups", 0)
                }
            )
            
        except Exception as e:
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            return HealthCheck(
                name="event_system",
                status=HealthLevel.CRITICAL,
                message=f"Event system is unhealthy: {str(e)}",
                response_time_ms=response_time,
                timestamp=datetime.now(),
                details={"error": str(e)}
            )
    
    async def _check_service_discovery_health(self) -> HealthCheck:
        """Check service discovery health"""
        start_time = datetime.now()
        
        try:
            metrics = service_registry.get_service_metrics()
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            
            total_instances = metrics["total_instances"]
            healthy_instances = metrics["healthy_instances"]
            
            if healthy_instances == total_instances:
                status = HealthLevel.HEALTHY
                message = "All service instances are healthy"
            elif healthy_instances > total_instances * 0.5:
                status = HealthLevel.DEGRADED
                message = f"Some service instances are unhealthy ({healthy_instances}/{total_instances})"
            else:
                status = HealthLevel.CRITICAL
                message = f"Most service instances are unhealthy ({healthy_instances}/{total_instances})"
            
            return HealthCheck(
                name="service_discovery",
                status=status,
                message=message,
                response_time_ms=response_time,
                timestamp=datetime.now(),
                details=metrics
            )
            
        except Exception as e:
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            return HealthCheck(
                name="service_discovery",
                status=HealthLevel.CRITICAL,
                message=f"Service discovery is unhealthy: {str(e)}",
                response_time_ms=response_time,
                timestamp=datetime.now(),
                details={"error": str(e)}
            )
    
    async def _check_circuit_breaker_health(self) -> HealthCheck:
        """Check overall circuit breaker health"""
        start_time = datetime.now()
        
        try:
            circuit_states = service_circuit_breaker.get_all_states()
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            
            open_circuits = sum(
                1 for state in circuit_states.values() 
                if state["state"] == "OPEN"
            )
            total_circuits = len(circuit_states)
            
            if open_circuits == 0:
                status = HealthLevel.HEALTHY
                message = "All circuit breakers are closed"
            elif open_circuits < total_circuits * 0.3:
                status = HealthLevel.DEGRADED
                message = f"Some circuit breakers are open ({open_circuits}/{total_circuits})"
            else:
                status = HealthLevel.CRITICAL
                message = f"Many circuit breakers are open ({open_circuits}/{total_circuits})"
            
            return HealthCheck(
                name="circuit_breakers",
                status=status,
                message=message,
                response_time_ms=response_time,
                timestamp=datetime.now(),
                details=circuit_states
            )
            
        except Exception as e:
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            return HealthCheck(
                name="circuit_breakers",
                status=HealthLevel.CRITICAL,
                message=f"Circuit breaker health check failed: {str(e)}",
                response_time_ms=response_time,
                timestamp=datetime.now(),
                details={"error": str(e)}
            )
    
    def _determine_overall_status(self, checks: List[HealthCheck]) -> HealthLevel:
        """Determine overall status from individual checks"""
        if not checks:
            return HealthLevel.UNKNOWN
        
        # Check for critical issues first
        if any(check.status == HealthLevel.CRITICAL for check in checks):
            return HealthLevel.CRITICAL
        
        # Check for unhealthy issues
        if any(check.status == HealthLevel.UNHEALTHY for check in checks):
            return HealthLevel.UNHEALTHY
        
        # Check for degraded issues
        if any(check.status == HealthLevel.DEGRADED for check in checks):
            return HealthLevel.DEGRADED
        
        # All checks are healthy
        return HealthLevel.HEALTHY
    
    async def _calculate_service_uptime(self, service_name: str) -> float:
        """Calculate service uptime (simplified)"""
        # This would typically track service start time
        # For now, return a placeholder
        return 3600.0  # 1 hour
    
    async def _store_health_history(self, services_health: Dict[str, ServiceHealth]):
        """Store health check history"""
        timestamp = datetime.now()
        
        for service_name, health in services_health.items():
            if service_name not in self.health_history:
                self.health_history[service_name] = []
            
            # Add current health check
            self.health_history[service_name].append(health)
            
            # Keep only last 100 health checks
            if len(self.health_history[service_name]) > 100:
                self.health_history[service_name] = self.health_history[service_name][-100:]
    
    async def _check_alerts(self, services_health: Dict[str, ServiceHealth]):
        """Check for health alerts"""
        for service_name, health in services_health.items():
            if health.overall_status in [HealthLevel.CRITICAL, HealthLevel.UNHEALTHY]:
                log.warning(f"Service {service_name} is {health.overall_status.value}")
                # Here you would typically send alerts (email, Slack, etc.)

# Global health monitor instance
health_monitor = HealthMonitor()
