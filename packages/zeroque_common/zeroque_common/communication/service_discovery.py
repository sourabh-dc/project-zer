# packages/zeroque_common/zeroque_common/communication/service_discovery.py
"""
Service Discovery Implementation for ZeroQue Services

This module provides service discovery capabilities for dynamic service
registration, health checking, and load balancing.
"""

import os
import asyncio
import httpx
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

log = logging.getLogger(__name__)

class ServiceStatus(Enum):
    """Service health status"""
    HEALTHY = "HEALTHY"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"
    STARTING = "STARTING"
    STOPPING = "STOPPING"

@dataclass
class ServiceInstance:
    """Service instance information"""
    service_name: str
    instance_id: str
    host: str
    port: int
    status: ServiceStatus
    last_health_check: datetime
    metadata: Dict[str, Any]
    version: str = "1.0.0"
    
    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"
    
    @property
    def is_healthy(self) -> bool:
        return (
            self.status == ServiceStatus.HEALTHY and
            datetime.now() - self.last_health_check < timedelta(minutes=5)
        )

class ServiceRegistry:
    """Service registry for managing service instances"""
    
    def __init__(self):
        self.services: Dict[str, List[ServiceInstance]] = {}
        self.health_check_interval = 30  # seconds
        self.health_check_timeout = 5    # seconds
        self._health_check_task: Optional[asyncio.Task] = None
        
        # Default service configurations
        self.default_services = {
            "provisioning": {"port": 8201, "health_path": "/health"},
            "catalog": {"port": 8202, "health_path": "/health"},
            "entry": {"port": 8204, "health_path": "/health"},
            "billing": {"port": 8206, "health_path": "/health"},
            "orders": {"port": 8208, "health_path": "/health"},
            "pricing": {"port": 8209, "health_path": "/health"},
            "identity": {"port": 8210, "health_path": "/health"},
            "events": {"port": 8200, "health_path": "/health"},
            "observability": {"port": 8214, "health_path": "/health"}
        }
        
        log.info("ServiceRegistry initialized")
    
    async def register_service(self, service_name: str, instance_id: str,
                             host: str, port: int, metadata: Dict[str, Any] = None):
        """Register a service instance"""
        if service_name not in self.services:
            self.services[service_name] = []
        
        instance = ServiceInstance(
            service_name=service_name,
            instance_id=instance_id,
            host=host,
            port=port,
            status=ServiceStatus.STARTING,
            last_health_check=datetime.now(),
            metadata=metadata or {}
        )
        
        # Check if instance already exists
        existing = next(
            (inst for inst in self.services[service_name] 
             if inst.instance_id == instance_id), None
        )
        
        if existing:
            # Update existing instance
            existing.host = host
            existing.port = port
            existing.metadata = metadata or {}
            existing.last_health_check = datetime.now()
            log.info(f"Updated service instance: {service_name}:{instance_id}")
        else:
            # Add new instance
            self.services[service_name].append(instance)
            log.info(f"Registered service instance: {service_name}:{instance_id}")
        
        # Start health checking if not already running
        if not self._health_check_task or self._health_check_task.done():
            self._health_check_task = asyncio.create_task(self._health_check_loop())
    
    async def deregister_service(self, service_name: str, instance_id: str):
        """Deregister a service instance"""
        if service_name in self.services:
            self.services[service_name] = [
                inst for inst in self.services[service_name]
                if inst.instance_id != instance_id
            ]
            log.info(f"Deregistered service instance: {service_name}:{instance_id}")
    
    async def discover_service(self, service_name: str) -> List[ServiceInstance]:
        """Discover healthy instances of a service"""
        if service_name not in self.services:
            # Try to discover from default configuration
            await self._discover_default_service(service_name)
        
        instances = self.services.get(service_name, [])
        healthy_instances = [inst for inst in instances if inst.is_healthy]
        
        if not healthy_instances:
            log.warning(f"No healthy instances found for service: {service_name}")
        
        return healthy_instances
    
    async def get_service_url(self, service_name: str, 
                            load_balancing: str = "round_robin") -> Optional[str]:
        """Get a service URL with load balancing"""
        instances = await self.discover_service(service_name)
        
        if not instances:
            return None
        
        if load_balancing == "round_robin":
            # Simple round-robin selection
            instance = instances[0]  # Could implement proper round-robin
        elif load_balancing == "random":
            import random
            instance = random.choice(instances)
        else:
            instance = instances[0]
        
        return instance.url
    
    async def health_check_service(self, instance: ServiceInstance) -> bool:
        """Perform health check on a service instance"""
        try:
            health_path = self.default_services.get(
                instance.service_name, {}
            ).get("health_path", "/health")
            
            async with httpx.AsyncClient(timeout=self.health_check_timeout) as client:
                response = await client.get(f"{instance.url}{health_path}")
                
                if response.status_code == 200:
                    instance.status = ServiceStatus.HEALTHY
                    instance.last_health_check = datetime.now()
                    return True
                else:
                    instance.status = ServiceStatus.UNHEALTHY
                    instance.last_health_check = datetime.now()
                    return False
                    
        except Exception as e:
            log.warning(f"Health check failed for {instance.service_name}:{instance.instance_id}: {str(e)}")
            instance.status = ServiceStatus.UNHEALTHY
            instance.last_health_check = datetime.now()
            return False
    
    async def _health_check_loop(self):
        """Continuous health checking loop"""
        log.info("Starting service health check loop")
        
        while True:
            try:
                for service_name, instances in self.services.items():
                    for instance in instances:
                        await self.health_check_service(instance)
                
                await asyncio.sleep(self.health_check_interval)
                
            except Exception as e:
                log.error(f"Health check loop error: {str(e)}")
                await asyncio.sleep(5)
    
    async def _discover_default_service(self, service_name: str):
        """Discover service using default configuration"""
        if service_name in self.default_services:
            config = self.default_services[service_name]
            
            # Try localhost discovery
            instance = ServiceInstance(
                service_name=service_name,
                instance_id=f"{service_name}-localhost",
                host="localhost",
                port=config["port"],
                status=ServiceStatus.UNKNOWN,
                last_health_check=datetime.now(),
                metadata={"discovered": True}
            )
            
            # Perform initial health check
            if await self.health_check_service(instance):
                await self.register_service(
                    service_name, instance.instance_id,
                    instance.host, instance.port, instance.metadata
                )
    
    def get_service_metrics(self) -> Dict[str, Any]:
        """Get service discovery metrics"""
        total_instances = sum(len(instances) for instances in self.services.values())
        healthy_instances = sum(
            len([inst for inst in instances if inst.is_healthy])
            for instances in self.services.values()
        )
        
        service_stats = {}
        for service_name, instances in self.services.items():
            healthy_count = len([inst for inst in instances if inst.is_healthy])
            service_stats[service_name] = {
                "total_instances": len(instances),
                "healthy_instances": healthy_count,
                "unhealthy_instances": len(instances) - healthy_count
            }
        
        return {
            "total_services": len(self.services),
            "total_instances": total_instances,
            "healthy_instances": healthy_instances,
            "unhealthy_instances": total_instances - healthy_instances,
            "service_stats": service_stats,
            "health_check_interval": self.health_check_interval
        }
    
    def get_all_services(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get all registered services"""
        result = {}
        for service_name, instances in self.services.items():
            result[service_name] = [
                {
                    "instance_id": inst.instance_id,
                    "host": inst.host,
                    "port": inst.port,
                    "url": inst.url,
                    "status": inst.status.value,
                    "is_healthy": inst.is_healthy,
                    "last_health_check": inst.last_health_check.isoformat(),
                    "version": inst.version,
                    "metadata": inst.metadata
                }
                for inst in instances
            ]
        return result

# Global service registry instance
service_registry = ServiceRegistry()
